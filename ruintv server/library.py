#!/usr/bin/env python3
"""
library.py — RUIN.TO local library daemon (port 8788)

Scans a folder, matches each video to a TMDB id, and serves it. Nothing here touches
the live site; the site asks this daemon and falls back to providers when it has nothing.

Two serving paths:
  * a browser-safe file (mp4/webm, h264/vp8/vp9/av1, aac/mp3/opus/vorbis) is byte-streamed
    with HTTP Range, straight from disk
  * anything else (mkv, HEVC, AC3, DTS) is remuxed ONCE by ffmpeg into fMP4 HLS in a cache
    folder, then served as a playlist

Matching, in order: a [tmdb-123] tag, an IMDb id (tt1234567), or a TMDB title+year search.
Whatever does not match is reported at /probe and can be fixed in library_overrides.json
without renaming anything.

Seek-bar sprites share relay.py's cache: the Supabase trickplay table indexes cue sheets whose
sheets live on the Drive pool (gdrive_accounts.json). A row hit is served with no build at all;
a miss builds locally, uploads the sheets, writes the row, and then serves from Drive. If the
Supabase keys or the Drive accounts are absent, sprites stay purely local and nothing breaks.

    python library.py --root "D:\\movies\\library" --cache "D:\\movies\\cache"

Endpoints:
    GET  /health
    GET  /index.json?tmdb=<id>      files for one film (what the site reads)
    GET  /index.json                the whole index
    GET  /file/<tmdb>/<i>           direct bytes, Range supported
    GET  /stream/<tmdb>/<i>         master playlist (builds on first request)
    GET  /stream/<tmdb>/<i>/<name>  child playlist / segments / init
    GET  /trick?id=<tmdb>&i=<n>     seek-bar sprite job for a local file (start / poll)
    GET  /trick/<tmdb>/thumbs.vtt   sprite cue sheet
    GET  /trick/<tmdb>/<sheet>.webp one sprite sheet
    GET  /subs/<tmdb>/<i>/<si>.vtt  sidecar subtitle as WebVTT
    GET  /probe                     what matched and what did not
    GET|POST /scan                  rescan
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.2.5"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ruin-library/" + VERSION

VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".ts", ".m2ts", ".mpg", ".mpeg"}
SUB_EXT = {".srt", ".vtt", ".ass", ".ssa"}
DIRECT_EXT = {".mp4", ".m4v", ".webm"}
DIRECT_VCODEC = {"h264", "vp8", "vp9", "av1"}
DIRECT_ACODEC = {"aac", "mp3", "opus", "vorbis"}

TMDB_TAG = re.compile(r"[\[(]tmdb[-_ ]?(\d+)[\])]", re.I)
IMDB_TAG = re.compile(r"\b(tt\d{7,9})\b")
YEAR_RE = re.compile(r"(19|20)\d{2}")

JUNK = re.compile(
    r"\b(1080p|720p|2160p|480p|4k|bluray|blu-?ray|web-?dl|webrip|web|hdtv|brrip|bdrip|dvdrip|remux|"
    r"x264|x265|h\.?264|h\.?265|hevc|avc|10bit|8bit|aac|ac3|dts|ddp?5\.1|atmos|proper|repack|extended|"
    r"unrated|remastered|imax|yify|yts|rarbg|galaxyrg|multi|dual|subbed|dubbed)\b",
    re.I,
)

MIN_FREE_BYTES = 8 * 1024 ** 3
HLS_TIME = 6
BUILD_WAIT = 600          # a feature-length remux takes minutes; the request is held, not failed

# seek-bar sprites: one frame every TRICK_INTERVAL seconds, tiled TRICK_COLS x TRICK_ROWS per sheet
TRICK_INTERVAL = 10
TRICK_COLS = 10
TRICK_ROWS = 10
TRICK_W = 288
TRICK_H = 162
TRICK_QUALITY = 55
TRICK_MAX_SHEETS = 40
TRICK_TIMEOUT = 1800
# The player asks for sprites the instant it opens, which is also when the film starts streaming off the same
# disk. Waiting a moment lets playback buffer before ffmpeg starts reading.
TRICK_DELAY = 12
TRICK_THREADS = 2

# Drive pool + Postgres index, shared with relay.py. A sheet id becomes a public CDN reference.
DRIVE_REF = "https://lh3.googleusercontent.com/d/%s=s0"
GDRIVE_CAP_BYTES = int(14.2 * 1024 * 1024 * 1024)
GDRIVE_TOKEN_CACHE: dict[str, tuple[str, float]] = {}

ROOT = Path(".")
CACHE = Path("library_cache")
OVERRIDES_PATH = Path("library_overrides.json")
INDEX_PATH = Path("library.json")

LIB: dict[str, list[dict]] = {}
UNMATCHED: list[dict] = []
OVERRIDES: dict[str, int] = {}
LIB_LOCK = threading.Lock()
BUILDS: dict[str, threading.Event] = {}
BUILDS_LOCK = threading.Lock()
TRICKS: dict[str, dict] = {}
TRICKS_LOCK = threading.Lock()
LAST_TRICK: dict[str, str] = {}
RESCANNING = threading.Event()
TMDB_KEY = ""
FFMPEG = ""
FFPROBE = ""


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def http_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def config_value(key: str) -> str:
    """Look a key up in the environment, then .env, then config.json."""
    val = os.environ.get(key, "").strip()
    if val:
        return val
    for name in (".env", "config.json"):
        p = Path(__file__).parent / name
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if name.endswith(".json"):
            try:
                got = str(json.loads(text).get(key) or "").strip()
                if got:
                    return got
            except ValueError:
                pass
        else:
            for line in text.splitlines():
                if line.strip().startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def tmdb_key() -> str:
    return config_value("TMDB_KEY")


def find_ffmpeg() -> tuple[str, str]:
    candidates = [
        os.environ.get("FFMPEG_BIN", ""),
        r"D:\my development work\development tools\ffmpeg\bin\ffmpeg.exe",
        "ffmpeg",
    ]
    ff = ""
    for c in candidates:
        if not c:
            continue
        if os.path.isabs(c) and os.path.isfile(c):
            ff = c
            break
        if not os.path.isabs(c):
            hit = shutil.which(c)
            if hit:
                ff = hit
                break
    if not ff:
        return "", ""
    base = os.path.dirname(ff)
    probe = os.path.join(base, "ffprobe.exe" if os.name == "nt" else "ffprobe")
    return ff, probe if os.path.isfile(probe) else ""


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #

def clean_title(name: str) -> str:
    stem = Path(name).stem
    stem = TMDB_TAG.sub(" ", stem)
    stem = IMDB_TAG.sub(" ", stem)
    stem = re.sub(r"[._]+", " ", stem)
    stem = JUNK.sub(" ", stem)
    stem = re.sub(r"\s{2,}", " ", stem).strip(" -[]()")
    return stem.strip()


def year_of(name: str) -> str:
    m = YEAR_RE.search(Path(name).stem)
    return m.group(0) if m else ""


def match_file(path: Path) -> int | None:
    name = path.name
    key = str(path.relative_to(ROOT)).replace("\\", "/")
    if key in OVERRIDES:
        return OVERRIDES[key]

    m = TMDB_TAG.search(name)
    if m:
        return int(m.group(1))

    m = IMDB_TAG.search(name)
    if m and TMDB_KEY:
        try:
            data = http_json(
                f"https://api.themoviedb.org/3/find/{m.group(1)}"
                f"?api_key={TMDB_KEY}&external_source=imdb_id"
            )
            hits = data.get("movie_results") or []
            if hits:
                return int(hits[0]["id"])
        except Exception as e:
            log(f"imdb lookup {m.group(1)}: {e}")

    if not TMDB_KEY:
        return None
    title = clean_title(name)
    if len(title) < 2:
        return None
    year = year_of(name)
    try:
        q = urllib.parse.urlencode({"api_key": TMDB_KEY, "query": title, **({"year": year} if year else {})})
        data = http_json(f"https://api.themoviedb.org/3/search/movie?{q}")
        hits = data.get("results") or []
    except Exception as e:
        log(f"search {title!r}: {e}")
        return None
    if not hits:
        return None
    first = hits[0]
    if year and (first.get("release_date") or "")[:4] != year:
        return None
    if (first.get("title") or "").strip().lower() != title.lower():
        return None
    return int(first["id"])


def probe(path: Path) -> tuple[bool, int, int]:
    """(browser can play it directly, height, seconds)"""
    ext = path.suffix.lower()
    if not FFPROBE:
        return ext in DIRECT_EXT, 0, 0
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-print_format", "json",
             "-show_streams", "-show_format", str(path)],
            capture_output=True, timeout=25,
        )
        info = json.loads(out.stdout.decode("utf-8", "replace") or "{}")
    except Exception:
        return ext in DIRECT_EXT, 0, 0
    v = next((s for s in info.get("streams") or [] if s.get("codec_type") == "video"), None)
    a = [s for s in info.get("streams") or [] if s.get("codec_type") == "audio"]
    if not v:
        return False, 0, 0
    height = int(v.get("height") or 0)
    vc = (v.get("codec_name") or "").lower()
    acs = [(s.get("codec_name") or "").lower() for s in a]
    direct = ext in DIRECT_EXT and vc in DIRECT_VCODEC and all(c in DIRECT_ACODEC for c in acs)
    try:
        seconds = int(float((info.get("format") or {}).get("duration") or 0))
    except (TypeError, ValueError):
        seconds = 0
    return direct, height, seconds


def sidecar_subs(path: Path) -> list[dict]:
    out = []
    try:
        entries = list(path.parent.iterdir())
    except OSError:
        return out
    for cand in entries:
        if not cand.is_file() or cand.suffix.lower() not in SUB_EXT:
            continue
        if cand.stem != path.stem:
            continue
        lang = "und"
        m = re.search(r"\.([a-z]{2,3})$", cand.stem)
        if m and cand.stem.lower().endswith(m.group(0)) and len(cand.stem) > len(path.stem):
            lang = m.group(1)
        out.append({"path": cand, "lang": lang, "label": lang.upper()})
    return out


def scan() -> None:
    global UNMATCHED
    if not ROOT.exists():
        log(f"root missing: {ROOT}")
        return
    lib: dict[str, list[dict]] = {}
    unmatched: list[dict] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXT:
            continue
        if CACHE.resolve() in path.resolve().parents:
            continue
        tmdb = match_file(path)
        if not tmdb:
            unmatched.append({"file": str(path.relative_to(ROOT)), "title": clean_title(path.name)})
            continue
        direct, height, seconds = probe(path)
        try:
            stat = path.stat()
        except OSError:
            continue
        lib.setdefault(str(tmdb), []).append({
            "path": path,
            "direct": direct,
            "height": height,
            "seconds": seconds,
            "subs": sidecar_subs(path),
            "mtime": stat.st_mtime,
            "size": stat.st_size,
        })
    with LIB_LOCK:
        LIB.clear()
        LIB.update(lib)
        UNMATCHED = unmatched
    total = sum(len(v) for v in lib.values())
    log(f"scan: {total} file(s) matched, {len(unmatched)} unmatched")
    try:
        INDEX_PATH.write_text(json.dumps(
            {k: [{"file": str(e["path"].relative_to(ROOT)), "direct": e["direct"]} for e in v]
             for k, v in lib.items()}, indent=1), encoding="utf-8")
    except OSError:
        pass


def scan_soon() -> None:
    """One background rescan at a time, however many requests notice a missing file."""
    if RESCANNING.is_set():
        return
    RESCANNING.set()

    def run():
        try:
            scan()
        finally:
            RESCANNING.clear()

    threading.Thread(target=run, daemon=True).start()


def forget(path: Path) -> None:
    """Drop an entry whose file has gone, so the site stops offering it."""
    removed = False
    with LIB_LOCK:
        for tmdb, items in list(LIB.items()):
            kept = [e for e in items if e["path"] != path]
            if len(kept) != len(items):
                removed = True
                if kept:
                    LIB[tmdb] = kept
                else:
                    LIB.pop(tmdb, None)
    if removed:
        log(f"file gone, dropped from the index: {path.name}")
        scan_soon()


# --------------------------------------------------------------------------- #
# HLS cache
# --------------------------------------------------------------------------- #

def cache_key(path: Path, mtime: float, size: int) -> str:
    return hashlib.sha1(f"{path}|{mtime}|{size}".encode()).hexdigest()[:16]


def cache_dir(key: str) -> Path:
    d = CACHE / key
    d.mkdir(parents=True, exist_ok=True)
    return d


# What FFMPEG has to produce before a directory is usable. The master is NOT in here: it is written by us
# afterwards, so a check that included it could never pass.
def outputs_present(key: str) -> bool:
    out = CACHE / key
    return ((out / "index.m3u8").exists()
            and (out / "init.mp4").exists()
            and any(out.glob("seg*.m4s")))


# What the handler needs: ffmpeg's output plus the master on top of it.
def build_complete(key: str) -> bool:
    return outputs_present(key) and (CACHE / key / "master.m3u8").exists()


def missing_parts(key: str) -> str:
    out = CACHE / key
    gaps = []
    if not (out / "index.m3u8").exists():
        gaps.append("index.m3u8")
    if not (out / "init.mp4").exists():
        gaps.append("init.mp4")
    if not any(out.glob("seg*.m4s")):
        gaps.append("segments")
    if not (out / "master.m3u8").exists():
        gaps.append("master")
    return ", ".join(gaps) or "nothing"


def clear_build(key: str) -> None:
    out = CACHE / key
    if not out.is_dir():
        return
    for pattern in ("master.m3u8", "index.m3u8", "init.mp4", "seg*.m4s"):
        for f in out.glob(pattern):
            try:
                f.unlink()
            except OSError:
                pass


def write_master(key: str, height: int = 0) -> None:
    # The variant carries the real height, so the quality menu reads 720p for a 720p file instead of a
    # hardcoded 1080p. RESOLUTION is also the attribute hls.js names a level from.
    h = max(144, min(height or 1080, 2160))
    w = int(round(h * 16 / 9 / 2)) * 2
    (CACHE / key / "master.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:7\n"
        f'#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION={w}x{h},CODECS="avc1.640028,mp4a.40.2"\n'
        "index.m3u8\n", encoding="utf-8")


def prune_cache() -> None:
    if not CACHE.exists():
        return
    try:
        free = shutil.disk_usage(str(CACHE)).free
    except OSError:
        return
    if free >= MIN_FREE_BYTES:
        return
    dirs = sorted((d for d in CACHE.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime)
    for d in dirs:
        if free >= MIN_FREE_BYTES:
            break
        size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        shutil.rmtree(d, ignore_errors=True)
        free += size
        log(f"pruned {d.name} ({size // 1024 ** 2} MB)")


def build(key: str, src: Path, height: int = 0) -> None:
    if build_complete(key):
        return
    # ffmpeg already finished its part but the master is missing: just write the master, no need to encode again.
    if outputs_present(key):
        write_master(key, height)
        log(f"master written for {src.name} (outputs were already there)")
        return
    if not FFMPEG:
        log("ffmpeg not found, cannot remux")
        return
    clear_build(key)          # drop a partial leftover before starting over
    prune_cache()
    out = cache_dir(key)
    # Every output name below is RELATIVE and ffmpeg is run with cwd=out. A bare
    # -hls_fmp4_init_filename is resolved against the working directory, not against the playlist path,
    # so an absolute playlist alone left init.mp4 next to library.py and the cache never held it.
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ac", "2",
        "-force_key_frames", f"expr:gte(t,n_forced*{HLS_TIME})",
        "-f", "hls", "-hls_time", str(HLS_TIME), "-hls_playlist_type", "event",
        "-hls_segment_type", "fmp4",
        "-hls_fmp4_init_filename", "init.mp4",
        "-hls_segment_filename", "seg%05d.m4s",
        "index.m3u8",
    ]
    log(f"remux start {src.name}")
    try:
        subprocess.run(cmd, check=True, timeout=6 * 3600, cwd=str(out),
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        log(f"remux failed {src.name}: {e.stderr.decode('utf-8', 'replace')[-300:]}")
        return
    except subprocess.TimeoutExpired:
        log(f"remux timed out {src.name}")
        return
    if not outputs_present(key):
        log(f"remux left an incomplete set for {src.name} (missing {missing_parts(key)}), not writing the master")
        return
    write_master(key, height)
    log(f"remux done {src.name}")


def _build_thread(key: str, src: Path, height: int, ev: threading.Event) -> None:
    try:
        build(key, src, height)
    except Exception as exc:
        log(f"remux crashed {src.name}: {exc}")
    finally:
        # the finished event MUST leave the table, otherwise every later request finds an already-set event,
        # waits 0 ms and answers 503 without ever starting another build
        with BUILDS_LOCK:
            BUILDS.pop(key, None)
        ev.set()


def ensure_built(key: str, src: Path, height: int = 0) -> threading.Event:
    with BUILDS_LOCK:
        ev = BUILDS.get(key)
        if ev is None:
            ev = threading.Event()
            BUILDS[key] = ev
            threading.Thread(target=_build_thread, args=(key, src, height, ev), daemon=True).start()
        return ev


# --------------------------------------------------------------------------- #
# trickplay: Supabase index + Drive pool, shared with relay.py
# --------------------------------------------------------------------------- #

def supabase_cfg() -> tuple[str, str]:
    return config_value("SUPABASE_URL").rstrip("/"), config_value("SUPABASE_KEY")


def supabase_get_trick(tmdb: str) -> dict | None:
    sb_url, sb_key = supabase_cfg()
    if not sb_url or not sb_key:
        return None
    url = "%s/rest/v1/trickplay?tmdb_id=eq.%s&select=*" % (sb_url, urllib.parse.quote(str(tmdb)))
    req = urllib.request.Request(url, headers={
        "apikey": sb_key, "Authorization": "Bearer " + sb_key, "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            rows = json.loads(resp.read().decode("utf-8", "replace"))
            return rows[0] if isinstance(rows, list) and rows else None
    except Exception as exc:
        log(f"trick supabase get err: {exc}")
        return None


def supabase_save_trick(row: dict) -> bool:
    sb_url, sb_key = supabase_cfg()
    if not sb_url or not sb_key:
        return False
    req = urllib.request.Request(
        "%s/rest/v1/trickplay" % sb_url,
        data=json.dumps(row).encode("utf-8"),
        headers={
            "apikey": sb_key,
            "Authorization": "Bearer " + sb_key,
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201)
    except Exception as exc:
        log(f"trick supabase save err: {exc}")
        return False


def gdrive_cfg_path() -> Path | None:
    """auth_gdrive.py writes next to itself, which is relay.py's folder. Check there too."""
    override = config_value("GDRIVE_CFG")
    candidates = []
    if override:
        candidates.append(Path(override))
    here = Path(__file__).parent
    candidates.append(here / "gdrive_accounts.json")
    candidates.append(here.parent / "ruin-stream" / "gdrive_accounts.json")
    for c in candidates:
        if c.is_file():
            return c
    return None


def gdrive_pick_account():
    path = gdrive_cfg_path()
    if not path:
        return None, None
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, None

    accounts = cfg.get("accounts") or []
    if not accounts:
        return None, None

    # spread sheets over accounts: keep using one until it nears the 15 GB cap
    usage = {a["email"]: 0 for a in accounts if a.get("email")}
    sb_url, sb_key = supabase_cfg()
    if sb_url and sb_key:
        try:
            req = urllib.request.Request(
                "%s/rest/v1/trickplay?select=account_email,size_bytes" % sb_url,
                headers={"apikey": sb_key, "Authorization": "Bearer " + sb_key},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                for r in json.loads(resp.read().decode("utf-8", "replace")) or []:
                    em = r.get("account_email")
                    if em in usage:
                        try:
                            usage[em] += int(r.get("size_bytes") or 0)
                        except (TypeError, ValueError):
                            pass
        except Exception:
            pass

    for acc in accounts:
        em = acc.get("email")
        if em and usage.get(em, 0) < GDRIVE_CAP_BYTES:
            return cfg, acc
    return cfg, accounts[-1]


def gdrive_access_token(cfg: dict, acc: dict) -> str:
    email = acc["email"]
    cached = GDRIVE_TOKEN_CACHE.get(email)
    if cached and cached[1] > time.time() + 60:
        return cached[0]

    data = urllib.parse.urlencode({
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": acc["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req, timeout=12) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    token = payload["access_token"]
    GDRIVE_TOKEN_CACHE[email] = (token, time.time() + int(payload.get("expires_in", 3500)))
    return token


def gdrive_upload_public_webp(token: str, filename: str, raw_bytes: bytes, folder_id: str = "") -> str:
    boundary = "----RuinTrickBoundary987654321"
    meta_obj = {"name": filename, "mimeType": "image/webp"}
    if folder_id:
        meta_obj["parents"] = [folder_id]
    meta = json.dumps(meta_obj).encode("utf-8")
    body = (
        b"--" + boundary.encode() + b"\r\n"
        b"Content-Type: application/json; charset=UTF-8\r\n\r\n" + meta + b"\r\n"
        b"--" + boundary.encode() + b"\r\n"
        b"Content-Type: image/webp\r\n\r\n" + raw_bytes + b"\r\n"
        b"--" + boundary.encode() + b"--\r\n"
    )
    up_req = urllib.request.Request(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id",
        data=body,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "multipart/related; boundary=" + boundary,
        },
        method="POST",
    )
    with urllib.request.urlopen(up_req, timeout=30) as resp:
        file_id = json.loads(resp.read().decode("utf-8", "replace"))["id"]

    perm_req = urllib.request.Request(
        "https://www.googleapis.com/drive/v3/files/%s/permissions" % file_id,
        data=b'{"role":"reader","type":"anyone"}',
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(perm_req, timeout=15) as resp:
        resp.read()

    return file_id


# --------------------------------------------------------------------------- #
# seek-bar sprites (built from the local file, indexed globally)
# --------------------------------------------------------------------------- #

def trick_vtt_time(secs: int) -> str:
    return "%02d:%02d:%02d.000" % (secs // 3600, (secs % 3600) // 60, secs % 60)


def trick_vtt_text(refs: list[str], seconds: int) -> tuple[str, int]:
    per_sheet = TRICK_COLS * TRICK_ROWS
    total = len(refs) * per_sheet
    if seconds > 0:
        total = min(total, int(seconds / TRICK_INTERVAL) + 1)
    lines = ["WEBVTT", ""]
    for index in range(total):
        start = index * TRICK_INTERVAL
        ref = refs[index // per_sheet]
        tile = index % per_sheet
        x = (tile % TRICK_COLS) * TRICK_W
        y = (tile // TRICK_COLS) * TRICK_H
        lines.append("%s --> %s" % (trick_vtt_time(start), trick_vtt_time(start + TRICK_INTERVAL)))
        lines.append("%s#xywh=%d,%d,%d,%d" % (ref, x, y, TRICK_W, TRICK_H))
        lines.append("")
    return "\n".join(lines), total


def trick_build(key: str, src: Path, seconds: int, tmdb: str) -> None:
    out = cache_dir(key) / "thumbs"
    out.mkdir(parents=True, exist_ok=True)
    vtt = out / "thumbs.vtt"
    if vtt.exists():
        with TRICKS_LOCK:
            TRICKS[key] = {"state": "ready"}
        return
    if not FFMPEG:
        with TRICKS_LOCK:
            TRICKS[key] = {"state": "failed", "error": "ffmpeg not found"}
        return
    # let the player fill its buffer before this starts hammering the same disk
    time.sleep(TRICK_DELAY)
    # -skip_frame nokey decodes only keyframes instead of every frame. A full decode of a feature-length
    # film read the whole 1.9 GB and starved the concurrent /file serve until its socket timed out.
    # -threads keeps it from taking every core while a film is playing.
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-skip_frame", "nokey", "-threads", str(TRICK_THREADS),
        "-i", str(src),
        "-vf", ("fps=1/%d,scale=%d:%d:force_original_aspect_ratio=decrease,"
                "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,tile=%dx%d"
                % (TRICK_INTERVAL, TRICK_W, TRICK_H, TRICK_W, TRICK_H, TRICK_COLS, TRICK_ROWS)),
        "-c:v", "libwebp", "-quality", str(TRICK_QUALITY), "-compression_level", "4",
        "-frames:v", str(TRICK_MAX_SHEETS), "-start_number", "0",
        "s%03d.webp",
    ]
    log(f"trick start {src.name}")
    try:
        subprocess.run(cmd, check=True, timeout=TRICK_TIMEOUT, cwd=str(out),
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        log(f"trick failed {src.name}: {e.stderr.decode('utf-8', 'replace')[-300:]}")
        with TRICKS_LOCK:
            TRICKS[key] = {"state": "failed", "error": "ffmpeg failed"}
        return
    except subprocess.TimeoutExpired:
        with TRICKS_LOCK:
            TRICKS[key] = {"state": "failed", "error": "timed out"}
        return

    sheets = sorted(f.name for f in out.glob("s*.webp"))
    if not sheets:
        with TRICKS_LOCK:
            TRICKS[key] = {"state": "failed", "error": "no sheets"}
        return

    # publish the sheets so the next account or device gets a cache hit instead of a rebuild
    cfg, acc = gdrive_pick_account()
    refs = list(sheets)
    sheet_ids: list[str] = []
    uploaded_email = ""
    total_bytes = 0
    if cfg and acc:
        try:
            token = gdrive_access_token(cfg, acc)
            folder_id = acc.get("folder_id") or cfg.get("folder_id") or ""
            refs = []
            for name in sheets:
                blob = (out / name).read_bytes()
                total_bytes += len(blob)
                fid = gdrive_upload_public_webp(token, "%s_%s" % (tmdb, name), blob, folder_id=folder_id)
                sheet_ids.append(fid)
                refs.append(DRIVE_REF % fid)
            uploaded_email = acc["email"]
            log(f"trick {src.name} uploaded {len(sheet_ids)} sheet(s) ({total_bytes / 1048576:.2f} MB) to {uploaded_email}")
        except Exception as up_exc:
            log(f"trick {src.name} gdrive upload err: {up_exc}")
            refs = list(sheets)
            sheet_ids = []

    text, total = trick_vtt_text(refs, seconds)
    vtt.write_text(text, encoding="utf-8")

    if uploaded_email and sheet_ids:
        supabase_save_trick({
            "tmdb_id": int(tmdb) if tmdb.isdigit() else tmdb,
            "account_email": uploaded_email,
            "vtt_text": text,
            "sheet_ids": sheet_ids,
            "frames": total,
            "interval": TRICK_INTERVAL,
            "cols": TRICK_COLS,
            "rows": TRICK_ROWS,
            "w": TRICK_W,
            "h": TRICK_H,
            "size_bytes": total_bytes,
        })

    with TRICKS_LOCK:
        TRICKS[key] = {"state": "ready", "frames": total, "vtt_text": text if uploaded_email else ""}
    log(f"trick done {src.name}: {total} frames")


def trick_status(tmdb: str, entry: dict) -> dict:
    key = cache_key(entry["path"], entry["mtime"], entry["size"])
    LAST_TRICK[tmdb] = key

    vtt = CACHE / key / "thumbs" / "thumbs.vtt"
    if vtt.exists():
        frames = len(list((CACHE / key / "thumbs").glob("s*.webp"))) * TRICK_COLS * TRICK_ROWS
        with TRICKS_LOCK:
            TRICKS[key] = {"state": "ready", "frames": frames}
        return {"state": "ready", "building": False, "frames": frames, "error": ""}

    with TRICKS_LOCK:
        st = TRICKS.get(key)
        if st is not None and st["state"] == "pending":
            return {"state": "pending", "building": True, "frames": 0, "error": ""}
        if st is not None and st["state"] == "failed":
            return {"state": "failed", "building": False, "frames": 0, "error": st.get("error", "")}
        if st is not None and st["state"] == "ready" and st.get("vtt_text"):
            return {"state": "ready", "building": False, "frames": st.get("frames", 0), "error": ""}

    # already built by anyone, for any account: serve the stored cue sheet, no build at all
    row = supabase_get_trick(tmdb)
    if row and row.get("vtt_text"):
        frames = int(row.get("frames") or 0)
        with TRICKS_LOCK:
            TRICKS[key] = {"state": "ready", "frames": frames, "vtt_text": row["vtt_text"]}
        log(f"trick {tmdb}: cache hit")
        return {"state": "ready", "building": False, "frames": frames, "error": ""}

    with TRICKS_LOCK:
        TRICKS[key] = {"state": "pending"}
        threading.Thread(target=trick_build, args=(key, entry["path"], entry["seconds"], tmdb),
                         daemon=True).start()
    return {"state": "pending", "building": True, "frames": 0, "error": ""}


# --------------------------------------------------------------------------- #
# subtitles
# --------------------------------------------------------------------------- #

def to_vtt(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1256", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")
    text = text.replace("\ufeff", "").replace("\r", "")
    if text.lstrip().upper().startswith("WEBVTT"):
        return text
    text = re.sub(r"(?m)^\d+[ \t]*\n(?=\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->)", "", text)
    text = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", text)
    return "WEBVTT\n\n" + text.strip() + "\n"


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

PROBE_PAGE = """<!doctype html><meta charset=utf-8><title>library probe</title>
<style>
body{background:#0b0b0d;color:#ddd;font:14px system-ui;padding:24px}
h1{font-size:15px;letter-spacing:.12em;text-transform:uppercase;color:#888}
h2{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#c8a24a;margin-top:28px}
table{width:100%;border-collapse:collapse}
td{padding:7px 8px;border-bottom:1px solid #1b1b20;font-size:13px}
.g{color:#6cc07a}.b{color:#d66}.m{color:#666}
code{color:#8a7d55;font-size:12px}
</style>
<h1>library probe</h1>
<p class="m">__COUNT__ file(s) matched, __BAD__ unmatched. Nothing is served from the unmatched list.</p>
__BODY__
<h2>fix a bad match</h2>
<p class="m">Add an entry to <code>library_overrides.json</code> keyed by the file path, then POST /scan:</p>
<p><code>{"Some Movie 2024.mkv": 12345}</code></p>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # a kept-alive connection may sit idle between segments; 300 s covers a paused player without
    # holding a thread forever. _serve_file raises it further for the duration of one large send.
    timeout = 300
    headers_sent = False

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.headers_sent = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def _base(self) -> str:
        host = (self.headers.get("Host") or "127.0.0.1:8788").split("/")[0]
        return "http://" + host

    def _lookup(self, tmdb: str, index: str):
        with LIB_LOCK:
            items = LIB.get(tmdb) or []
            if not items:
                return None, None
            try:
                return items, items[int(index)]
            except (ValueError, IndexError):
                return items, None

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()
        self.headers_sent = True

    def do_POST(self):
        self.headers_sent = False
        # drain the body, otherwise it stays on the socket and corrupts the NEXT request on this
        # keep-alive connection
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 0:
                self.rfile.read(min(length, 1 << 20))
        except (ValueError, OSError):
            pass
        try:
            if urllib.parse.urlparse(self.path).path == "/scan":
                scan()
                return self._send(200, json.dumps({"ok": True}))
            self._send(404, json.dumps({"error": "not found"}))
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self.headers_sent = False
        try:
            self._route()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            return                       # a seek or a closed tab: normal, and not worth a traceback
        except Exception as exc:
            log(f"500 {urllib.parse.urlsplit(self.path).path}: {exc}")
            if not self.headers_sent:
                try:
                    self._send(500, json.dumps({"error": str(exc)}))
                except Exception:
                    pass

    def _route(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        parts = [p for p in u.path.split("/") if p]

        if u.path == "/health":
            with LIB_LOCK:
                total = sum(len(v) for v in LIB.values())
            return self._send(200, json.dumps({"ok": True, "version": VERSION, "files": total,
                                               "ffmpeg": bool(FFMPEG)}))

        # GET as well as POST: grab.py pokes this after filing, and a GET poke used to 404 here.
        if u.path == "/scan":
            scan()
            return self._send(200, json.dumps({"ok": True}))

        if u.path == "/probe":
            body = []
            with LIB_LOCK:
                total = sum(len(v) for v in LIB.values())
                for tmdb, items in sorted(LIB.items(), key=lambda kv: int(kv[0])):
                    body.append(f'<h2>tmdb {tmdb}</h2><table>')
                    for i, e in enumerate(items):
                        mode = "direct" if e["direct"] else "remux"
                        body.append(f'<tr><td class="g">{e["path"].name}</td>'
                                    f'<td class="m">{mode} · {e["height"] or "?"}p · {len(e["subs"])} sub(s)</td></tr>')
                    body.append("</table>")
                if UNMATCHED:
                    body.append('<h2 class="b">unmatched</h2><table>')
                    for e in UNMATCHED:
                        body.append(f'<tr><td class="b">{e["file"]}</td>'
                                    f'<td class="m">title read as “{e["title"]}”</td></tr>')
                    body.append("</table>")
            html = PROBE_PAGE.replace("__COUNT__", str(total)).replace("__BAD__", str(len(UNMATCHED)))
            html = html.replace("__BODY__", "".join(body) or '<p class="m">nothing scanned yet</p>')
            return self._send(200, html, "text/html; charset=utf-8")

        if u.path == "/index.json":
            base = self._base()
            if "tmdb" in q:
                tmdb = (q["tmdb"] or [""])[0]
                with LIB_LOCK:
                    items = LIB.get(tmdb) or []
                    files = [{
                        "index": i,
                        "direct": e["direct"],
                        "kind": "mp4" if e["direct"] else "hls",
                        "height": e["height"],
                        "seconds": e["seconds"],
                        "subtitles": [
                            {"label": s["label"], "lang": s["lang"],
                             "url": f"{base}/subs/{tmdb}/{i}/{si}.vtt"}
                            for si, s in enumerate(e["subs"])
                        ],
                    } for i, e in enumerate(items)]
                return self._send(200, json.dumps({"tmdb": tmdb, "files": files}))
            with LIB_LOCK:
                return self._send(200, json.dumps(
                    {k: [{"file": str(e["path"].relative_to(ROOT)), "direct": e["direct"]} for e in v]
                     for k, v in LIB.items()}, indent=1))

        if len(parts) >= 3 and parts[0] == "file":
            items, entry = self._lookup(parts[1], parts[2])
            if not entry:
                return self._send(404, json.dumps({"error": "no such file"}))
            return self._serve_file(entry["path"])

        if len(parts) >= 3 and parts[0] == "stream":
            items, entry = self._lookup(parts[1], parts[2])
            if not entry:
                return self._send(404, json.dumps({"error": "no such file"}))
            if not entry["path"].exists():
                forget(entry["path"])
                return self._send(404, json.dumps({"error": "file gone"}))
            key = cache_key(entry["path"], entry["mtime"], entry["size"])
            if not build_complete(key):
                # rebuilds a missing init.mp4 / half-written set instead of serving a playlist hls.js cannot use
                ev = ensure_built(key, entry["path"], entry["height"])
                ev.wait(BUILD_WAIT)
            out = CACHE / key
            if not build_complete(key):
                return self._send(503, json.dumps({"error": "still remuxing", "missing": missing_parts(key)}),
                                  extra={"Retry-After": "5"})
            name = parts[3] if len(parts) > 3 else "master.m3u8"
            if name == "master.m3u8":
                # The child line in the file is a bare "index.m3u8". Rewrite it to carry the file index, so the
                # variant is fetched at /stream/<tmdb>/<i>/index.m3u8 and the index survives into every segment URL.
                text = (out / "master.m3u8").read_text(encoding="utf-8")
                text = re.sub(r"(?m)^index\.m3u8\s*$", f"{parts[2]}/index.m3u8", text)
                return self._send(200, text, "application/vnd.apple.mpegurl",
                                  extra={"Cache-Control": "no-store"})
            target = out / name
            if not target.exists():
                return self._send(404, json.dumps({"error": "not ready"}))
            ctype = ("application/vnd.apple.mpegurl" if name.endswith(".m3u8")
                     else "video/mp4" if name.endswith(".mp4") else "video/iso.segment")
            return self._send(200, target.read_bytes(), ctype,
                              extra={"Cache-Control": "public, max-age=31536000, immutable"})

        if len(parts) == 3 and parts[0] == "trick":
            tmdb, name = parts[1], parts[2]
            key = LAST_TRICK.get(tmdb)
            if not key:
                return self._send(404, json.dumps({"error": "no trick job"}))
            # a cue sheet published to Drive is held in memory; only the sheets come off disk
            if name == "thumbs.vtt":
                with TRICKS_LOCK:
                    st = dict(TRICKS.get(key) or {})
                if st.get("vtt_text"):
                    return self._send(200, st["vtt_text"], "text/vtt; charset=utf-8",
                                      extra={"Cache-Control": "public, max-age=31536000, immutable"})
            target = CACHE / key / "thumbs" / name
            if not target.exists():
                return self._send(404, json.dumps({"error": "not ready"}))
            ctype = "text/vtt; charset=utf-8" if name.endswith(".vtt") else "image/webp"
            return self._send(200, target.read_bytes(), ctype,
                              extra={"Cache-Control": "public, max-age=31536000, immutable"})

        if u.path == "/trick":
            tmdb = (q.get("id") or [""])[0]
            if not tmdb.isdigit():
                return self._send(400, json.dumps({"error": "bad id"}))
            items, entry = self._lookup(tmdb, (q.get("i") or ["0"])[0])
            if not entry:
                return self._send(404, json.dumps({"state": "failed", "error": "no such file"}))
            if not entry["path"].exists():
                forget(entry["path"])
                return self._send(404, json.dumps({"state": "failed", "error": "file gone"}))
            info = trick_status(tmdb, entry)
            return self._send(200, json.dumps({
                "state": info["state"],
                "building": info["building"],
                "vtt": ("/trick/%s/thumbs.vtt" % tmdb) if info["state"] == "ready" else "",
                "interval": TRICK_INTERVAL, "cols": TRICK_COLS, "rows": TRICK_ROWS,
                "w": TRICK_W, "h": TRICK_H,
                "frames": info["frames"], "done": info["frames"],
                "tries": 0, "error": info.get("error", ""),
            }))

        if len(parts) >= 5 and parts[0] == "subs":
            items, entry = self._lookup(parts[1], parts[2])
            if not entry:
                return self._send(404, json.dumps({"error": "no such file"}))
            try:
                sub = entry["subs"][int(parts[3].split(".")[0])]
            except (ValueError, IndexError):
                return self._send(404, json.dumps({"error": "no such subtitle"}))
            return self._send(200, to_vtt(sub["path"]), "text/vtt; charset=utf-8")

        self._send(404, json.dumps({"error": "not found"}))

    def _serve_file(self, path: Path):
        try:
            size = path.stat().st_size
        except OSError:
            forget(path)                      # deleted behind our back: drop the row and answer 404
            return self._send(404, json.dumps({"error": "file gone"}))
        # a large send stays open for as long as the player is playing. If the browser's buffer is full
        # the write blocks; without a generous timeout that block raised socket.timeout and 500'd mid-film.
        try:
            self.connection.settimeout(600)
        except OSError:
            pass
        rng = self.headers.get("Range") or ""
        start, end = 0, size - 1
        status = 200
        if rng.startswith("bytes="):
            spec = rng[6:].split(",")[0].strip()
            try:
                a, b = spec.split("-", 1)
                if a == "":
                    start, end = max(0, size - int(b)), size - 1
                else:
                    start = int(a)
                    end = int(b) if b else size - 1
                start, end = max(0, start), min(end, size - 1)
                if start > end:
                    raise ValueError
                status = 206
            except ValueError:
                start, end, status = 0, size - 1, 200
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4" if path.suffix.lower() in DIRECT_EXT else "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=3600")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        self.headers_sent = True
        if self.command == "HEAD":
            return
        with path.open("rb") as fh:
            fh.seek(start)
            left = length
            while left > 0:
                chunk = fh.read(min(262144, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (socket.timeout, TimeoutError):
                    # the player stopped reading for longer than the socket allowed: log and let it
                    # re-request with a Range rather than 500 the whole response
                    log(f"send stalled, dropping {path.name} at byte {start + (length - left)}")
                    return
                left -= len(chunk)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def load_overrides() -> dict[str, int]:
    try:
        data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
        return {k: int(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def main() -> None:
    global ROOT, CACHE, FFMPEG, FFPROBE, OVERRIDES, TMDB_KEY
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--cache", default="library_cache")
    ap.add_argument("--ffmpeg", default="")
    args = ap.parse_args()

    ROOT = Path(args.root).resolve()
    CACHE = Path(args.cache).resolve()
    CACHE.mkdir(parents=True, exist_ok=True)
    FFMPEG, FFPROBE = (args.ffmpeg, "") if args.ffmpeg else find_ffmpeg()
    if args.ffmpeg:
        base = os.path.dirname(args.ffmpeg)
        p = os.path.join(base, "ffprobe.exe")
        FFPROBE = p if os.path.isfile(p) else ""
    TMDB_KEY = tmdb_key()
    OVERRIDES = load_overrides()

    if not ROOT.is_dir():
        raise SystemExit(f"library: root missing: {ROOT}")
    if not TMDB_KEY:
        log("warning: no TMDB_KEY (env, .env or config.json) — only tagged files will match")
    if not FFMPEG:
        log("warning: ffmpeg not found — only direct-playable files will work")
    sb_url, sb_key = supabase_cfg()
    log(f"trick index: {'supabase ' + sb_url if sb_url and sb_key else 'local only (no SUPABASE_URL/SUPABASE_KEY)'}")
    log(f"drive pool: {gdrive_cfg_path() or 'none (sprites stay local)'}")

    scan()
    srv = Server(("0.0.0.0", args.port), Handler)
    log(f"library {VERSION} on http://0.0.0.0:{args.port}")
    log(f"root {ROOT}")
    log(f"cache {CACHE}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("stopped")


if __name__ == "__main__":
    main()
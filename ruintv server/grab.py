#!/usr/bin/env python3
"""
grab.py — RUIN.TO acquisition daemon (port 8789)

Resolves a TMDB id to a YTS torrent, verifies it before spending bandwidth, then
verifies the downloaded file again before it is allowed into the library.

    <Title> (Year) [tmdb-<id>].mp4

Client modes, set "client" in grab.json:

  aria2   Fully automatic. aria2 is handed a per-job folder and writes into it.
  fdm     Hands the magnet to Free Download Manager, which creates its own
          per-download subfolder under the staging root.
  drop    Nothing is launched. The API returns the magnet; the watcher files
          whatever lands.

Verification has two stages.

PRE-DOWNLOAD. TMDB is queried with append_to_response=external_ids,
alternative_titles and the result is kept on the job as ground truth. Every YTS
candidate must match the IMDb id (or normalized title + exact year + YTS runtime
if TMDB's IMDb id is not indexed on YTS), stay at or below max_quality (hard
1080p ceiling, never falling back to 2160p), meet min_seeds, avoid dub-only
releases, and clear a per-minute size floor. Unrated / Extended / Uncut /
Director's Cut releases are prioritized when multiple torrents exist.

POST-DOWNLOAD. Four gates, all on the real file:

1. ffprobe duration within [-10 min, +20 min] of TMDB runtime (allows longer
     extended/uncut editions while rejecting shortened or wrong movies)
2. ffprobe width/height consistent with the grabbed quality (including cropped
     widescreen encodes such as 1920x800), and size within ±5% of the torrent
3. audio language — original TMDB language must be preserved (multi-audio
     files containing the original track pass; dub-only replacements reject)
4. identity — FDM subfolder name, filename, or container title matches TMDB
     title, original_title, or any alternative title (year, if present, within ±1)

All gates pass -> filed. Runtime, resolution, or dub-only audio fails -> wrong
release: job failed permanently and the download deleted. Runtime, resolution,
and language pass but identity fails -> likely the right film under an unexpected
release name: moved into staging/_review as needs_review, never renamed, never
closed, and surfaced in /queue for a human decision.

Endpoints:

    GET  /                     queue page
    GET  /health
    GET  /queue                jobs as JSON
    GET  /dry?tmdb=<id>        resolve + gate a film without downloading
    POST /grab?tmdb=<id>       start a job
    POST /cancel?id=<job>      cancel a job
    POST /queue/approve?id=    file a needs_review candidate
    POST /queue/reject?id=     delete a needs_review candidate

    python grab.py --config grab.json
"""

from __future__ import annotations

import argparse
import difflib
import errno
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.5.0"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".ts", ".m2ts"}
QUALITY_RANK = {"2160p": 4, "1080p": 3, "720p": 2, "480p": 1}
YTS_HOSTS = ("movies-api.accel.li", "yts.pw", "yts.gg", "yts.mx", "yts.lt", "yts.bz", "yts.rs", "yts.am")
TRACKERS = (
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:80",
    "udp://tracker.coppersurfer.tk:6969",
    "udp://glotorrents.pw:6969/announce",
    "udp://tracker.leechers-paradise.org:6969",
    "udp://9.rarbg.to:2710/announce",
)
SKIP_TOKENS = ("sample", "trailer", "proof")
IGNORED_DIRS = {".temp", "_review"}
ACTIVE_STATES = {"resolving", "downloading", "handed_off", "moving", "needs_review"}
DISK_RESERVED_STATES = {"resolving", "downloading", "handed_off", "moving"}

# words too common to prove anything on their own
STOP_TOKENS = {
    "the", "and", "of", "a", "an", "in", "on", "to", "for", "with", "aka",
    "yts", "yify", "x264", "x265", "aac", "web", "webrip", "bluray", "brrip",
    "bdrip", "hdtv", "remux", "proper", "repack", "extended", "unrated",
    "uncut", "directors", "director", "cut", "1080p", "720p", "2160p", "480p",
}
# sequelling words that differ freely between TMDB and release names
CONNECTORS = {"chapter", "part", "vol", "volume", "pt", "episode", "pt.", "one", "two", "three"}
UNCUT_MARKERS = ("unrated", "extended", "uncut", "director's cut", "directors cut", "final cut", "ultimate cut", "redux")

# ISO 639-1 (TMDB original_language) -> ISO 639-1 + ISO 639-2/B/T (ffprobe stream tags)
ISO1_TO_ISO2 = {
    "en": {"en", "eng"},
    "ja": {"ja", "jpn"},
    "ko": {"ko", "kor"},
    "es": {"es", "spa"},
    "fr": {"fr", "fre", "fra"},
    "de": {"de", "ger", "deu"},
    "it": {"it", "ita"},
    "pt": {"pt", "por"},
    "ru": {"ru", "rus"},
    "zh": {"zh", "chi", "zho", "cmn", "yue"},
    "cn": {"cn", "zh", "chi", "zho", "yue"},
    "hi": {"hi", "hin"},
    "ar": {"ar", "ara"},
    "tr": {"tr", "tur"},
    "th": {"th", "tha"},
    "vi": {"vi", "vie"},
    "id": {"id", "ind"},
    "pl": {"pl", "pol"},
    "nl": {"nl", "dut", "nld"},
    "sv": {"sv", "swe"},
    "da": {"da", "dan"},
    "no": {"no", "nor", "nob", "nno"},
    "fi": {"fi", "fin"},
    "ta": {"ta", "tam"},
    "te": {"te", "tel"},
    "ml": {"ml", "mal"},
    "fa": {"fa", "per", "fas"},
    "he": {"he", "heb"},
    "el": {"el", "gre", "ell"},
    "cs": {"cs", "cze", "ces"},
    "hu": {"hu", "hun"},
    "ro": {"ro", "rum", "ron"},
    "uk": {"uk", "ukr"},
}
UNSPECIFIED_LANGS = {"", "und", "unk", "mul", "mis", "zxx"}
FOREIGN_TAG_WORDS = {
    "spanish", "french", "german", "italian", "russian", "hindi",
    "arabic", "portuguese", "japanese", "korean", "mandarin", "cantonese",
}

# (min_width, max_width, min_height, max_height) — accepts either dimension so
# cropped widescreen encodes (e.g. 1920x800 for 1080p, 1280x536 for 720p) pass
RES_BANDS = {
    "480p": (600, 900, 340, 560),
    "720p": (1150, 1360, 640, 800),
    "1080p": (1750, 2000, 960, 1120),
    "2160p": (3500, 4100, 1900, 2260),
}

# gross-outlier floor, MB per minute of runtime, so a 150 MB "1080p" of a
# 120-minute film is refused before any bandwidth is spent
MIN_MB_PER_MIN = {"480p": 1.5, "720p": 3.0, "1080p": 5.0, "2160p": 9.0}
MAX_MB_PER_MIN = 60.0

YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
TMDB_TAG_RE = re.compile(r"\[tmdb-(\d+)\]", re.IGNORECASE)

DEFAULTS = {
    "host": "127.0.0.1",
    "bind": "0.0.0.0",
    "port": 8789,
    "tmdb_key": "",
    "yts_hosts": list(YTS_HOSTS),
    "library_root": r"D:\movies\library",
    "staging_root": r"D:\movies\staging",
    "jobs_file": "",
    "watch_roots": [],
    "watch_depth": 3,
    "client": "drop",
    "fdm_path": r"C:\Program Files\Softdeluxe\Free Download Manager\fdm.exe",
    "aria2_rpc": "http://127.0.0.1:6800/jsonrpc",
    "aria2_secret": "",
    "library_scan_url": "http://127.0.0.1:8788/scan",
    "max_quality": "1080p",
    "min_seeds": 3,
    "min_free_gb": 20,
    "auto_scan": True,
    "min_file_mb": 20,
    "auto_delete_rejected": True,
    "verify_runtime_tolerance_min": 10,
    "verify_runtime_long_tolerance_min": 20,
    "verify_size_tolerance_pct": 5,
    "verify_audio_language": True,
    "ffmpeg_dir": "",
    "ffprobe_path": "",
}

STOP = threading.Event()
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
SEEN: dict[str, int] = {}
REVIEWED: dict[str, int] = {}          # path -> size, parked or rejected: do not re-probe
REVIEWED_LOCK = threading.Lock()
PROBE_CACHE: dict[tuple, dict] = {}
CFG: dict = {}
ARIA = None
FFPROBE = ""


# --------------------------------------------------------------------------- #
# plumbing & persistence
# --------------------------------------------------------------------------- #

def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def http_get(url: str, timeout: int = 25, headers: dict | None = None) -> str:
    h = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def http_post(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, data=b"", headers={"User-Agent": UA}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def http_json(url: str, **kw):
    txt = http_get(url, **kw)
    return json.loads(txt) if txt.strip() else {}


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def free_bytes(path: Path) -> int:
    try:
        return shutil.disk_usage(str(path)).free
    except OSError:
        return 0


def reserved_bytes() -> int:
    """Sum of expected sizes for currently active downloads so back-to-back grabs cannot overcommit disk."""
    with JOBS_LOCK:
        return sum(
            int(j.get("size") or 0)
            for j in JOBS.values()
            if j.get("state") in DISK_RESERVED_STATES
        )


def safe_name(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]', "", s)
    s = re.sub(r"\s+", " ", s).strip().rstrip(".")
    return s[:120] or "untitled"


def jobs_state_path() -> Path | None:
    jf = (CFG.get("jobs_file") or "").strip()
    if jf:
        return Path(jf)
    sr = (CFG.get("staging_root") or "").strip()
    if sr:
        return Path(sr) / "jobs.json"
    return None


def save_jobs() -> None:
    p = jobs_state_path()
    if not p:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with JOBS_LOCK:
            items = list(JOBS.values())
        items.sort(key=lambda j: j.get("added", 0), reverse=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(items[:200], indent=2), encoding="utf-8")
        os.replace(str(tmp), str(p))
    except OSError as e:
        log(f"save_jobs failed: {e}")


def load_jobs() -> None:
    p = jobs_state_path()
    if not p or not p.is_file():
        return
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig") or "[]")
        if not isinstance(raw, list):
            return
        restored = 0
        with JOBS_LOCK:
            for item in raw:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                if item.get("state") == "moving":
                    item["state"] = "handed_off"
                elif item.get("state") == "resolving":
                    item["state"] = "failed"
                    item["error"] = "interrupted during resolve"
                JOBS[item["id"]] = item
                if item.get("state") == "needs_review" and item.get("candidate_path"):
                    with REVIEWED_LOCK:
                        REVIEWED[item["candidate_path"]] = int(item.get("candidate_seconds") or 0)
                restored += 1
        if restored:
            log(f"restored {restored} job(s) from {p.name}")
    except Exception as e:
        log(f"load_jobs failed: {e}")


def find_existing_in_library(tmdb_id: int) -> Path | None:
    lib = Path(CFG["library_root"])
    if not lib.is_dir():
        return None
    target = int(tmdb_id)
    for dirpath, _dirs, files in os.walk(lib):
        for f in files:
            p = Path(dirpath) / f
            if p.suffix.lower() not in VIDEO_EXT:
                continue
            m = TMDB_TAG_RE.search(p.name)
            if m and int(m.group(1)) == target:
                return p
    return None


def find_active_job(tmdb_id: int) -> dict | None:
    target = int(tmdb_id)
    with JOBS_LOCK:
        for j in JOBS.values():
            if int(j.get("tmdb") or 0) == target and j.get("state") in ACTIVE_STATES:
                return dict(j)
    return None


def staging_temp_active() -> bool:
    """True when FDM still has partial downloads inside staging/.temp."""
    temp_dir = Path(CFG["staging_root"]) / ".temp"
    if not temp_dir.is_dir():
        return False
    try:
        for _dirpath, _dirs, files in os.walk(temp_dir):
            if files:
                return True
    except OSError:
        return False
    return False


def is_transient_lock(exc: BaseException) -> bool:
    winerr = getattr(exc, "winerror", None)
    err = getattr(exc, "errno", None)
    if winerr in (32, 33):  # ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION
        return True
    if err in (errno.EACCES, errno.EBUSY, errno.ETXTBSY):
        return True
    msg = str(exc).lower()
    return "being used by another process" in msg or "sharing violation" in msg


def find_ffprobe() -> str:
    candidates = [
        CFG.get("ffprobe_path", ""),
        os.environ.get("FFPROBE_BIN", ""),
    ]
    fdir = CFG.get("ffmpeg_dir", "")
    if fdir:
        candidates.append(os.path.join(fdir, "ffprobe.exe" if os.name == "nt" else "ffprobe"))
    candidates.append("ffprobe")
    for c in candidates:
        if not c:
            continue
        if os.path.isabs(c):
            if os.path.isfile(c):
                return c
        else:
            hit = shutil.which(c)
            if hit:
                return hit
    return ""


# --------------------------------------------------------------------------- #
# normalisation, identity, and language
# --------------------------------------------------------------------------- #

def norm(text: str) -> str:
    """Fold to a comparable form: lowercase, accents off, & -> and, punctuation gone."""
    s = (text or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[\[\](){}_.,:;'\"!?/\\|–—-]", " ", s)
    try:
        import unicodedata
        s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    except Exception:
        pass
    return re.sub(r"\s+", " ", s).strip()


def match_tokens(text: str) -> set[str]:
    """Words that can prove identity. Keeps short numerals, drops stops and connectors."""
    raw = [w for w in norm(text).split() if len(w) >= 2]
    out = {w for w in raw if w not in STOP_TOKENS and w not in CONNECTORS}
    return out or {w for w in raw if w not in STOP_TOKENS}


def title_keys(job: dict) -> list[str]:
    keys = [job.get("title", ""), job.get("original_title", "")]
    keys.extend(job.get("alternative_titles", []) or [])
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        nk = norm(k)
        if nk and len(nk) >= 2 and nk not in seen:
            seen.add(nk)
            out.append(nk)
    return out


def title_matches_meta(candidate_title: str, meta: dict) -> bool:
    """Normalized exact or connector-stripped token match against TMDB titles."""
    cand_norm = norm(candidate_title)
    if not cand_norm:
        return False
    cand_tokens = match_tokens(candidate_title)
    for t in [meta.get("title", ""), meta.get("original_title", ""), *(meta.get("alternatives") or [])]:
        nt = norm(t)
        if not nt:
            continue
        if cand_norm == nt:
            return True
        wt = match_tokens(t)
        if wt and cand_tokens and wt == cand_tokens:
            return True
    return False


def name_year(text: str) -> str:
    m = YEAR_RE.search(text or "")
    return m.group(0) if m else ""


def identity_match(names: list[str], job: dict) -> str:
    """Return which source proved identity, or "" if none did."""
    keys = title_keys(job)
    if not keys:
        return ""
    job_year = str(job.get("year") or "")
    primary_keys = [norm(job.get("title", "")), norm(job.get("original_title", ""))]
    primary_keys = [k for k in primary_keys if k]
    want_primary: set[str] = set()
    for k in primary_keys:
        want_primary |= match_tokens(k)

    for label, raw in zip(("folder", "filename", "container-title"), names):
        if not raw:
            continue
        n = norm(raw)
        if not n:
            continue
        cy = name_year(raw)
        if cy and job_year and abs(int(cy) - int(job_year)) > 1:
            continue
        for k in keys:
            if len(k) >= 3 and re.search(rf"(?:^|\s){re.escape(k)}(?:\s|$)", n):
                return label
        have = match_tokens(raw)
        if want_primary and want_primary <= have:
            return label
        for k in keys:
            want_k = match_tokens(k)
            if want_k and want_k <= have:
                return label
        for k in primary_keys:
            if len(k) >= 5 and difflib.SequenceMatcher(None, k, n).ratio() >= 0.82:
                return label
    return ""


def expected_lang_codes(orig_lang: str) -> set[str]:
    code = (orig_lang or "").strip().lower()
    if not code:
        return set()
    return ISO1_TO_ISO2.get(code, {code})


def has_dub_marker(names: list[str], job: dict) -> bool:
    """True when release naming indicates a dub-only replacement (allows dual/multi audio)."""
    orig = (job.get("original_language") or "").strip().lower()
    title_words = set()
    for k in title_keys(job):
        title_words.update(k.split())

    joined = norm(" ".join(n for n in names if n))
    words = set(joined.split())
    # Multi-audio / dual-audio releases keep the original track intact for Phases 2-3
    if "dual" in words or "multi" in words:
        return False
    if ("dub" in words or "dubbed" in words) and "dub" not in title_words and "dubbed" not in title_words:
        return True
    if orig == "en":
        for fw in FOREIGN_TAG_WORDS:
            if fw in words and fw not in title_words:
                return True
    return False


def audio_language_ok(audio_langs: list[str], job: dict, names: list[str]) -> bool | None:
    """Verify original audio language is preserved without rejecting multi-audio or untagged YTS files."""
    if not CFG.get("verify_audio_language", True):
        return None
    orig = (job.get("original_language") or "").strip().lower()
    if not orig:
        return None

    explicit = [
        (lang or "").strip().lower()
        for lang in (audio_langs or [])
        if (lang or "").strip().lower() not in UNSPECIFIED_LANGS
    ]
    allowed = expected_lang_codes(orig)
    if explicit:
        return any(lang in allowed for lang in explicit)
    if has_dub_marker(names, job):
        return False
    return None


def uncut_bonus(cand: dict) -> int:
    text = f"{cand.get('title', '')} {cand.get('torrent_name', '')}".lower()
    return 1 if any(m in text for m in UNCUT_MARKERS) else 0


# --------------------------------------------------------------------------- #
# ffprobe
# --------------------------------------------------------------------------- #

def ffprobe_media(path: Path) -> dict:
    """Duration, width, height, audio languages, and container title, cached per path+mtime+size."""
    try:
        st = path.stat()
    except OSError:
        return {"ok": False, "error": "stat failed", "seconds": 0, "width": 0, "height": 0, "title": "", "audio_langs": []}
    key = (str(path), int(st.st_mtime), int(st.st_size))
    cached = PROBE_CACHE.get(key)
    if cached:
        return cached
    result = {"ok": False, "error": "", "seconds": 0, "width": 0, "height": 0, "title": "", "audio_langs": []}
    if not FFPROBE:
        result["error"] = "ffprobe not found"
        PROBE_CACHE[key] = result
        return result
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, timeout=40,
        )
        info = json.loads(out.stdout.decode("utf-8", "replace") or "{}")
    except Exception as e:
        result["error"] = f"probe: {e}"
        PROBE_CACHE[key] = result
        return result
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        result["error"] = "no video stream"
        PROBE_CACHE[key] = result
        return result
    audio_langs = []
    for s in streams:
        if s.get("codec_type") == "audio":
            lang = str((s.get("tags") or {}).get("language") or "").strip().lower()
            if lang and lang not in audio_langs:
                audio_langs.append(lang)
    fmt = info.get("format") or {}
    tags = fmt.get("tags") or {}
    vtags = video.get("tags") or {}
    result["ok"] = True
    try:
        result["seconds"] = int(float(fmt.get("duration") or 0))
    except (TypeError, ValueError):
        result["seconds"] = 0
    try:
        result["width"] = int(video.get("width") or 0)
    except (TypeError, ValueError):
        result["width"] = 0
    try:
        result["height"] = int(video.get("height") or 0)
    except (TypeError, ValueError):
        result["height"] = 0
    result["title"] = str(tags.get("title") or vtags.get("title") or "")
    result["audio_langs"] = audio_langs
    if len(PROBE_CACHE) > 4000:
        PROBE_CACHE.clear()
    PROBE_CACHE[key] = result
    return result


# --------------------------------------------------------------------------- #
# aria2 client
# --------------------------------------------------------------------------- #

class Aria2:
    def __init__(self, cfg: dict):
        self.rpc = cfg["aria2_rpc"]
        self.secret = cfg["aria2_secret"]

    def _rpc(self, method: str, params: list):
        p = ([f"token:{self.secret}"] if self.secret else []) + params
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": p}
        ).encode()
        req = urllib.request.Request(
            self.rpc, data=payload,
            headers={"User-Agent": UA, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=25) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
        if "error" in body:
            raise RuntimeError(body["error"].get("message", "aria2 error"))
        return body.get("result")

    def add(self, url: str, savepath: Path) -> str:
        gid = self._rpc("aria2.addUri", [[url], {"dir": str(savepath)}])
        if not gid:
            raise RuntimeError("aria2 returned no gid")
        return gid

    def status(self, gid: str) -> dict | None:
        try:
            return self._rpc("aria2.tellStatus", [gid])
        except Exception:
            return None

    def delete(self, gid: str) -> None:
        for m in ("aria2.forceRemove", "aria2.remove"):
            try:
                self._rpc(m, [gid])
                return
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# TMDB ground truth
# --------------------------------------------------------------------------- #

def tmdb_meta(tmdb_id: int) -> dict:
    key = (CFG.get("tmdb_key") or "").strip()
    if not key:
        raise RuntimeError("tmdb_key not configured in grab.json")
    url = (
        f"https://api.themoviedb.org/3/movie/{int(tmdb_id)}"
        f"?api_key={key}&append_to_response=external_ids,alternative_titles"
    )
    data = http_json(url) or {}
    ext = data.get("external_ids") or {}
    alts = ((data.get("alternative_titles") or {}).get("titles")) or []
    runtime = data.get("runtime") or 0
    try:
        runtime = int(runtime)
    except (TypeError, ValueError):
        runtime = 0
    return {
        "tmdb": int(tmdb_id),
        "imdb": (ext.get("imdb_id") or "").strip(),
        "title": (data.get("title") or "").strip(),
        "original_title": (data.get("original_title") or "").strip(),
        "original_language": (data.get("original_language") or "").strip().lower(),
        "alternatives": [str(t.get("title") or "").strip() for t in alts if t.get("title")],
        "year": (data.get("release_date") or "")[:4],
        "runtime": runtime,
        "poster": data.get("poster_path") or "",
    }


# --------------------------------------------------------------------------- #
# YTS resolution + pre-download gate
# --------------------------------------------------------------------------- #

def yts_hosts() -> list[str]:
    configured = CFG.get("yts_hosts") or list(YTS_HOSTS)
    return list(dict.fromkeys([str(h).strip() for h in configured if str(h).strip()]))


def yts_query(term: str) -> list[dict]:
    for host in yts_hosts():
        try:
            url = f"https://{host}/api/v2/list_movies.json?query_term={urllib.parse.quote(term)}&limit=10"
            data = http_json(url, headers={"Referer": f"https://{host}/"})
        except Exception as e:
            log(f"yts {host}: {e}")
            continue
        movies = ((data or {}).get("data") or {}).get("movies") or []
        if movies:
            return movies
    return []


def yts_candidates(meta: dict) -> list[dict]:
    """Torrents gated by IMDb lock, or normalized title + exact year + YTS runtime if IMDb is absent on YTS."""
    imdb = meta.get("imdb") or ""
    want_year = meta.get("year") or ""
    want_runtime = int(meta.get("runtime") or 0)
    short_tol = int(CFG.get("verify_runtime_tolerance_min") or 10)
    long_tol = int(CFG.get("verify_runtime_long_tolerance_min") or 20)

    imdb_movies = yts_query(imdb) if imdb else []
    if imdb_movies:
        movies = [m for m in imdb_movies if (m.get("imdb_code") or "").strip() == imdb]
        allow_title_fallback = False
    else:
        movies = yts_query(meta.get("title") or "")
        allow_title_fallback = True

    out: list[dict] = []
    for m in movies:
        code = (m.get("imdb_code") or "").strip()
        m_title = m.get("title") or ""
        m_year = str(m.get("year") or "")
        try:
            m_runtime = int(m.get("runtime") or 0)
        except (TypeError, ValueError):
            m_runtime = 0

        if not allow_title_fallback:
            if code != imdb:
                continue
            if want_year and m_year and abs(int(m_year) - int(want_year)) > 1:
                continue
        else:
            if not title_matches_meta(m_title, meta):
                continue
            if want_year and m_year != want_year:
                continue
            if want_runtime > 0 and m_runtime > 0:
                diff = m_runtime - want_runtime
                if diff < -short_tol or diff > long_tol:
                    continue

        if has_dub_marker([m.get("title_long") or "", m_title], meta):
            continue

        for t in m.get("torrents") or []:
            h = (t.get("hash") or "").lower()
            if not h:
                continue
            dn = f"{m.get('title_long') or m_title or 'movie'} [{t.get('quality')}] [YTS]"
            magnet = "magnet:?xt=urn:btih:" + h + "&dn=" + urllib.parse.quote(dn)
            for tr in TRACKERS:
                magnet += "&tr=" + urllib.parse.quote(tr)
            out.append({
                "quality": t.get("quality") or "?",
                "size": int(t.get("size_bytes") or 0),
                "seeds": int(t.get("seeds") or 0),
                "peers": int(t.get("peers") or 0),
                "hash": h,
                "url": t.get("url") or "",
                "magnet": magnet,
                "title": m.get("title_long") or m_title or "",
                "year": m.get("year"),
                "imdb": code,
                "torrent_name": dn,
            })
    return out


def size_sane(size: int, quality: str, runtime: int) -> tuple[bool, str]:
    """Refuse a torrent whose size cannot plausibly be that film at that quality."""
    if not size or not runtime:
        return True, ""
    minutes = max(1, runtime)
    mb_per_min = (size / 1048576.0) / minutes
    floor = MIN_MB_PER_MIN.get(quality, 1.5)
    if mb_per_min < floor:
        return False, f"{human(size)} for {runtime} min at {quality} is {mb_per_min:.1f} MB/min, floor {floor}"
    if mb_per_min > MAX_MB_PER_MIN:
        return False, f"{mb_per_min:.0f} MB/min is implausible at {quality}"
    return True, ""


def rank(cands: list[dict]) -> tuple[list[dict], str]:
    """Hard quality ceiling + hard min_seeds floor + uncut/extended cut priority."""
    allow = QUALITY_RANK.get(CFG["max_quality"], 3)
    min_seeds = int(CFG["min_seeds"])
    capped = [c for c in cands if 0 < QUALITY_RANK.get(c["quality"], 0) <= allow]
    if not capped:
        return [], f"no candidate at or below {CFG['max_quality']}"
    seeded = [c for c in capped if c["seeds"] >= min_seeds]
    if not seeded:
        return [], f"no candidate meets min_seeds ({min_seeds})"
    seeded.sort(
        key=lambda c: (
            QUALITY_RANK.get(c["quality"], 0),
            uncut_bonus(c),
            c["seeds"],
            c["size"],
        ),
        reverse=True,
    )
    return seeded, ""


def resolve(tmdb_id: int) -> tuple[dict, list[dict], str]:
    """Ground truth + gated candidates + rejection reason ("" when usable)."""
    meta = tmdb_meta(tmdb_id)
    if not meta["title"]:
        return meta, [], "tmdb returned no title"
    cands = yts_candidates(meta)
    if not cands:
        return meta, [], "no yts torrent for this imdb id or title"
    ranked, rank_err = rank(cands)
    if not ranked:
        return meta, [], rank_err
    kept: list[dict] = []
    reasons: list[str] = []
    for c in ranked:
        ok, why = size_sane(c["size"], c["quality"], meta["runtime"])
        if ok:
            kept.append(c)
        else:
            reasons.append(f"{c['quality']} {why}")
    if kept:
        return meta, kept, ""
    return meta, [], "every candidate failed the size sanity check: " + "; ".join(reasons[:3])


# --------------------------------------------------------------------------- #
# jobs
# --------------------------------------------------------------------------- #

def new_job(tmdb_id: int) -> dict:
    return {
        "id": uuid.uuid4().hex[:12],
        "tmdb": tmdb_id,
        "tmdb_id": tmdb_id,
        "imdb_id": "",
        "title": "",
        "original_title": "",
        "original_language": "",
        "alternative_titles": [],
        "year": "",
        "runtime": 0,
        "poster_path": "",
        "yts_title": "",
        "quality": "",
        "size": 0,
        "hash": "",
        "gid": "",
        "state": "resolving",
        "progress": 0.0,
        "speed": 0,
        "eta": 0,
        "path": "",
        "dir": "",
        "magnet_file": "",
        "magnet": "",
        "error": "",
        "permanent": False,
        "candidate_path": "",
        "candidate_seconds": 0,
        "candidate_width": 0,
        "candidate_height": 0,
        "candidate_audio_langs": [],
        "identity_source": "",
        "added": time.time(),
    }


def job_dir(job: dict) -> Path:
    """The job's own folder under staging."""
    return Path(CFG["staging_root"]) / (job.get("dir") or job["id"])


def public(j: dict) -> dict:
    d = dict(j)
    d["size_h"] = human(j["size"]) if j["size"] else ""
    d["speed_h"] = human(j["speed"]) + "/s" if j["speed"] else ""
    d["progress_pct"] = round(j["progress"] * 100, 1)
    d["runtime_h"] = f"{j['runtime']} min" if j.get("runtime") else ""
    d["poster_url"] = (
        "https://image.tmdb.org/t/p/w342" + j["poster_path"] if j.get("poster_path") else ""
    )
    d["staging"] = str(job_dir(j)) if j.get("dir") else CFG["staging_root"]
    return d


def snapshot() -> list[dict]:
    with JOBS_LOCK:
        items = [public(j) for j in JOBS.values()]
    items.sort(key=lambda j: j["added"], reverse=True)
    return items


def find_video(root: Path) -> Path | None:
    if root.is_file():
        return root if root.suffix.lower() in VIDEO_EXT else None
    if not root.exists():
        return None
    best = None
    best_size = -1
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = Path(dirpath) / f
            if p.suffix.lower() not in VIDEO_EXT:
                continue
            try:
                s = p.stat().st_size
            except OSError:
                continue
            if s > best_size:
                best, best_size = p, s
    return best


def file_into_library(video: Path, tmdb: int | None, title: str, year: str) -> Path:
    lib = Path(CFG["library_root"])
    lib.mkdir(parents=True, exist_ok=True)
    clean = safe_name(title or video.stem)
    clean = re.sub(r"\s*\((19|20)\d{2}\)\s*$", "", clean).strip() or safe_name(video.stem)
    if tmdb:
        stem = f"{clean} ({year}) [tmdb-{tmdb}]" if year else f"{clean} [tmdb-{tmdb}]"
    else:
        stem = f"{clean} ({year})" if year else clean
    dest = lib / (stem + video.suffix.lower())
    n = 2
    while dest.exists():
        dest = lib / f"{stem} ({n}){video.suffix.lower()}"
        n += 1
    shutil.move(str(video), str(dest))
    return dest


def poke_scan() -> None:
    if not CFG["auto_scan"]:
        return
    try:
        http_post(CFG["library_scan_url"], timeout=90)
    except Exception as e:
        log(f"scan poke failed (is library.py running?): {e}")


def finalize(job: dict, video: Path) -> bool:
    """Move verified video into library. Returns False if transiently locked so watcher retries."""
    try:
        dest = file_into_library(video, job["tmdb"], job["title"], job["year"])
    except OSError as e:
        if is_transient_lock(e):
            job["state"] = "handed_off"
            log(f"file locked by client ({video.name}), will retry next scan")
            return False
        job["state"] = "failed"
        job["error"] = f"move: {e}"
        save_jobs()
        return False
    except Exception as e:
        job["state"] = "failed"
        job["error"] = f"move: {e}"
        save_jobs()
        return False
    job["path"] = str(dest)
    job["progress"] = 1.0
    job["state"] = "done"
    save_jobs()
    try:
        log(f"filed {dest.name} ({human(dest.stat().st_size)})")
    except OSError:
        log(f"filed {dest.name}")
    poke_scan()
    return True


def cleanup_staging(job: dict) -> None:
    mf = job.get("magnet_file")
    if mf:
        try:
            Path(mf).unlink()
        except OSError:
            pass
    d = job.get("dir")
    if not d:
        return
    folder = Path(CFG["staging_root"]) / d
    if not folder.exists():
        return
    if find_video(folder):
        return
    shutil.rmtree(folder, ignore_errors=True)


def clear_source_folder(video: Path) -> None:
    parent = video.parent
    try:
        staging = Path(CFG["staging_root"]).resolve()
        review_root = (staging / "_review").resolve()
        par = parent.resolve()
    except OSError:
        return
    if par in (staging, review_root):
        return
    try:
        inside_staging = staging in par.parents
    except OSError:
        inside_staging = False
    if inside_staging and find_video(par) is None:
        shutil.rmtree(parent, ignore_errors=True)
        log(f"removed staging folder {parent.name}")
        return
    try:
        if par in {Path(r).resolve() for r in watch_roots()}:
            return
    except OSError:
        return
    try:
        if any(parent.iterdir()):
            return
        parent.rmdir()
        log(f"removed empty folder {parent.name}")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# verification
# --------------------------------------------------------------------------- #

def runtime_ok(seconds: int, runtime_min: int) -> bool | None:
    """Asymmetric runtime window: [-short_tol, +long_tol] so uncut editions pass."""
    if not seconds or not runtime_min:
        return None
    short_tol = int(CFG.get("verify_runtime_tolerance_min") or 10) * 60
    long_tol = int(CFG.get("verify_runtime_long_tolerance_min") or 20) * 60
    diff = seconds - (runtime_min * 60)
    return (-short_tol) <= diff <= long_tol


def resolution_ok(width: int, height: int, quality: str) -> bool | None:
    if quality not in RES_BANDS:
        return None
    if not width and not height:
        return None
    w_lo, w_hi, h_lo, h_hi = RES_BANDS[quality]
    w_match = (w_lo <= width <= w_hi) if width else False
    h_match = (h_lo <= height <= h_hi) if height else False
    return w_match or h_match


def size_ok(size: int, expected: int) -> bool | None:
    if not size or not expected:
        return None
    pct = float(CFG["verify_size_tolerance_pct"]) / 100.0
    return abs(size - expected) <= expected * pct


def evaluate(video: Path, folder: str, size: int):
    """Decide what this file is. Returns (job, verdict, info, ident) or None.

    verdict: "file" (all gates pass), "review" (right film, unrecognised name, or
    undecidable), "reject" (wrong film or dub-only audio replacement).
    """
    with JOBS_LOCK:
        pending = [j for j in JOBS.values() if j["state"] == "handed_off"]
    if not pending:
        return None

    free = [j for j in pending if not find_video(job_dir(j))]
    if not free:
        return None

    # Ignore standalone bonus clips (<50% expected torrent size) while FDM still has active .temp files
    temp_busy = staging_temp_active()
    eligible = []
    for j in free:
        exp = int(j.get("size") or 0)
        if temp_busy and exp > 0 and size < int(exp * 0.50):
            continue
        eligible.append(j)
    if not eligible:
        return None

    info = ffprobe_media(video)
    names = [folder, video.stem, info.get("title", "")]

    best = None            # (score, job, verdict, info, ident)
    for job in eligible:
        ident = identity_match(names, job)
        r_ok = runtime_ok(info["seconds"], int(job.get("runtime") or 0))
        res_ok = resolution_ok(info["width"], info["height"], job.get("quality") or "")
        s_ok = size_ok(size, int(job.get("size") or 0))
        lang_ok = audio_language_ok(info.get("audio_langs") or [], job, names)

        if not info["ok"] or r_ok is None:
            verdict = "review"
        elif r_ok is False:
            verdict = "reject"
        elif res_ok is False:
            verdict = "reject"
        elif lang_ok is False:
            verdict = "reject"
        elif ident and (s_ok is not False):
            verdict = "file"
        else:
            verdict = "review"

        score = {"file": 3, "review": 2, "reject": 1}[verdict]
        if ident:
            score += 0.5
        if best is None or score > best[0]:
            best = (score, job, verdict, info, ident)

    if best is None:
        return None
    return best[1], best[2], best[3], best[4]


def mark_reviewed(path: Path, size: int) -> None:
    with REVIEWED_LOCK:
        REVIEWED[str(path)] = size


def isolate_to_review(video: Path) -> Path:
    """Move a parked video into staging/_review so restarts never re-scan or delete it."""
    try:
        staging = Path(CFG["staging_root"]).resolve()
        src = video.resolve()
        review_root = staging / "_review"
        review_root.mkdir(parents=True, exist_ok=True)
        if src.parent != staging and staging in src.parents:
            dest_dir = review_root / src.parent.name
        else:
            dest_dir = review_root
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        n = 2
        while dest.exists():
            dest = dest_dir / f"{src.stem} ({n}){src.suffix}"
            n += 1
        old_parent = src.parent
        shutil.move(str(src), str(dest))
        if old_parent != staging and staging in old_parent.parents and find_video(old_parent) is None:
            shutil.rmtree(old_parent, ignore_errors=True)
        return dest
    except OSError as e:
        log(f"could not move {video.name} to _review: {e}")
        return video


def park(job: dict, video: Path, info: dict, ident: str) -> None:
    parked = isolate_to_review(video)
    job["state"] = "needs_review"
    job["candidate_path"] = str(parked)
    job["candidate_seconds"] = info["seconds"]
    job["candidate_width"] = info["width"]
    job["candidate_height"] = info["height"]
    job["candidate_audio_langs"] = info.get("audio_langs") or []
    job["identity_source"] = ident
    job["error"] = "identity not confirmed"
    mark_reviewed(parked, info.get("seconds", 0))
    save_jobs()
    log(f"needs review: {parked.name} (moved to _review)")


def delete_candidate(path: Path) -> None:
    """Remove a rejected file, and its staging folder when no other video remains."""
    try:
        target = path.resolve()
    except OSError:
        return
    try:
        staging = Path(CFG["staging_root"]).resolve()
        review_root = (staging / "_review").resolve()
        lib = Path(CFG["library_root"]).resolve()
    except OSError:
        return
    if lib in target.parents or target.parent == lib:
        return
    parent = target.parent
    try:
        target.unlink()
        log(f"deleted rejected {target.name}")
    except OSError as e:
        log(f"could not delete {target.name}: {e}")
        return
    if parent in (staging, review_root):
        return
    try:
        if staging in parent.parents and find_video(parent) is None:
            shutil.rmtree(parent, ignore_errors=True)
            log(f"removed rejected folder {parent.name}")
    except OSError:
        pass


def reject_job(job: dict, video: Path, info: dict, reason: str) -> None:
    job["state"] = "failed"
    job["permanent"] = True
    job["error"] = reason
    mark_reviewed(video, info.get("seconds", 0))
    save_jobs()
    log(f"rejected {video.name}: {reason}")
    if CFG["auto_delete_rejected"]:
        delete_candidate(video)


def handle_file(p: Path, folder: str, min_size: int) -> None:
    if p.suffix.lower() not in VIDEO_EXT:
        return
    if any(tok in p.name.lower() for tok in SKIP_TOKENS):
        return
    with REVIEWED_LOCK:
        if str(p) in REVIEWED:
            return
    try:
        size = p.stat().st_size
    except OSError:
        return
    if size < min_size:
        return
    if SEEN.get(str(p)) != size:
        SEEN[str(p)] = size
        return

    decision = evaluate(p, folder, size)
    if decision is None:
        return
    job, verdict, info, ident = decision

    if verdict == "file":
        job["state"] = "moving"
        if finalize(job, p):
            SEEN.pop(str(p), None)
            clear_source_folder(p)
            cleanup_staging(job)
        return

    if verdict == "review":
        park(job, p, info, ident)
        SEEN.pop(str(p), None)
        return

    names = [folder, p.stem, info.get("title", "")]
    parts = []
    if runtime_ok(info["seconds"], int(job.get("runtime") or 0)) is False:
        parts.append(f"runtime {info['seconds']}s vs {job.get('runtime')} min")
    if resolution_ok(info["width"], info["height"], job.get("quality") or "") is False:
        parts.append(f"{info['width']}x{info['height']} vs {job.get('quality')}")
    if audio_language_ok(info.get("audio_langs") or [], job, names) is False:
        langs = ",".join(info.get("audio_langs") or []) or "dubbed-tag"
        parts.append(f"audio language {langs} vs {job.get('original_language')}")
    reject_job(job, p, info, "; ".join(parts) or "failed verification")
    SEEN.pop(str(p), None)


# --------------------------------------------------------------------------- #
# aria2 poller
# --------------------------------------------------------------------------- #

def aria_tick() -> None:
    changed = False
    with JOBS_LOCK:
        active = [j for j in JOBS.values() if j["state"] == "downloading"]
    for job in active:
        st = ARIA.status(job["gid"])
        if not st:
            continue
        files = st.get("files") or []
        total = sum(int(f.get("length") or 0) for f in files)
        done = sum(int(f.get("completedLength") or 0) for f in files)
        job["progress"] = (done / total) if total else 0.0
        job["speed"] = int(st.get("downloadSpeed") or 0)
        eta = st.get("eta")
        job["eta"] = int(eta) if str(eta).isdigit() else 0
        if st.get("status") == "complete":
            job["state"] = "handed_off"
            ARIA.delete(job["gid"])
            changed = True
        elif st.get("status") == "error":
            job["state"] = "failed"
            job["permanent"] = True
            job["error"] = st.get("errorMessage") or "aria2 error"
            changed = True
    if changed:
        save_jobs()


def aria_loop() -> None:
    while not STOP.is_set():
        try:
            aria_tick()
        except Exception as e:
            log(f"aria: {e}")
        STOP.wait(5)


# --------------------------------------------------------------------------- #
# watcher
# --------------------------------------------------------------------------- #

def watch_roots() -> list[str]:
    roots = [CFG["staging_root"], *CFG.get("watch_roots", [])]
    return list(dict.fromkeys(r for r in roots if r))


def scan_roots(min_size: int) -> None:
    lib = Path(CFG["library_root"]).resolve()
    max_depth = int(CFG.get("watch_depth") or 3)
    for root in watch_roots():
        base = Path(root)
        if not base.is_dir():
            continue
        try:
            base_parts = len(base.resolve().parts)
        except OSError:
            continue
        for dirpath, dirs, files in os.walk(base):
            here = Path(dirpath)
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            try:
                if here.resolve() == lib:
                    dirs[:] = []
                    continue
                depth = len(here.resolve().parts) - base_parts
            except OSError:
                depth = 0
            if depth >= max_depth:
                dirs[:] = []
            for f in files:
                handle_file(here / f, here.name, min_size)


def watcher_loop() -> None:
    min_size = int(CFG["min_file_mb"]) * 1024 * 1024
    while not STOP.is_set():
        try:
            scan_roots(min_size)
            if len(SEEN) > 4000:
                SEEN.clear()
        except Exception as e:
            log(f"watch: {e}")
        STOP.wait(6)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

PAGE = """<!doctype html><meta charset=utf-8><title>RUIN grab</title>
<style>
body{background:#0b0b0d;color:#ddd;font:14px system-ui;margin:0;padding:24px}
h1{font-size:16px;letter-spacing:.12em;text-transform:uppercase;color:#888;margin:0 0 6px}
.n{color:#666;font-size:12px;margin-bottom:18px}
table{width:100%;border-collapse:collapse}
td{padding:9px 8px;border-bottom:1px solid #1b1b20;vertical-align:top}
.t{color:#fff;font-weight:600}
.s{color:#777;font-size:12px}
.mono{font:11px ui-monospace;color:#8a7d55;word-break:break-all}
.bar{height:5px;background:#1b1b20;border-radius:3px;overflow:hidden;margin-top:6px}
.bar>i{display:block;height:100%;background:#c8a24a}
.done{color:#6cc07a}.fail{color:#d66}.moving,.handed_off{color:#c8a24a}
.review{color:#c8a24a;font-weight:600}
.poster{width:46px;border-radius:3px;display:block}
button{background:#1b1b20;color:#bbb;border:1px solid #2b2b32;border-radius:4px;padding:4px 9px;cursor:pointer;font-size:12px;margin-bottom:4px}
button:hover{color:#fff;border-color:#444}
.ok{color:#6cc07a}
</style><h1>RUIN grab</h1><div class=n>mode: __MODE__</div><table id=rows></table>
<script>
async function act(path,id){await fetch(path+'?id='+id,{method:'POST'});tick();}
async function tick(){
  const r = await fetch('/queue'); const rows = await r.json();
  document.getElementById('rows').innerHTML = rows.map(j=>{
    const cls = j.state==='done'?'done':j.state==='failed'?'fail':j.state==='needs_review'?'review':'';
    return `<tr><td>${j.poster_url?`<img class=poster src="${j.poster_url}">`:''}</td><td>
    <div class="t">${j.title||'…'} ${j.year?('('+j.year+')'):''}</div>
    <div class="s">tmdb ${j.tmdb} · ${j.quality} · ${j.size_h} · ${j.runtime_h}</div>
    <div class="s ${cls}">${j.state}${j.speed_h?(' · '+j.speed_h):''}${j.error?(' · '+j.error):''}</div>
    ${j.state==='downloading'?`<div class="bar"><i style="width:${j.progress_pct}%"></i></div>`:''}
    ${j.state==='needs_review'?`<div class="mono">${j.candidate_path} · ${j.candidate_seconds}s · ${j.candidate_width}x${j.candidate_height}</div>
      <div><button class=ok onclick="act('/queue/approve','${j.id}')">approve</button>
      <button onclick="act('/queue/reject','${j.id}')">reject</button></div>`:''}
    ${j.magnet?`<div class="mono" title="${j.magnet}">${j.magnet.slice(0,90)}…</div>`:''}
    </td><td style="width:1%"><button onclick="act('/cancel','${j.id}')">x</button></td></tr>`;
  }).join('') || '<tr><td class="s">idle</td></tr>';
}
setInterval(tick, 2500); tick();
</script>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 120

    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj).encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)

        if u.path == "/":
            return self._send(200, PAGE.replace("__MODE__", CFG["client"]).encode(),
                              "text/html; charset=utf-8")
        if u.path == "/health":
            return self._json({"ok": True, "version": VERSION, "mode": CFG["client"],
                               "max_quality": CFG["max_quality"], "min_seeds": CFG["min_seeds"],
                               "ffprobe": bool(FFPROBE), "tmdb_key": bool(CFG.get("tmdb_key"))})
        if u.path == "/queue":
            return self._json(snapshot())
        if u.path == "/dry":
            try:
                tmdb = int((q.get("tmdb") or [""])[0])
            except ValueError:
                return self._json({"error": "tmdb required"}, 400)
            try:
                meta, cands, why = resolve(tmdb)
            except Exception as e:
                return self._json({"error": str(e)}, 502)
            avail = max(0, free_bytes(Path(CFG["staging_root"])) - reserved_bytes())
            return self._json({
                "tmdb": tmdb,
                "imdb": meta["imdb"],
                "title": meta["title"],
                "original_language": meta["original_language"],
                "runtime": meta["runtime"],
                "rejected": why,
                "free": human(avail),
                "candidates": [
                    {k: c[k] for k in ("quality", "size", "seeds", "peers", "title", "year")}
                    | {"size_h": human(c["size"]), "uncut": bool(uncut_bonus(c))}
                    for c in cands
                ],
            })
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            if length:
                self.rfile.read(min(length, 1 << 20))
        except (ValueError, OSError):
            pass

        if u.path == "/cancel":
            jid = (q.get("id") or [""])[0]
            with JOBS_LOCK:
                job = JOBS.get(jid)
            if not job:
                return self._json({"error": "no such job"}, 404)
            if job["gid"] and ARIA:
                ARIA.delete(job["gid"])
            job["state"] = "cancelled"
            save_jobs()
            return self._json({"ok": True})

        if u.path == "/queue/approve":
            return self._review_action(q, approve=True)

        if u.path == "/queue/reject":
            return self._review_action(q, approve=False)

        if u.path != "/grab":
            return self._json({"error": "not found"}, 404)
        return self._grab(q)

    def _review_action(self, q, approve: bool):
        jid = (q.get("id") or [""])[0]
        with JOBS_LOCK:
            job = JOBS.get(jid)
        if not job or job["state"] != "needs_review":
            return self._json({"error": "no parked job"}, 404)
        video = Path(job.get("candidate_path") or "")
        if not video.is_file():
            job["state"] = "failed"
            job["permanent"] = True
            job["error"] = "candidate gone"
            save_jobs()
            return self._json({"error": "candidate gone"}, 410)
        with REVIEWED_LOCK:
            REVIEWED.pop(str(video), None)
        if approve:
            job["state"] = "moving"
            if finalize(job, video):
                clear_source_folder(video)
                cleanup_staging(job)
                log(f"approved {video.name}")
                return self._json({"ok": True, "filed": job.get("path", "")})
            return self._json({"error": job.get("error") or "move busy"}, 409)
        job["state"] = "failed"
        job["permanent"] = True
        job["error"] = "rejected by operator"
        save_jobs()
        if CFG["auto_delete_rejected"]:
            delete_candidate(video)
        log(f"rejected by operator: {video.name}")
        return self._json({"ok": True})

    def _grab(self, q):
        try:
            tmdb = int((q.get("tmdb") or [""])[0])
        except ValueError:
            return self._json({"error": "tmdb required"}, 400)
        force = (q.get("force") or [""])[0] in ("1", "true", "yes")

        if not force:
            existing_job = find_active_job(tmdb)
            if existing_job:
                return self._json(
                    {"error": f"already in queue ({existing_job['state']})", "job": public(existing_job)},
                    409,
                )
            existing_lib = find_existing_in_library(tmdb)
            if existing_lib:
                return self._json(
                    {"error": f"already in library: {existing_lib.name}", "path": str(existing_lib)},
                    409,
                )

        job = new_job(tmdb)
        with JOBS_LOCK:
            JOBS[job["id"]] = job
        save_jobs()

        try:
            meta, cands, why = resolve(tmdb)
        except Exception as e:
            job["state"] = "failed"
            job["permanent"] = True
            job["error"] = f"resolve: {e}"
            save_jobs()
            return self._json(public(job), 502)

        job.update(
            imdb_id=meta["imdb"],
            title=meta["title"],
            original_title=meta["original_title"],
            original_language=meta["original_language"],
            alternative_titles=meta["alternatives"],
            year=meta["year"],
            runtime=meta["runtime"],
            poster_path=meta["poster"],
        )

        if not cands:
            job["state"] = "failed"
            job["permanent"] = True
            job["error"] = why
            save_jobs()
            return self._json(public(job), 404)

        pick = cands[0]
        need = int(pick["size"] * 1.5) + int(CFG["min_free_gb"]) * (1024 ** 3)
        raw_free = free_bytes(Path(CFG["staging_root"]))
        avail = max(0, raw_free - reserved_bytes()) if raw_free else 0
        if raw_free and avail < need:
            job["state"] = "failed"
            job["error"] = f"low disk: {human(avail)} available ({human(reserved_bytes())} queued), need {human(need)}"
            save_jobs()
            return self._json(public(job), 507)

        base = safe_name(re.sub(r"\s*\((19|20)\d{2}\)\s*$", "", pick["title"] or "").strip()
                         or pick["title"] or "untitled")
        stem = f"{base} ({pick['year']})" if pick["year"] else base
        job["dir"] = safe_name(pick["torrent_name"] or stem)
        job["magnet_file"] = str(Path(CFG["staging_root"]) / (stem + ".magnet.txt"))
        staging = Path(CFG["staging_root"])
        staging.mkdir(parents=True, exist_ok=True)

        job.update(
            yts_title=pick["title"],
            quality=pick["quality"],
            size=pick["size"],
            hash=pick["hash"],
            magnet=pick["magnet"],
        )
        link = pick["url"] or pick["magnet"]

        if CFG["client"] == "aria2":
            try:
                job["gid"] = ARIA.add(link, job_dir(job))
            except Exception as e:
                job["state"] = "failed"
                job["error"] = f"aria2: {e}"
                save_jobs()
                return self._json(public(job), 502)
            job["state"] = "downloading"
            save_jobs()
            log(f"queued {pick['title']} [{pick['quality']}] {human(pick['size'])}")
            return self._json(public(job), 202)

        if CFG["client"] == "fdm":
            Path(job["magnet_file"]).write_text(pick["magnet"], encoding="utf-8")
            try:
                subprocess.Popen([CFG["fdm_path"], pick["magnet"]], close_fds=True)
            except Exception as e:
                job["state"] = "failed"
                job["error"] = f"fdm launch: {e}"
                save_jobs()
                return self._json(public(job), 502)
            job["state"] = "handed_off"
            save_jobs()
            log(f"handed to FDM: {pick['title']} [{pick['quality']}] -> {job['dir']}")
            return self._json(public(job), 202)

        Path(job["magnet_file"]).write_text(pick["magnet"], encoding="utf-8")
        job["state"] = "handed_off"
        save_jobs()
        log(f"magnet ready: {pick['title']} [{pick['quality']}]")
        return self._json(public(job), 202)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def load_config(path: str) -> dict:
    cfg = dict(DEFAULTS)
    p = Path(path) if path else None
    if p and p.exists():
        try:
            raw = p.read_text(encoding="utf-8-sig").strip()
            if not raw:
                log(f"config {p.name} is empty, using defaults")
            else:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    cfg.update(loaded)
                else:
                    log(f"config {p.name} is not an object, using defaults")
        except (OSError, ValueError) as e:
            log(f"config {p.name} unreadable ({e}), using defaults")
    elif p:
        log(f"config {p.name} not found, using defaults")
    for key in ("library_root", "staging_root"):
        if not cfg[key]:
            raise SystemExit(f"grab: {key} is required")
        Path(cfg[key]).mkdir(parents=True, exist_ok=True)
    if Path(cfg["library_root"]).resolve() == Path(cfg["staging_root"]).resolve():
        raise SystemExit("grab: staging_root must differ from library_root")
    roots = cfg.get("watch_roots") or []
    if not isinstance(roots, list):
        roots = [str(roots)]
    cleaned = []
    for r in roots:
        if not r:
            continue
        Path(r).mkdir(parents=True, exist_ok=True)
        cleaned.append(str(r))
    cfg["watch_roots"] = cleaned
    if not cfg.get("bind"):
        cfg["bind"] = "0.0.0.0"
    try:
        cfg["watch_depth"] = max(1, int(cfg.get("watch_depth") or 3))
    except (TypeError, ValueError):
        cfg["watch_depth"] = 3
    try:
        cfg["verify_runtime_tolerance_min"] = max(1, int(cfg.get("verify_runtime_tolerance_min") or 10))
    except (TypeError, ValueError):
        cfg["verify_runtime_tolerance_min"] = 10
    try:
        cfg["verify_runtime_long_tolerance_min"] = max(1, int(cfg.get("verify_runtime_long_tolerance_min") or 20))
    except (TypeError, ValueError):
        cfg["verify_runtime_long_tolerance_min"] = 20
    try:
        cfg["verify_size_tolerance_pct"] = max(1, int(cfg.get("verify_size_tolerance_pct") or 5))
    except (TypeError, ValueError):
        cfg["verify_size_tolerance_pct"] = 5
    return cfg


def main() -> None:
    global CFG, ARIA, FFPROBE
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="grab.json")
    ap.add_argument("--client", choices=["aria2", "fdm", "drop"])
    args = ap.parse_args()
    CFG = load_config(args.config)
    if args.client:
        CFG["client"] = args.client
    FFPROBE = find_ffprobe()
    load_jobs()

    if CFG["client"] == "aria2":
        ARIA = Aria2(CFG)
        try:
            ARIA._rpc("aria2.getVersion", [])
        except Exception as e:
            raise SystemExit(f"grab: aria2 RPC unreachable at {CFG['aria2_rpc']}: {e}")
        threading.Thread(target=aria_loop, daemon=True).start()
    else:
        threading.Thread(target=watcher_loop, daemon=True).start()
        if CFG["client"] == "fdm" and not Path(CFG["fdm_path"]).exists():
            log(f"warning: fdm_path not found: {CFG['fdm_path']}")

    bind = CFG["bind"]
    srv = Server((bind, int(CFG["port"])), Handler)
    log(f"grab {VERSION} on http://{bind}:{CFG['port']} mode={CFG['client']} max_quality={CFG['max_quality']}")
    if not CFG.get("tmdb_key"):
        log("warning: tmdb_key is empty in grab.json")
    if not FFPROBE:
        log("warning: ffprobe not found — every download will park for review")
    else:
        log(f"ffprobe {FFPROBE}")
    log(f"runtime tolerance -{CFG['verify_runtime_tolerance_min']}/+{CFG['verify_runtime_long_tolerance_min']} min, "
        f"size tolerance ±{CFG['verify_size_tolerance_pct']}%, "
        f"verify_audio_language={CFG['verify_audio_language']}, "
        f"auto_delete_rejected={CFG['auto_delete_rejected']}")
    log(f"library {CFG['library_root']}")
    log(f"staging {CFG['staging_root']}")
    log(f"watch depth {CFG['watch_depth']}")
    for r in watch_roots():
        log(f"watching {r}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        STOP.set()
        save_jobs()
        log("stopped")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
grab.py — RUIN.TO acquisition daemon (port 8789)

Decides how a TMDB id gets into your library, in a fixed order, and only accepts
what it can justify:

    feature:              yts  ->  provider  ->  youtube (proof-gated)  ->  queue
    short / AI / youtube: provider  ->  youtube (proof-gated)  ->  yts  ->  queue

The decision itself lives in source.py; this file carries it out. We are the
source, so a feature YTS indexes is fetched from YTS and no provider is asked for
it. A short film, an AI-generated film or a YouTube-hosted upload is a YTS title
only by accident, so those go to the provider and YouTube rungs first and YTS is
the last resort before queueing. A provider source must have been VERIFIED by
relay, and a YouTube candidate must satisfy a proof, before anything is downloaded.

YTS IS LOOKED UP BY TITLE. `query_term` matches titles only and returns
movie_count 0 for an IMDb code, which is what silently sent every title to a
provider. coverage.yts_rows owns the lookup; this file only builds magnets from
what it returns.

REJECTED TORRENTS ARE SKIPPED. A magnet that failed verify.postcheck is added to
the job's rejected set and filtered out of the next resolve, so a retry moves down
the candidate list instead of handing back the identical copy. When every
candidate has been rejected the job fails with `no untried torrent` rather than
looping.

QUALITY IS LOCKED TO 1080p. One file per title, at 1080p. A title without a 1080p
torrent falls to 720p, then 480p, then 2160p, then anything. Within a tier a
digital release always beats a cam, so a 720p WEB outranks a 1080p cam. min_seeds
is enforced; when nothing clears it the best-seeded candidate is still used and
the pick is marked `below_floor` so the log says so instead of the hand-off
looking healthy.

NOTHING IS FILED WITHOUT PASSING verify.postcheck. Every finished fetch is
probed: it must match the length the source promised, hold a real video and a
real audio stream, sit inside the length band around the TMDB runtime, and carry
the film's own language. A failure deletes the file, adds the URL to the job's
rejected set and re-decides. Three failures and the title queues. A pass that
cannot be length-checked (no TMDB runtime) is still filed but recorded in
review.jsonl.

AUDIO IS A LIST, NOT A CHOICE. Provider streams carry several audio tracks, dub
first, and picking one throws the rest away. Every track is kept instead, up to
max_audio_tracks, and the map order puts the film's own language first so the
player starts on the original and a viewer never has to hunt for it. Dubs are
then an extra rather than a substitute: a Spanish track is no longer a defect, it
is track 2 in the menu.

THE ORIGINAL TRACK IS PROVEN, NOT ASSUMED. A dub is routinely served with an
UNTAGGED stream, so a tag cannot be trusted to exist. Untagged tracks are
measured with whisper.cpp language identification: windows are cut from the
middle of the film and each is run on its own. A tagged track costs nothing --
the tag is trusted and no detection runs. Detection stops the moment a track is
decided, and the whole file stops being probed the moment one track proves to be
the original.

THE ASYMMETRY. A wrong-language verdict must be earned: the plurality has to
reach lang_min_agree votes and the probability floor before a track is recorded
as some other language. A right-language verdict only has to be the plurality,
even on one vote, because a track that leans English is not worth discarding on
noise. That biases toward filing a good copy rather than queueing a title, which
is the direction you want when the alternative is a missing film.

If no track resolves to the film's own language the file is deleted and the next
source is tried. On acceptance every track is stamped with its language and the
original is moved to track 0. Tracks that cannot be measured keep `und`.

Whisper must be run with -dl (or the JSON simply echoes the language it was told
to use) and the language is read from `result.language`, never `params.language`.

Consequence, and it is intended: a title whose only source is a dub QUEUES instead
of filing. Nothing wrong sits on the shelf. YTS is unaffected and needs none of
this -- a YTS release is original audio, correctly tagged, single track.

A title already in library.json is `present` and is not fetched again. POST
{"tmdb": N, "force": 1} overrides that.

ONE JOB PER TITLE, IN ANY STATE. find_job returns the row for a title and /grab
reuses it. A card load never re-runs the decision -- it just returns the row, so a
page left open cannot spin the provider sweep. Only force or POST /requeue re-decide.

SKIPS. Cancelling a title writes a permanent entry to skip.json, and a skipped title
answers instantly instead of starting a sweep, so browsing cannot refill the queue
with the same work. A skip survives /clear and survives page loads; force, /requeue
and /unskip are the ways back in. GET /needs marks skipped rows, GET /skips lists them.

POST /clear drops finished rows. GET /queue hides them unless ?all=1.

Filed name is always:

    <Title> (Year) [tmdb-<id>].mp4

A YouTube file also leaves a sidecar in provenance/<tmdb>.json naming the video id
and the proof. Jobs are memory-only, so without the sidecar a file fetched last
week could not be corrected without a re-fetch.

Three client modes, set "client" in grab.json:

  aria2   Fully automatic. Single .exe, no install. Real progress and completion detection.
  fdm     Hands the magnet to Free Download Manager. FDM pops its own window and uses its own
          default folder, so the file lands loose in the staging root and is adopted by title.
  drop    Nothing is launched. The API returns the magnet; the watcher files whatever lands.

In fdm and drop modes a watcher thread files new videos automatically, so you never rename
or move anything by hand. In aria2 mode the job gets its own folder, because aria2 honours
the path it is given and the folder then doubles as proof of whose file it is.

A `handed_off` job that produces nothing within stale_handoff_min minutes is failed, because
a downloader that silently ignores the magnet otherwise blocks that title forever.

watch_roots is the list of EXTRA folders the watcher looks in, on top of the staging root.
watch_depth bounds how far each root is walked, since a deep sweep of a whole drive is wasted work.

PROVIDER RUNG (allow_provider): the relay on 8787 is asked for a verified stream and ffmpeg
copies it into the job folder. Provider tokens expire mid-download on long films, so a 403 or
an expired-token exit re-resolves the title and restarts the fetch, twice, before giving up.
source.choose owns the relay call and the source ordering; this file only starts the fetch.

The audio map is built from a probe of the source, not guessed: the film's own language first,
then untagged tracks, then the rest, capped at max_audio_tracks. The probe must be told the
input is HLS and must ignore extensions, because the relay hands out /hls?u= URLs with no
suffix and the child playlists end in .html; without both ffprobe refuses the URL and every
track looks absent. When the probe still returns nothing the map falls back to every track, and
the post-download remux puts the original on track 0 instead.

CAM COPIES: a film still in cinemas has nothing but a cam, and a cam is the film, so it is
filed rather than queued -- but it is flagged. The flag lives on the job, in the API and in
the provenance sidecar. A cam sidecar does not make a title `present`: a grab on it always
re-checks, and if only another cam exists the job closes as `present` again instead of
re-fetching. cam_loop retries every cam title every cam_retry_hours and swaps in the first
non-cam copy that appears, on YTS or from a provider, deleting the cam before the new file is
moved in so the library does not accumulate " (2)" copies. cam_loop is started in every client
mode, so an aria2 setup gets upgrades too.

YOUTUBE RUNG (allow_youtube): yt-dlp fetches the proven video and merges it to mp4. It is
always handed --ffmpeg-location, because without ffmpeg on PATH yt-dlp silently downloads
video and audio as two files and the silent video is the larger one. Audio is preferred as
m4a, and if the result is any other codec (opus is what YouTube serves by default) the audio
is transcoded to AAC, because opus inside an MP4 plays in Chrome but not reliably elsewhere.
A file with no audio track fails the job instead of being filed.

ffmpeg is invoked with -extension_picky 0 because the relay hands out URLs like
/hls?u=... with no file extension, which newer ffmpeg refuses by default.

POST /wrong?id=<job>&tmdb=<id>&video=<id> is the manual correction loop. It deletes the filed
file, blacklists that video id STICKILY, and marks the job `wrong` so the title can be grabbed
again. POST /forgive?video=<id> drops a sticky entry without touching any file.

GET /needs returns the queue as JSON, newest first, one row per title.

Adoption is strict on purpose. A file is only claimed when every meaningful title word is present,
or when its size is within tolerance of the torrent, and never while the job's own staging folder
already holds a video. A file also has to be within tolerance of the expected size, so a stalled
download cannot be filed half-written.

    python grab.py --config grab.json
    curl "http://127.0.0.1:8789/dry?tmdb=1378742"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import coverage as cov
import source
import verify
from proofs import blacklist_add, blacklist_load, blacklist_remove

VERSION = "1.9.3"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ruin-grab/" + VERSION
VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".ts", ".m2ts"}
QUALITY_RANK = {"2160p": 4, "1080p": 3, "720p": 2, "480p": 1}
CAP_ORDER = {
    "2160p": ("2160p", "1080p", "720p", "480p"),
    "1080p": ("1080p", "720p", "480p", "2160p"),
    "720p": ("720p", "480p", "1080p", "2160p"),
    "480p": ("480p", "720p", "1080p", "2160p"),
}
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
STOP_TOKENS = {
    "the", "and", "of", "a", "an", "in", "on", "to", "for", "with", "part", "chapter",
    "vol", "aka", "yts", "yify", "x264", "x265", "aac", "web", "webrip", "bluray",
    "brrip", "bdrip", "hdtv", "remux", "proper", "repack", "extended", "unrated",
    "1080p", "720p", "2160p", "480p",
}
MIN_SIZE_RATIO = 0.75
TERMINAL = {"done", "failed", "cancelled", "wrong", "present", "skipped"}
REENTERABLE = {"queued", "wrong"}
BUSY = {"resolving", "fetching", "downloading", "moving", "handed_off"}
AUDIO_OK = {"aac", "mp3", "ac3", "eac3"}
EXPIRED_MARKERS = ("403", "410", "forbidden", "expired", "token", "unauthorized", "401")
MAX_PROVIDER_ATTEMPTS = 3
MAX_VERIFY_FAILS = 3
CATEGORICAL = {"P1", "P2", "P3", "P4"}

# whisper emits ISO 639-1 mostly, but a few models and a few TMDB records use the three-letter form.
LANG_ALIAS = {
    "eng": "en", "spa": "es", "fra": "fr", "fre": "fr", "deu": "de", "ger": "de",
    "ita": "it", "por": "pt", "rus": "ru", "jpn": "ja", "kor": "ko", "zho": "zh",
    "chi": "zh", "hin": "hi", "ara": "ar", "tur": "tr", "nld": "nl", "dut": "nl",
    "swe": "sv", "nor": "no", "dan": "da", "fin": "fi", "pol": "pl", "ell": "el",
    "gre": "el", "heb": "he", "tha": "th", "vie": "vi", "ces": "cs", "cze": "cs",
    "hun": "hu", "ron": "ro", "rum": "ro", "ukr": "uk", "ind": "id", "msa": "ms",
    "may": "ms", "fil": "fil", "tgl": "fil", "ben": "bn", "urd": "ur", "fas": "fa",
    "per": "fa", "cat": "ca", "srp": "sr", "hrv": "hr", "slk": "sk", "slo": "sk",
    "slv": "sl", "bul": "bg", "lit": "lt", "lav": "lv", "est": "et", "isl": "is",
    "gle": "ga", "cym": "cy", "glg": "gl", "eus": "eu", "baq": "eu", "mkd": "mk",
    "sqi": "sq", "alb": "sq", "hye": "hy", "arm": "hy", "kat": "ka", "geo": "ka",
    "aze": "az", "kaz": "kk", "uzb": "uz", "mon": "mn", "nep": "ne", "sin": "si",
    "tam": "ta", "tel": "te", "mal": "ml", "kan": "kn", "mar": "mr", "guj": "gu",
    "pan": "pa", "ori": "or", "asm": "as", "mya": "my", "bur": "my", "khm": "km",
    "lao": "lo", "bod": "bo", "tib": "bo", "div": "dv", "amh": "am", "som": "so",
    "swa": "sw", "yor": "yo", "ibo": "ig", "hau": "ha", "zul": "zu", "xho": "xh",
    "afr": "af", "mlt": "mt", "lat": "la", "epo": "eo", "yid": "yi",
}

DEFAULTS = {
    "host": "127.0.0.1",
    "bind": "0.0.0.0",
    "port": 8789,
    "tmdb_key": "c8b3444f786125dd2b69a88d34202de4",
    "library_root": r"D:\movies\library",
    "staging_root": r"D:\movies\staging",
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
    "stale_handoff_min": 120,
    "cam_retry_hours": 12,
    "allow_provider": True,
    "allow_youtube": True,
    "relay_url": "http://127.0.0.1:8787",
    "ffmpeg_dir": r"D:\my development work\development tools\ffmpeg\bin",
    "ytdlp_path": "",
    "max_audio_tracks": 4,
    "lang_check": True,
    "whisper_path": r"D:\my development work\development tools\ffmpeg\bin\whisper-cli.exe",
    "whisper_model": r"D:\my development work\development tools\ffmpeg\bin\ggml-base.bin",
    "lang_windows": 5,
    "lang_window_s": 30,
    "lang_min_p": 0.4,
    "lang_min_agree": 2,
    "lang_max_probe": 3,
}

STOP = threading.Event()
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
GRAB_LOCKS: dict[int, threading.Lock] = {}
GRAB_LOCKS_GUARD = threading.Lock()
FETCHERS: dict[str, subprocess.Popen] = {}
SEEN: dict[str, int] = {}
CFG: dict = {}
ARIA = None
FFMPEG = ""
YTDLP = ""
WHISPER = ""
NEEDS_PATH = Path(__file__).with_name("needs.jsonl")
REVIEW_PATH = Path(__file__).with_name("review.jsonl")
BLACKLIST_PATH = Path(__file__).with_name("yt_blacklist.json")
LIBRARY_PATH = Path(__file__).with_name("library.json")
SKIP_PATH = Path(__file__).with_name("skip.json")
PROV_DIR = Path(__file__).with_name("provenance")
SKIPS: dict[str, dict] = {}
SKIPS_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #

def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def grab_lock_for(tmdb_id: int) -> threading.Lock:
    with GRAB_LOCKS_GUARD:
        lock = GRAB_LOCKS.get(tmdb_id)
        if lock is None:
            lock = threading.Lock()
            GRAB_LOCKS[tmdb_id] = lock
        return lock


def http_get(url: str, timeout: int = 25, headers: dict | None = None) -> str:
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
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


def _tmdb_json(path: str) -> dict:
    key = str(CFG.get("tmdb_key") or "").strip()
    if not key:
        return {}
    url = f"https://api.themoviedb.org/3{path}"
    headers = None
    if len(key) > 60 or key.startswith("eyJ"):
        headers = {"Authorization": f"Bearer {key}"}
    else:
        sep = "&" if "?" in url else "?"
        url += f"{sep}api_key={urllib.parse.quote(key, safe='')}"
    try:
        data = http_json(url, headers=headers)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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


def safe_name(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]', "", s)
    s = re.sub(r"\s+", " ", s).strip().rstrip(".")
    return s[:120] or "untitled"


def same_lang(a: str, b: str) -> bool:
    """True when two language codes mean the same language, two-letter or three-letter."""
    a = (a or "").lower()
    b = (b or "").lower()
    if not a or not b:
        return False
    if a == b:
        return True
    return LANG_ALIAS.get(a) == b or LANG_ALIAS.get(b) == a


def in_library(tmdb: int) -> str:
    """Path of the filed copy when library.json already holds this id and the file exists."""
    try:
        data = json.loads(LIBRARY_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    for entry in data.get(str(tmdb)) or []:
        name = entry.get("file") if isinstance(entry, dict) else None
        if not name:
            continue
        p = Path(CFG["library_root"]) / name
        try:
            if p.is_file() and p.stat().st_size > 1024:
                return str(p)
        except OSError:
            continue
    return ""


def prov_write(tmdb: int, video_id: str, proof: str, title: str,
               cam: bool, path: str, audio_langs: list[str] | None = None,
               detect: str = "") -> None:
    """Remember which upload a filed copy came from, so it can be corrected later."""
    try:
        PROV_DIR.mkdir(exist_ok=True)
        (PROV_DIR / f"{tmdb}.json").write_text(json.dumps({
            "tmdb": tmdb, "video_id": video_id, "proof": proof,
            "title": title, "cam": bool(cam), "path": path,
            "audio_langs": list(audio_langs or []),
            "audio_detect": detect or "",
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, indent=1), encoding="utf-8")
    except OSError as e:
        log(f"provenance write failed: {e}")


def prov_read(tmdb: int) -> dict:
    try:
        return json.loads((PROV_DIR / f"{tmdb}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def prov_drop(tmdb: int) -> None:
    try:
        (PROV_DIR / f"{tmdb}.json").unlink()
    except OSError:
        pass


def review_write(row: dict) -> None:
    """A filed copy that could not be length-checked or could not be language-proven."""
    try:
        with REVIEW_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError as e:
        log(f"review write failed: {e}")


def is_cam_copy(tmdb: int) -> bool:
    """True when the library copy for this id came from a cam, so it is worth re-checking."""
    prov = prov_read(tmdb)
    if not prov.get("cam"):
        return False
    p = Path(prov.get("path") or "")
    try:
        return p.is_file()
    except OSError:
        return False


def looks_expired(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in EXPIRED_MARKERS)


def stale_handoff() -> float:
    try:
        return max(0.0, float(CFG.get("stale_handoff_min") or 0) * 60)
    except (TypeError, ValueError):
        return 7200.0


def kill_tree(proc) -> None:
    """Kill a fetch and its children. proc.kill() only reaps the parent on Windows, so a
    yt-dlp or ffmpeg child survives and keeps a lock on the staging folder."""
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=20)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# skips
# --------------------------------------------------------------------------- #

def load_skips() -> None:
    try:
        data = json.loads(SKIP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    with SKIPS_LOCK:
        SKIPS.clear()
        for key, value in data.items():
            if str(key).isdigit():
                SKIPS[str(key)] = value if isinstance(value, dict) else {}


def save_skips() -> None:
    with SKIPS_LOCK:
        snapshot = dict(SKIPS)
    try:
        SKIP_PATH.write_text(json.dumps(snapshot, indent=1, sort_keys=True), encoding="utf-8")
    except OSError as e:
        log(f"skip save failed: {e}")


def is_skipped(tmdb) -> bool:
    with SKIPS_LOCK:
        return str(tmdb) in SKIPS


def add_skip(tmdb, why: str = "") -> None:
    with SKIPS_LOCK:
        SKIPS[str(tmdb)] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "why": (why or "")[:200]}
    save_skips()


def drop_skip(tmdb) -> bool:
    with SKIPS_LOCK:
        had = SKIPS.pop(str(tmdb), None) is not None
    if had:
        save_skips()
    return had


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
            self.rpc,
            data=payload,
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
# resolution
# --------------------------------------------------------------------------- #

def tmdb_meta(tmdb_id: int) -> dict:
    """TMDB details with runtime converted to SECONDS at the boundary."""
    data = _tmdb_json(f"/movie/{int(tmdb_id)}")
    if not data:
        return {}
    return {
        "title": data.get("title") or data.get("original_title") or "",
        "year": (data.get("release_date") or "")[:4],
        "runtime": int(data.get("runtime") or 0) * 60,
        "homepage": data.get("homepage") or "",
        "original_language": (data.get("original_language") or "").lower(),
    }


def tmdb_imdb(tmdb_id: int) -> str | None:
    for path in (f"/movie/{int(tmdb_id)}/external_ids", f"/movie/{int(tmdb_id)}"):
        data = _tmdb_json(path)
        imdb = (data or {}).get("imdb_id")
        if imdb and str(imdb).startswith("tt"):
            return str(imdb)
    return None


def yts_candidates(imdb_id: str, title: str = "", year: str = "",
                   rejected=None) -> list[dict]:
    """Magnets for the right film, from the shared title lookup.

    coverage.yts_rows has already matched the title and year (or the IMDb code), so
    anything arriving here is this film and not a remake. Magnets already in
    `rejected` are dropped, so a re-decide moves down the list instead of handing
    back the copy that just failed verification.
    """
    blocked = {r for r in (rejected or ()) if r}
    out: list[dict] = []
    for m in cov.yts_rows(imdb_id, title, year):
        name = m.get("title_long") or m.get("title") or ""
        for t in m.get("torrents") or []:
            h = (t.get("hash") or "").lower()
            if not h:
                continue
            dn = f"{name or 'movie'} [{t.get('quality')}] [YTS]"
            magnet = "magnet:?xt=urn:btih:" + h + "&dn=" + urllib.parse.quote(dn)
            for tr in TRACKERS:
                magnet += "&tr=" + urllib.parse.quote(tr)
            if magnet in blocked:
                continue
            out.append(
                {
                    "quality": (t.get("quality") or "?").lower(),
                    "type": (t.get("type") or "").lower(),
                    "cam": cov.is_cam(t.get("type"), name),
                    "size": int(t.get("size_bytes") or 0),
                    "seeds": int(t.get("seeds") or 0),
                    "peers": int(t.get("peers") or 0),
                    "hash": h,
                    "url": t.get("url") or "",
                    "magnet": magnet,
                    "title": name,
                    "year": m.get("year"),
                }
            )
    return out


def rank(cands: list[dict]) -> list[dict]:
    """Best first: locked to the configured quality, digital before cam, then seeds.

    The quality order is a ladder, not a filter, so a title with no 1080p still gets
    fetched at 720p rather than queued. `cam` is compared before quality on purpose:
    a 720p WEB is worth more than a 1080p cam.

    min_seeds is a floor. When nothing clears it the best-seeded candidate is still
    used, but every pick carries `below_floor` so the caller can say so rather than
    presenting a 1-seed torrent as a healthy hand-off.
    """
    order = CAP_ORDER.get(CFG.get("max_quality") or "1080p", CAP_ORDER["1080p"])

    def pos(c: dict) -> int:
        try:
            return order.index(c["quality"])
        except ValueError:
            return len(order)

    min_seeds = int(CFG["min_seeds"])
    viable = [c for c in cands if c["seeds"] >= min_seeds]
    below = not viable
    pool = viable or list(cands)
    for c in pool:
        c["below_floor"] = below
    pool.sort(key=lambda c: (not c["cam"], -pos(c), c["seeds"], c["size"]), reverse=True)
    return pool


def resolve(tmdb_id: int, title: str = "", year: str = "",
            rejected=None) -> tuple[list[dict], str | None, dict]:
    """Ranked candidates for a title, minus anything already rejected."""
    meta = tmdb_meta(tmdb_id)
    title = title or meta.get("title") or ""
    year = str(year or meta.get("year") or "")
    imdb = tmdb_imdb(tmdb_id)
    if not title:
        return [], imdb, meta
    return rank(yts_candidates(imdb or "", title, year, rejected)), imdb, meta


# --------------------------------------------------------------------------- #
# fetching
# --------------------------------------------------------------------------- #

def ffprobe_path() -> str:
    if not FFMPEG:
        return ""
    p = Path(FFMPEG).with_name("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    return str(p) if p.is_file() else ""


def probe_source_audio(url: str) -> list[dict]:
    """Every audio stream the source offers, with its tag. [] when the probe fails.

    The probe needs -f hls and -allowed_extensions ALL: the relay serves /hls?u= URLs with no
    suffix and the child playlists end in .html, and without both ffprobe rejects the URL and
    every stream looks absent.
    """
    exe = ffprobe_path()
    if not exe:
        return []
    args = [exe, "-v", "error"]
    if "://" in url:
        args += ["-f", "hls", "-allowed_extensions", "ALL"]
    args += ["-select_streams", "a",
             "-show_entries", "stream=index:stream_tags=language", "-of", "json", url]
    try:
        raw = subprocess.run(args, capture_output=True, timeout=25).stdout
        streams = (json.loads(raw.decode("utf-8", "replace") or "{}")).get("streams") or []
    except Exception:
        return []
    out: list[dict] = []
    for s in streams:
        try:
            out.append({
                "abs": int(s["index"]),
                "lang": ((s.get("tags") or {}).get("language") or "").lower(),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out


def audio_order(url: str, want: str) -> list[int]:
    """Absolute stream indices to keep, the film's own language first.

    Ordering the map this way means the original lands on audio track 0, so the player starts on
    it and a viewer never has to switch. Untagged tracks come next because the dub is the common
    untagged case and they are the ones most likely to be the original in a lazy mux; everything
    else follows. The list is capped so a badly muxed source cannot ship a dozen tracks.
    """
    tracks = probe_source_audio(url)
    if not tracks:
        return []
    primary = [t["abs"] for t in tracks if same_lang(t["lang"], want)]
    neutral = [t["abs"] for t in tracks if t["lang"] in ("", "und")]
    rest = [t["abs"] for t in tracks
            if t["abs"] not in primary and t["abs"] not in neutral]
    order = primary + neutral + rest
    cap = max(1, min(8, int(CFG.get("max_audio_tracks") or 4)))
    return order[:cap]


def fetch_start(job: dict, url: str, seconds: int, kind: str) -> None:
    out = job_dir(job)
    out.mkdir(parents=True, exist_ok=True)
    target = out / (safe_name(job["title"] or "movie") + ".mp4")
    job["target"] = str(target)
    job["fetch_seconds"] = seconds
    job["state"] = "fetching"

    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-extension_picky", "0", "-allowed_extensions", "ALL",
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
    ]
    if kind != "mp4":
        cmd += ["-f", "hls"]
    cmd += ["-i", url]

    # every audio track is kept, the film's own language first; the probe decides the order
    order = audio_order(url, job.get("want_lang") or "en")
    cmd += ["-map", "0:v:0?"]
    if order:
        for index in order:
            cmd += ["-map", "0:%d" % index]
    else:
        cmd += ["-map", "0:a?"]
    cmd += ["-c", "copy", "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats", str(target)]

    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    FETCHERS[job["id"]] = proc

    def read_out():
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("out_time_us="):
                continue
            try:
                us = int(line.split("=", 1)[1])
            except ValueError:
                continue
            if seconds > 0:
                job["progress"] = min(0.99, (us / 1_000_000) / seconds)

    def read_err():
        tail: list[str] = []
        for raw in proc.stderr:
            text = raw.decode("utf-8", "replace").strip()
            if text:
                tail.append(text)
                del tail[:-8]
        job["fetch_err"] = " | ".join(tail)[-400:]

    threading.Thread(target=read_out, daemon=True).start()
    threading.Thread(target=read_err, daemon=True).start()
    log(f"fetch start {job['title']} ({seconds}s, {kind}, audio tracks "
        f"{len(order) or 'all'}{' ' + str(order) if order else ''})")


def audio_codec(video: Path) -> str:
    """Codec name of the first audio stream, or "" when there is none."""
    exe = ffprobe_path()
    if not exe:
        return "?"
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(video)],
            capture_output=True, timeout=30,
        )
        return out.stdout.decode("utf-8", "replace").strip().lower()
    except Exception:
        return "?"


def probe_file(video: Path) -> dict:
    """Duration, stream presence, and every audio track as {rel, abs, lang, codec}.

    `rel` is the audio-relative index used by -map 0:a:N and -metadata:s:a:N; `abs` is the
    container stream index. Both are kept because ffprobe reports absolute and the muxer wants
    relative.
    """
    out = {"seconds": 0, "video": False, "audio": False, "lang": "", "tracks": []}
    exe = ffprobe_path()
    if not exe:
        return out
    try:
        proc = subprocess.run(
            [exe, "-v", "error", "-print_format", "json",
             "-show_streams", "-show_format", str(video)],
            capture_output=True, timeout=120,
        )
        info = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except Exception:
        return out
    rel = 0
    for stream in info.get("streams") or []:
        if stream.get("codec_type") == "video":
            out["video"] = True
        elif stream.get("codec_type") == "audio":
            out["audio"] = True
            lang = ((stream.get("tags") or {}).get("language") or "").lower()
            out["tracks"].append({
                "rel": rel, "abs": stream.get("index"),
                "lang": lang, "codec": (stream.get("codec_name") or "").lower(),
            })
            rel += 1
            if not out["lang"]:
                out["lang"] = lang
    try:
        out["seconds"] = int(float((info.get("format") or {}).get("duration") or 0))
    except (TypeError, ValueError):
        pass
    return out


def to_aac(video: Path) -> tuple[bool, str]:
    """Copy the video, transcode the audio to AAC. opus-in-mp4 is not portable."""
    if not FFMPEG:
        return False, "ffmpeg missing"
    tmp = video.with_name(video.stem + ".aac.mp4")
    try:
        proc = subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             "-i", str(video), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(tmp)],
            capture_output=True, timeout=1800,
        )
    except Exception as e:
        return False, f"aac: {e}"
    if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1024:
        tail = proc.stderr.decode("utf-8", "replace").strip()[-200:]
        tmp.unlink(missing_ok=True)
        return False, "aac failed: " + (tail or f"exit {proc.returncode}")
    try:
        video.unlink()
    except OSError:
        pass
    tmp.replace(video)
    return True, ""


# --------------------------------------------------------------------------- #
# spoken language proof
# --------------------------------------------------------------------------- #

def detect_lang(video: Path, seconds: int, track: int = 0) -> dict:
    """Measure the spoken language of ONE track, and stop as soon as it is decided.

    A dub is served untagged, so nothing in the container states the language and the only
    evidence is the audio itself. Windows are spread across the middle of the film -- never the
    first or last 8%, where title music and end credits live -- and each is run through whisper
    language identification on its own. A single bad window therefore cannot decide the result,
    while agreeing windows cannot be fooled by a dub. Once one language reaches the agreement
    count at the probability floor, the remaining windows are skipped.

    More windows than a bare majority are used on purpose: an unsure track often answers three
    different languages in three windows, and a two-thirds threshold then never fires. A
    plurality is a usable answer; a tie is not.

    whisper must be run with -dl or the JSON only echoes the language it was told to use, and
    the answer is read from `result.language`, never `params.language`. -bs 1 drops beam search,
    which roughly halves the run time and does not hurt identification.

    Returns {"lang", "p", "votes", "why"}. "lang" is "" when nothing could be measured, which
    the caller treats as unknown rather than as a mismatch.
    """
    out = {"lang": "", "p": 0.0, "votes": {}, "why": ""}
    exe = WHISPER
    model = str(CFG.get("whisper_model") or "")
    if not exe or not model or not Path(model).is_file():
        out["why"] = "whisper unavailable"
        return out
    if seconds <= 0:
        out["why"] = "no duration"
        return out
    if seconds < 120:
        out["why"] = "too short to sample"
        return out

    windows = max(1, min(7, int(CFG.get("lang_windows") or 5)))
    length = max(10, min(60, int(CFG.get("lang_window_s") or 30)))
    need = max(1, min(7, int(CFG.get("lang_min_agree") or 2)))
    floor = float(CFG.get("lang_min_p") or 0.4)
    threads = str(max(2, min(6, (os.cpu_count() or 4) // 2)))
    scores: dict[str, float] = {}
    votes: dict[str, int] = {}
    usable = 0

    for index in range(windows):
        frac = (index + 1) / (windows + 1)
        start = int(seconds * (0.08 + frac * 0.84))
        start = max(0, min(start, max(0, seconds - length - 1)))
        stamp = uuid.uuid4().hex[:8]
        sample = Path(tempfile.gettempdir()) / f"ruin_lang_{stamp}.wav"
        report = Path(tempfile.gettempdir()) / f"ruin_lang_{stamp}"
        try:
            cut = subprocess.run(
                [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-ss", str(start), "-t", str(length), "-i", str(video),
                 "-map", "0:a:%d" % track, "-vn", "-sn", "-dn",
                 "-ac", "1", "-ar", "16000", "-af", "highpass=f=120",
                 "-f", "wav", str(sample)],
                capture_output=True, timeout=240,
            )
            if cut.returncode != 0 or not sample.is_file() or sample.stat().st_size < 16000:
                continue
            subprocess.run(
                [exe, "-m", model, "-f", str(sample), "-dl", "-bs", "1", "-nt",
                 "-oj", "-of", str(report), "-t", threads],
                capture_output=True, timeout=600,
            )
            data = json.loads((report.with_suffix(".json"))
                              .read_text(encoding="utf-8", errors="replace"))
            found = str(((data or {}).get("result") or {}).get("language") or "").lower()
            if not found or found == "auto":
                continue
            # whisper does not report a probability in the JSON, so each usable window counts
            # as a full vote and the mean is taken over the windows that answered
            usable += 1
            votes[found] = votes.get(found, 0) + 1
            scores[found] = scores.get(found, 0.0) + 1.0
            if votes[found] >= need and (scores[found] / usable) >= floor:
                break
        except Exception:
            continue
        finally:
            sample.unlink(missing_ok=True)
            report.with_suffix(".json").unlink(missing_ok=True)

    out["votes"] = votes
    if not usable:
        out["why"] = "no usable window"
        return out
    best = max(scores, key=lambda k: (votes.get(k, 0), scores[k]))
    out["lang"] = best
    out["p"] = round(votes[best] / usable, 3)
    out["why"] = f"{best} {votes.get(best, 0)}/{usable}"
    return out


def stamp_langs(video: Path, resolved: list[tuple[int, str]], first: int) -> bool:
    """One remux: put the original track first and label every track with its language.

    `resolved` is (audio-relative index, language) in the file's current order. `first` is the
    track that carries the film's own language; it becomes audio track 0 so the player starts on
    it. Tracks that could not be identified keep whatever tag they had, including none.
    """
    if not FFMPEG:
        return False
    langs = {rel: lang for rel, lang in resolved}
    order = [first] + [rel for rel, _ in resolved if rel != first]
    tmp = video.with_name(video.stem + ".tag.mp4")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-i", str(video), "-map", "0:v:0"]
    for rel in order:
        cmd += ["-map", "0:a:%d" % rel]
    cmd += ["-c", "copy"]
    for pos, rel in enumerate(order):
        lang = langs.get(rel) or ""
        if lang:
            cmd += ["-metadata:s:a:%d" % pos, "language=" + lang]
    cmd += ["-movflags", "+faststart", str(tmp)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=2400)
    except Exception:
        return False
    if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 1024:
        tmp.unlink(missing_ok=True)
        return False
    try:
        video.unlink()
    except OSError:
        pass
    tmp.replace(video)
    return True


def yt_fetch_start(job: dict, video_id: str, seconds: int) -> None:
    """Fetch a proven YouTube candidate and merge it to mp4 in place."""
    out = job_dir(job)
    out.mkdir(parents=True, exist_ok=True)
    job["fetch_seconds"] = seconds
    job["state"] = "fetching"

    cmd = [
        YTDLP, "--no-warnings", "--no-playlist", "--newline", "--no-part",
        "--no-mtime", "--force-overwrites",
        "--retries", "10", "--fragment-retries", "10", "--retry-sleep", "2",
        "-f", ("bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]"
               "/bv*[height<=1080]+ba[ext=m4a]"
               "/b[height<=1080][ext=mp4]"
               "/bv*+ba/b"),
        "--merge-output-format", "mp4", "--remux-video", "mp4",
    ]
    if FFMPEG:
        cmd += ["--ffmpeg-location", str(Path(FFMPEG).parent)]
    cmd += ["-o", str(out / "download.%(ext)s"),
            f"https://www.youtube.com/watch?v={video_id}"]

    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    FETCHERS[job["id"]] = proc

    pct = re.compile(r"\[download\]\s+([\d.]+)%")

    def read_out():
        for raw in proc.stdout:
            m = pct.search(raw.decode("utf-8", "replace"))
            if m:
                try:
                    job["progress"] = min(0.99, float(m.group(1)) / 100)
                except ValueError:
                    pass

    def read_err():
        tail: list[str] = []
        for raw in proc.stderr:
            text = raw.decode("utf-8", "replace").strip()
            if text:
                tail.append(text)
                del tail[:-8]
        job["fetch_err"] = " | ".join(tail)[-400:]

    threading.Thread(target=read_out, daemon=True).start()
    threading.Thread(target=read_err, daemon=True).start()
    log(f"youtube fetch {job['title']} ({video_id}, {seconds}s)")


def retry_provider(job: dict) -> None:
    """The token on a provider stream dies part way through a long film."""
    time.sleep(2)
    if job["state"] != "fetching" and job.get("rung") != "provider":
        return
    try:
        plan = source.choose(str(job["tmdb"]), job.get("rejected"))
    except Exception as e:
        job["state"] = "failed"
        job["error"] = f"re-resolve: {e}"
        return
    if plan.get("rung") != "provider" or not plan.get("url"):
        job["state"] = "failed"
        job["error"] = "re-resolve: no provider source"
        return
    job["fetch_err"] = ""
    job["progress"] = 0.0
    job["quality"] = plan.get("quality") or job.get("quality") or ""
    job["cam"] = bool(plan.get("cam"))
    job["fetch_direct"] = plan.get("direct") or plan.get("url") or ""
    job["expected"] = int(plan.get("seconds") or 0)
    log(f"re-resolved {job['title']} via {plan.get('label')} "
        f"(attempt {job.get('attempts')}/{MAX_PROVIDER_ATTEMPTS})")
    try:
        fetch_start(job, plan["url"], int(plan.get("seconds") or 0), "hls")
    except Exception as e:
        job["state"] = "failed"
        job["error"] = f"retry start: {e}"


def _spawn_finalize(job: dict, video: Path, transcode_yt: bool = False) -> None:
    """Run post-fetch transcode, verification, and library filing off the poller loops."""
    job["state"] = "moving"

    def run():
        try:
            if transcode_yt:
                codec = audio_codec(video)
                if codec == "":
                    job["state"] = "failed"
                    job["error"] = "no audio track (merge failed, ffmpeg-location?)"
                    clear_source_folder(video)
                    cleanup_staging(job)
                    return
                if codec not in AUDIO_OK and codec != "?":
                    ok, err = to_aac(video)
                    if not ok:
                        job["state"] = "failed"
                        job["error"] = err
                        clear_source_folder(video)
                        cleanup_staging(job)
                        return
                    log(f"audio {codec} -> aac for {job['title']}")
            finalize(job, video)
        except Exception as e:
            job["state"] = "failed"
            job["error"] = f"finalize: {e}"
            clear_source_folder(video)
            cleanup_staging(job)

    threading.Thread(target=run, daemon=True).start()


def fetch_tick() -> None:
    with JOBS_LOCK:
        active = [j for j in JOBS.values() if j["state"] == "fetching"]
    for job in active:
        proc = FETCHERS.get(job["id"])
        if proc is None or proc.poll() is None:
            continue
        FETCHERS.pop(job["id"], None)
        if proc.returncode == 0:
            video = find_video(job_dir(job))
            if not video:
                job["state"] = "failed"
                job["error"] = "fetch produced no video"
                cleanup_staging(job)
                continue
            _spawn_finalize(job, video, transcode_yt=(job.get("rung") == "youtube"))
            continue

        err = job.get("fetch_err") or f"fetch exit {proc.returncode}"
        if (job.get("rung") == "provider"
                and int(job.get("attempts") or 0) < MAX_PROVIDER_ATTEMPTS
                and looks_expired(err)):
            job["attempts"] = int(job.get("attempts") or 0) + 1
            job["state"] = "fetching"
            log(f"token died on {job['title']}, re-resolving (attempt {job['attempts']})")
            threading.Thread(target=retry_provider, args=(job,), daemon=True).start()
            continue

        job["state"] = "failed"
        job["error"] = err
        cleanup_staging(job)


def fetch_loop() -> None:
    while not STOP.is_set():
        try:
            fetch_tick()
        except Exception as e:
            log(f"fetch: {e}")
        STOP.wait(3)


# --------------------------------------------------------------------------- #
# jobs
# --------------------------------------------------------------------------- #

def new_job(tmdb_id: int) -> dict:
    return {
        "id": uuid.uuid4().hex[:12],
        "tmdb": tmdb_id,
        "title": "",
        "year": "",
        "imdb": "",
        "quality": "",
        "size": 0,
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
        "added": time.time(),
        "target": "",
        "fetch_seconds": 0,
        "fetch_err": "",
        "fetch_direct": "",
        "source": "",
        "rung": "",
        "video_id": "",
        "proof": "",
        "attempts": 0,
        "cam": False,
        "upgrade": False,
        "force": False,
        "runtime": 0,
        "want_lang": "",
        "expected": 0,
        "verify_fails": 0,
        "audio_lang": "",
        "audio_langs": [],
        "audio_detect": "",
        "rejected": [],
    }


def job_dir(job: dict) -> Path:
    """The job's own working folder, named after the film."""
    return Path(CFG["staging_root"]) / (job.get("dir") or job["id"])


def public(j: dict) -> dict:
    d = dict(j)
    d["size_h"] = human(j["size"]) if j["size"] else ""
    d["speed_h"] = human(j["speed"]) + "/s" if j["speed"] else ""
    d["progress_pct"] = round(j["progress"] * 100, 1)
    d["cam"] = bool(j.get("cam"))
    d["error"] = (j.get("error") or "")[:300]
    d["staging"] = str(job_dir(j)) if j.get("dir") else CFG["staging_root"]
    d["skipped"] = is_skipped(j["tmdb"])
    return d


def snapshot(all_rows: bool = False) -> list[dict]:
    """Live work only, newest first. Finished rows are noise once they are over."""
    with JOBS_LOCK:
        items = [public(j) for j in JOBS.values()]
    if not all_rows:
        items = [j for j in items if j["state"] not in TERMINAL]
    items.sort(key=lambda j: j["added"], reverse=True)
    return items


def find_job(tmdb_id: int) -> dict | None:
    with JOBS_LOCK:
        for job in JOBS.values():
            if job["tmdb"] == tmdb_id:
                return job
    return None


def active_for(tmdb_id: int) -> dict | None:
    with JOBS_LOCK:
        for job in JOBS.values():
            if job["tmdb"] != tmdb_id:
                continue
            if job["state"] in TERMINAL or job["state"] in REENTERABLE:
                continue
            return job
    return None


def needs_rows() -> list[dict]:
    """The queue, newest first, one row per title (the newest row for it)."""
    if not NEEDS_PATH.exists():
        return []
    latest: dict[str, dict] = {}
    order: list[str] = []
    try:
        with NEEDS_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                tmdb = str(row.get("tmdb") or "")
                if not tmdb.isdigit():
                    continue
                if tmdb not in latest:
                    order.append(tmdb)
                latest[tmdb] = row
    except OSError:
        return []
    rows = [latest[t] for t in order]
    rows.sort(key=lambda r: r.get("at") or "", reverse=True)
    for row in rows:
        have = in_library(int(row["tmdb"]))
        row["in_library"] = bool(have)
        row["path"] = have
        row["skipped"] = is_skipped(row["tmdb"])
    return rows


def queue_needs(plan: dict) -> None:
    """Record a queued title so the sweep can retry it when TMDB learns something."""
    tmdb = str(plan.get("tmdb") or "")
    fp = plan.get("fp") or ""
    if tmdb.isdigit():
        for row in needs_rows():
            if str(row.get("tmdb")) == tmdb and (row.get("fp") or "") == fp:
                return
    try:
        with NEEDS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "tmdb": plan.get("tmdb"),
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "fp": fp,
                "title": plan.get("title") or "",
                "why": plan.get("why") or "",
                "tried": plan.get("tried") or [],
            }) + "\n")
    except OSError as e:
        log(f"needs write failed: {e}")


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


def resolve_track_langs(job: dict, video: Path, info: dict, want: str) -> int:
    """Language for every track, and the index of the one carrying the film's own language.

    A tagged track is trusted and costs nothing. Untagged tracks are measured in order, and the
    whole loop stops the moment one of them is the original -- tracks after that point are left
    unlabelled rather than probed for the menu's benefit, because that is where the minutes go.
    At most lang_max_probe tracks are measured before giving up.

    The test is deliberately asymmetric. The film's own language only has to be the plurality of
    the windows; any OTHER language has to reach the agreement count and the probability floor
    before the track is written off. That way an unsure track that leans English is kept rather
    than thrown away, while a confident foreign one still rejects.

    Returns -1 when no track is the original, which is the reject case.
    """
    resolved: list[tuple[int, str]] = []
    original = -1
    probed = 0
    limit = max(1, min(8, int(CFG.get("lang_max_probe") or 3)))
    need = max(1, min(7, int(CFG.get("lang_min_agree") or 2)))
    floor = float(CFG.get("lang_min_p") or 0.4)

    for track in info["tracks"]:
        rel = track["rel"]
        tag = (track["lang"] or "").lower()
        if tag and tag not in ("und", "unk"):
            resolved.append((rel, tag))
            if same_lang(tag, want):
                original = rel
                break
            continue
        if probed >= limit:
            resolved.append((rel, ""))
            continue
        probed += 1
        verdict = detect_lang(video, info["seconds"], rel)
        job["audio_detect"] = (job.get("audio_detect") or "") + f"a{rel}:{verdict['why']};"
        found = verdict["lang"]
        agree = verdict["votes"].get(found, 0) if found else 0
        if found and same_lang(found, want):
            resolved.append((rel, want))
            original = rel
            break
        if found and agree >= need and verdict["p"] >= floor:
            resolved.append((rel, found))
        else:
            resolved.append((rel, ""))

    if original < 0:
        return -1
    seen = {rel for rel, _ in resolved}
    for track in info["tracks"]:
        if track["rel"] not in seen:
            resolved.append((track["rel"], ""))
    resolved.sort(key=lambda pair: pair[0])
    job["audio_langs"] = [lang for _, lang in resolved if lang]
    already_ok = (
        original == 0
        and all((t["lang"] or "") == (lang or "") for t, (_, lang) in zip(info["tracks"], resolved))
    )
    if already_ok:
        log(f"audio proven for {job['title']}: track 0 already {want}")
    elif stamp_langs(video, resolved, original):
        log(f"audio proven for {job['title']}: {len(resolved)} track(s), "
            f"original a{original} first")
    else:
        log(f"audio proven for {job['title']} but the language stamp failed")
    return original


def finalize(job: dict, video: Path) -> None:
    """Prove the original audio, verify the file, then file it. A failure deletes it and moves on."""
    info = probe_file(video)
    want = (job.get("want_lang") or "").lower()

    if CFG.get("lang_check") and want and info["tracks"]:
        original = resolve_track_langs(job, video, info, want)
        if original < 0:
            reject_and_retry(job, video,
                             f"no {want} audio in {len(info['tracks'])} track(s): "
                             f"{(job.get('audio_detect') or '')[:140]}")
            return
        info["lang"] = want
        job["audio_lang"] = want
    elif want and info["tracks"]:
        for t in info["tracks"]:
            if verify.audio_ok(t["lang"], want):
                info["lang"] = t["lang"]
                break

    verdict = verify.postcheck(info["seconds"], int(job.get("expected") or 0),
                               int(job.get("runtime") or 0),
                               info["video"], info["audio"],
                               info.get("lang") or "", job.get("want_lang") or "")
    if verdict["verdict"] == verify.REJECTED:
        reject_and_retry(job, video, verdict["why"])
        return
    if verdict["verdict"] == verify.UNVERIFIED:
        review_write({
            "at": time.strftime("%Y-%m-%d %H:%M:%S"), "tmdb": job["tmdb"],
            "title": job.get("title"), "year": job.get("year"),
            "rung": job.get("rung"), "seconds": info["seconds"],
            "langs": job.get("audio_langs") or [], "detect": job.get("audio_detect") or "",
            "why": verdict["why"], "url": job.get("fetch_direct") or job.get("video_id") or "",
        })

    if job.get("upgrade"):
        old = prov_read(job["tmdb"]).get("path") or ""
        if old and Path(old).exists():
            try:
                Path(old).unlink()
                log(f"replacing cam {Path(old).name}")
            except OSError as e:
                log(f"cam replace failed: {e}")
    try:
        dest = file_into_library(video, job["tmdb"], job["title"], job["year"])
    except Exception as e:
        job["state"] = "failed"
        job["error"] = f"move: {e}"
        clear_source_folder(video)
        cleanup_staging(job)
        return
    job["path"] = str(dest)
    job["progress"] = 1.0
    job["state"] = "done"
    prov_write(job["tmdb"], job.get("video_id") or "", job.get("proof") or "",
               job.get("title") or "", bool(job.get("cam")), str(dest),
               job.get("audio_langs") or [], job.get("audio_detect") or "")
    clear_source_folder(video)
    cleanup_staging(job)
    try:
        log(f"filed {dest.name} ({human(dest.stat().st_size)})"
            + (" [cam]" if job.get("cam") else "")
            + f" audio={'+'.join(job.get('audio_langs') or []) or '?'}")
    except OSError:
        log(f"filed {dest.name}")
    poke_scan()


def reject_and_retry(job: dict, video: Path, why: str) -> None:
    """Wrong film or wrong language: delete it, remember the URL, decide again."""
    try:
        video.unlink()
    except OSError:
        pass
    direct = job.get("fetch_direct") or ""
    if direct and direct not in job["rejected"]:
        job["rejected"].append(direct)
    vid = job.get("video_id") or ""
    if job.get("rung") == "youtube" and vid:
        if vid not in job["rejected"]:
            job["rejected"].append(vid)
        try:
            blacklist_add(BLACKLIST_PATH, vid, why[:140], sticky=False)
        except OSError:
            pass
    job["verify_fails"] = int(job.get("verify_fails") or 0) + 1
    log(f"rejected {job.get('title')}: {why} (fail {job['verify_fails']}/{MAX_VERIFY_FAILS})")

    if job["verify_fails"] >= MAX_VERIFY_FAILS:
        job["state"] = "queued"
        job["error"] = f"no verified source: {why}"
        queue_needs({"tmdb": job["tmdb"], "title": job.get("title") or "",
                     "why": job["error"], "fp": ""})
        clear_source_folder(video)
        cleanup_staging(job)
        return
    job["state"] = "resolving"
    threading.Thread(target=redecide, args=(job,), daemon=True).start()


def redecide(job: dict) -> None:
    try:
        plan = source.choose(str(job["tmdb"]), job.get("rejected"))
    except Exception as e:
        job["state"] = "failed"
        job["error"] = f"choose: {e}"
        cleanup_staging(job)
        return
    job.update(title=plan.get("title") or job["title"],
               year=str(plan.get("year") or job["year"]),
               imdb=plan.get("imdb") or job["imdb"],
               runtime=int(plan.get("runtime") or job.get("runtime") or 0),
               rung=plan.get("rung") or "", source=plan.get("rung") or "")
    dispatch(job, plan)


def cleanup_staging(job: dict) -> None:
    """The magnet note always goes. A job folder only ever exists in aria2 mode, and only goes when it
    no longer holds a video."""
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
        par = parent.resolve()
    except OSError:
        return
    if par == staging:
        return
    try:
        inside_staging = staging in par.parents
    except OSError:
        inside_staging = False
    if inside_staging:
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
# aria2 poller
# --------------------------------------------------------------------------- #

def aria_tick() -> None:
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
            d = job_dir(job)
            video = find_video(d)
            if video:
                _spawn_finalize(job, video)
            else:
                job["state"] = "failed"
                job["error"] = "no video after download"
                cleanup_staging(job)
            ARIA.delete(job["gid"])
        elif st.get("status") == "error":
            job["state"] = "failed"
            job["error"] = st.get("errorMessage") or "aria2 error"
            cleanup_staging(job)


def aria_loop() -> None:
    while not STOP.is_set():
        try:
            aria_tick()
        except Exception as e:
            log(f"aria: {e}")
        STOP.wait(5)


# --------------------------------------------------------------------------- #
# drop-folder watcher (fdm + drop modes)
# --------------------------------------------------------------------------- #

def watch_roots() -> list[str]:
    roots = [CFG["staging_root"], *CFG.get("watch_roots", [])]
    return list(dict.fromkeys(r for r in roots if r))


def name_tokens(text: str) -> set[str]:
    raw = {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) > 2}
    meaningful = raw - STOP_TOKENS
    return meaningful or raw


def adoptable(video: Path, size: int) -> dict | None:
    with JOBS_LOCK:
        pending = [j for j in JOBS.values() if j["state"] == "handed_off"]
    if not pending:
        return None

    free = [j for j in pending
            if not find_video(job_dir(j))
            and (not j["size"] or size >= j["size"] * MIN_SIZE_RATIO)]

    have = name_tokens(video.stem)
    for job in free:
        want = name_tokens(job["title"] or "")
        if want and want <= have:
            return job
    for job in free:
        if not job["size"]:
            continue
        if abs(size - job["size"]) <= job["size"] * 0.15:
            return job
    return None


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
                p = here / f
                if p.suffix.lower() not in VIDEO_EXT:
                    continue
                if any(tok in f.lower() for tok in SKIP_TOKENS):
                    continue
                try:
                    size = p.stat().st_size
                except OSError:
                    continue
                if size < min_size:
                    continue
                if SEEN.get(str(p)) != size:
                    SEEN[str(p)] = size
                    continue
                job = adoptable(p, size)
                if not job:
                    continue
                SEEN.pop(str(p), None)
                _spawn_finalize(job, p)


def cam_titles() -> list[int]:
    out: list[int] = []
    if not PROV_DIR.exists():
        return out
    for p in PROV_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tmdb = str(d.get("tmdb") or "")
        if d.get("cam") and tmdb.isdigit():
            out.append(int(tmdb))
    return out


def cam_pass() -> None:
    """Retry every cam copy. A cam is the film, so it is filed, but never the last word."""
    for tmdb in cam_titles():
        if active_for(tmdb):
            continue
        prov = prov_read(tmdb)
        try:
            if not Path(prov.get("path") or "").is_file():
                continue
        except OSError:
            continue
        job = find_job(tmdb)
        if job is not None and job["state"] not in TERMINAL:
            continue
        try:
            plan = source.choose(str(tmdb))
        except Exception as e:
            log(f"cam retry {tmdb}: {e}")
            continue
        rung = plan.get("rung")
        if rung == "yts":
            pass
        elif rung == "provider":
            if plan.get("cam") or not plan.get("url"):
                continue
        else:
            continue
        if job is None:
            job = new_job(tmdb)
            with JOBS_LOCK:
                JOBS[job["id"]] = job
        else:
            job["state"] = "resolving"
            job["error"] = ""
            job["proof"] = ""
            job["attempts"] = 0
            job["progress"] = 0.0
            job["verify_fails"] = 0
            job["rejected"] = []
        job.update(title=plan.get("title") or "", year=str(plan.get("year") or ""),
                   imdb=plan.get("imdb") or "", rung=rung, source=rung,
                   runtime=int(plan.get("runtime") or 0), upgrade=True,
                   want_lang=plan.get("original_language") or job.get("want_lang") or "en")
        if rung == "yts":
            yts_path(job, tmdb, plan)
            if job["state"] in ("handed_off", "downloading"):
                log(f"cam upgrade started for {job['title']}")
        else:
            ok, err, _code = provider_start(job, plan)
            if ok:
                log(f"cam upgrade started for {job['title']}")
            else:
                log(f"cam upgrade skipped for {tmdb}: {err}")


def cam_loop() -> None:
    """Cam upgrades, in every client mode.

    This used to be driven from watcher_loop, which only exists in fdm and drop modes, so
    an aria2 setup silently never upgraded a cam. It is its own loop now.
    """
    while not STOP.is_set():
        try:
            hours = float(CFG.get("cam_retry_hours") or 0)
        except (TypeError, ValueError):
            hours = 0.0
        if hours <= 0:
            return
        STOP.wait(hours * 3600)
        if STOP.is_set():
            return
        try:
            cam_pass()
        except Exception as e:
            log(f"cam pass: {e}")


def watcher_loop() -> None:
    min_size = int(CFG["min_file_mb"]) * 1024 * 1024
    while not STOP.is_set():
        try:
            with JOBS_LOCK:
                handed = [j for j in JOBS.values() if j["state"] == "handed_off"]

            limit = stale_handoff()
            for job in handed:
                if job["state"] != "handed_off":
                    continue
                if time.time() - job["added"] < limit:
                    continue
                job["state"] = "failed"
                job["error"] = "FDM never produced a file"
                cleanup_staging(job)
                log(f"stale hand-off: {job['title']}")

            for job in handed:
                if job["state"] != "handed_off":
                    continue
                v = find_video(job_dir(job))
                if not v:
                    continue
                try:
                    s1 = v.stat().st_size
                    time.sleep(2.5)
                    if v.stat().st_size != s1 or s1 < min_size:
                        continue
                except OSError:
                    continue
                _spawn_finalize(job, v)

            scan_roots(min_size)

            if len(SEEN) > 4000:
                SEEN.clear()
        except Exception as e:
            log(f"watch: {e}")
        STOP.wait(6)


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #

def dispatch(job: dict, plan: dict) -> tuple[dict, int]:
    """Carry out a plan. Returns (public job, http status)."""
    rung = plan.get("rung")
    job["runtime"] = int(plan.get("runtime") or job.get("runtime") or 0)
    job["want_lang"] = (plan.get("original_language") or job.get("want_lang") or "").lower()
    if not job["want_lang"] or not job["runtime"]:
        meta = tmdb_meta(job["tmdb"])
        if not job["runtime"]:
            job["runtime"] = int(meta.get("runtime") or 0)
        if not job["want_lang"]:
            job["want_lang"] = (meta.get("original_language") or "en").lower()
    if rung == "yts":
        return yts_path(job, job["tmdb"], plan)
    if rung == "provider":
        return provider_path(job, plan)
    if rung == "youtube":
        return youtube_path(job, plan)

    if plan.get("state") == "unreleased":
        job["state"] = "failed"
        job["error"] = plan.get("why") or "unreleased"
        return public(job), 404

    job["state"] = "queued"
    job["error"] = plan.get("why") or "no proof fired"
    job["proof"] = ""
    job["tried"] = plan.get("tried") or []
    queue_needs(plan)
    log(f"queued {job['title']}: {job['error']}")
    out = public(job)
    out["tried"] = plan.get("tried") or []
    return out, 202


def yts_path(job: dict, tmdb: int, plan: dict) -> tuple[dict, int]:
    title = job.get("title") or plan.get("title") or ""
    year = str(job.get("year") or plan.get("year") or "")
    try:
        cands, imdb, meta = resolve(tmdb, title, year, job.get("rejected"))
    except Exception as e:
        job["state"] = "failed"
        job["error"] = f"resolve: {e}"
        return public(job), 502
    if not job.get("runtime") and meta.get("runtime"):
        job["runtime"] = int(meta["runtime"])
    if not job.get("want_lang") and meta.get("original_language"):
        job["want_lang"] = meta["original_language"]
    runtime = int(job.get("runtime") or 0)
    if not cands:
        job["state"] = "failed"
        job["error"] = ("no untried torrent" if job.get("rejected")
                        else "yts vanished between choose and grab")
        return public(job), 404

    # an exact IMDb match is already right; this catches a "sample"-only torrent and a
    # torrent named for something else
    named = [c for c in cands if verify.file_names_film(c["title"], title, year)]
    sized = [c for c in (named or cands) if verify.size_sane(c["size"], runtime)]
    pick = (sized or named or cands)[0]

    job["cam"] = bool(pick.get("cam"))
    if pick.get("below_floor"):
        log(f"{pick['title']} [{pick['quality']}] only {pick['seeds']} seed(s), "
            f"below floor {CFG['min_seeds']}")

    # an upgrade pass that only finds another cam keeps the file it already has
    if job["cam"] and job.get("upgrade") and not job.get("force"):
        have = in_library(tmdb)
        if have:
            job["state"] = "present"
            job["path"] = have
            job["progress"] = 1.0
            job["error"] = "cam still the best available"
            return public(job), 200

    need = int(pick["size"] * 1.5) + int(CFG["min_free_gb"]) * (1024 ** 3)
    have_free = free_bytes(Path(CFG["staging_root"]))
    if have_free and have_free < need:
        job["state"] = "failed"
        job["error"] = f"low disk: {human(have_free)} free, need {human(need)}"
        return public(job), 507

    base = safe_name(re.sub(r"\s*\((19|20)\d{2}\)\s*$", "", pick["title"] or "").strip()
                     or pick["title"] or "untitled")
    stem = f"{base} ({pick['year']})" if pick["year"] else base
    job["dir"] = stem if CFG["client"] == "aria2" else ""
    job["magnet_file"] = str(Path(CFG["staging_root"]) / (stem + ".magnet.txt"))
    staging = job_dir(job) if job["dir"] else Path(CFG["staging_root"])
    staging.mkdir(parents=True, exist_ok=True)

    job.update(
        title=pick["title"],
        year=str(pick["year"] or ""),
        imdb=imdb or "",
        quality=pick["quality"],
        size=pick["size"],
        magnet=pick["magnet"],
        source="yts",
        expected=0,
        fetch_direct=pick["magnet"],
    )
    link = pick["url"] or pick["magnet"]

    if CFG["client"] == "aria2":
        try:
            job["gid"] = ARIA.add(link, staging)
        except Exception as e:
            job["state"] = "failed"
            job["error"] = f"aria2: {e}"
            return public(job), 502
        job["state"] = "downloading"
        log(f"queued {pick['title']} [{pick['quality']}]"
            + (" [cam]" if job["cam"] else "") + f" {human(pick['size'])}")
        return public(job), 202

    if CFG["client"] == "fdm":
        Path(job["magnet_file"]).write_text(pick["magnet"], encoding="utf-8")
        exe = CFG["fdm_path"]
        try:
            subprocess.Popen([exe, pick["magnet"]], close_fds=True)
        except Exception as e:
            job["state"] = "failed"
            job["error"] = f"fdm launch: {e}"
            return public(job), 502
        job["state"] = "handed_off"
        log(f"handed to FDM: {pick['title']} [{pick['quality']}] -> {staging}")
        return public(job), 202

    Path(job["magnet_file"]).write_text(pick["magnet"], encoding="utf-8")
    job["state"] = "handed_off"
    log(f"magnet ready: {pick['title']} [{pick['quality']}] -> {staging}")
    return public(job), 202


def provider_path(job: dict, plan: dict) -> tuple[dict, int]:
    ok, err, code = provider_start(job, plan)
    return public(job), code


def youtube_path(job: dict, plan: dict) -> tuple[dict, int]:
    if not CFG.get("allow_youtube") or not YTDLP:
        job["state"] = "failed"
        job["error"] = "youtube rung disabled or yt-dlp not found"
        return public(job), 500

    job["dir"] = safe_name(f"{job['title']} ({job['year']})" if job["year"] else job["title"])
    job["dir"] = job["dir"] or job["id"]
    job["video_id"] = plan.get("video_id") or ""
    job["proof"] = plan.get("proof") or ""
    job["quality"] = plan.get("quality") or "auto"
    job["expected"] = int(plan.get("seconds") or 0)
    job["fetch_direct"] = "https://www.youtube.com/watch?v=" + job["video_id"]

    if job["video_id"] and job["proof"] in CATEGORICAL:
        try:
            if blacklist_remove(BLACKLIST_PATH, job["video_id"]):
                log(f"unblacklisted {job['video_id']} ({job['proof']} overrides)")
        except OSError as e:
            log(f"unblacklist failed: {e}")

    have = free_bytes(Path(CFG["staging_root"]))
    if have and have < int(CFG["min_free_gb"]) * (1024 ** 3):
        job["state"] = "failed"
        job["error"] = f"low disk: {human(have)} free"
        return public(job), 507

    log(f"youtube fetch {job['title']} {job['video_id']} ({job['proof']})")
    try:
        yt_fetch_start(job, job["video_id"], int(plan.get("seconds") or 0))
    except Exception as e:
        job["state"] = "failed"
        job["error"] = f"yt-dlp start: {e}"
        return public(job), 502
    return public(job), 202


def provider_start(job: dict, plan: dict) -> tuple[bool, str, int]:
    """Start a provider fetch. Shared by the HTTP rung and the cam upgrade sweep."""
    if not CFG.get("allow_provider") or not FFMPEG:
        job["state"] = "failed"
        job["error"] = "provider rung disabled or ffmpeg not found"
        return False, job["error"], 500

    job["cam"] = bool(plan.get("cam"))

    if job["cam"] and not job.get("force") and not job.get("upgrade"):
        have = in_library(job["tmdb"])
        if have and is_cam_copy(job["tmdb"]):
            job["state"] = "present"
            job["path"] = have
            job["progress"] = 1.0
            job["error"] = "cam already filed, no better source"
            return False, job["error"], 200

    job["dir"] = safe_name(f"{job['title']} ({job['year']})" if job["year"] else job["title"])
    job["dir"] = job["dir"] or job["id"]
    job["quality"] = plan.get("quality") or "auto"
    job["expected"] = int(plan.get("seconds") or 0)
    job["fetch_direct"] = plan.get("direct") or plan.get("url") or ""

    have = free_bytes(Path(CFG["staging_root"]))
    if have and have < int(CFG["min_free_gb"]) * (1024 ** 3):
        job["state"] = "failed"
        job["error"] = f"low disk: {human(have)} free"
        return False, job["error"], 507

    log(f"provider fetch {job['title']} via {plan.get('label')} "
        f"({plan.get('seconds')}s, cam={plan.get('cam')}, verified={plan.get('verified')})")
    try:
        fetch_start(job, plan["url"], int(plan.get("seconds") or 0), "hls")
    except Exception as e:
        job["state"] = "failed"
        job["error"] = f"ffmpeg start: {e}"
        return False, job["error"], 502
    return True, "", 202


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

PAGE = """<!doctype html><meta charset=utf-8><title>RUIN grab</title>
<style>
body{background:#0b0b0d;color:#ddd;font:14px system-ui;margin:0;padding:24px}
h1{font-size:16px;letter-spacing:.12em;text-transform:uppercase;color:#888;margin:0 0 6px}
.n{color:#666;font-size:12px;margin-bottom:18px}
.n button{margin-left:8px}
table{width:100%;border-collapse:collapse}
td{padding:9px 8px;border-bottom:1px solid #1b1b20;vertical-align:top}
.t{color:#fff;font-weight:600}
.s{color:#777;font-size:12px}
.mono{font:11px ui-monospace;color:#8a7d55;word-break:break-all}
.bar{height:5px;background:#1b1b20;border-radius:3px;overflow:hidden;margin-top:6px}
.bar>i{display:block;height:100%;background:#c8a24a}
.done{color:#6cc07a}.fail{color:#d66}.moving,.handed_off,.fetching,.queued{color:#c8a24a}
.cam{color:#d0a;font-size:11px;letter-spacing:.1em}
.skipped{color:#7a7a86}
button{background:#1b1b20;color:#bbb;border:1px solid #2b2b32;border-radius:4px;padding:4px 9px;cursor:pointer;font-size:12px}
button:hover{color:#fff;border-color:#444}
</style><h1>RUIN grab</h1>
<div class=n>mode: __MODE__<button onclick="toggleAll()" id=tg>show finished</button><button onclick="clearDone()">clear finished</button></div>
<table id=rows></table>
<script>
const TERMINAL = ['done','failed','cancelled','wrong','present','skipped'];
let all = false;
async function tick(){
  const r = await fetch('/queue' + (all ? '?all=1' : ''));
  const rows = await r.json();
  document.getElementById('rows').innerHTML = rows.map(j=>{
    const cls = j.state==='done'?'done':(j.state==='failed'||j.state==='wrong')?'fail':(j.state==='skipped'?'skipped':'');
    const pct = j.state==='downloading'||j.state==='fetching';
    const end = TERMINAL.includes(j.state)
      ? `<button onclick="fetch('/requeue?id=${j.id}',{method:'POST'}).then(tick)">retry</button>`
      : `<button onclick="fetch('/cancel?id=${j.id}',{method:'POST'}).then(tick)">x</button>`;
    const wrong = j.state==='done' ? `<button onclick="fetch('/wrong?id=${j.id}&video=${j.video_id||''}',{method:'POST'}).then(tick)">wrong file</button>` : '';
    return `<tr><td><div class="t">${j.title||'…'} ${j.year?('('+j.year+')'):''}</div>
    <div class="s">tmdb ${j.tmdb} · ${j.quality} · ${j.size_h}${j.source?(' · '+j.source):''}${j.proof?(' · '+j.proof):''}${j.cam?' · <span class=cam>CAM</span>':''}</div>
    <div class="s ${cls}">${j.state}${j.speed_h?(' · '+j.speed_h):''}${j.error?(' · '+j.error):''}</div>
    ${pct?`<div class="bar"><i style="width:${j.progress_pct}%"></i></div>`:''}
    ${j.state==='handed_off'?`<div class="mono">save to: ${j.staging}</div>`:''}
    ${j.video_id?`<div class="mono">yt ${j.video_id}</div>`:''}
    ${j.magnet?`<div class="mono" title="${j.magnet}">${j.magnet.slice(0,90)}…</div>`:''}
    </td><td style="width:1%">${wrong}${end}</td></tr>`;
  }).join('') || '<tr><td class="s">idle</td></tr>';
  document.getElementById('tg').textContent = all ? 'hide finished' : 'show finished';
}
function toggleAll(){ all = !all; tick(); }
async function clearDone(){ await fetch('/clear',{method:'POST'}); tick(); }
setInterval(tick, 3000); tick();
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
            return self._send(
                200, PAGE.replace("__MODE__", CFG["client"]).encode(), "text/html; charset=utf-8"
            )
        if u.path == "/health":
            return self._json({"ok": True, "version": VERSION, "mode": CFG["client"],
                               "provider": CFG["allow_provider"],
                               "youtube": CFG["allow_youtube"],
                               "ffmpeg": bool(FFMPEG), "ytdlp": bool(YTDLP),
                               "whisper": bool(WHISPER), "lang_check": bool(CFG["lang_check"]),
                               "max_audio_tracks": CFG["max_audio_tracks"],
                               "lang_max_probe": CFG["lang_max_probe"],
                               "stale_handoff_min": CFG["stale_handoff_min"],
                               "cam_retry_hours": CFG["cam_retry_hours"],
                               "min_seeds": CFG["min_seeds"]})
        if u.path == "/queue":
            show_all = (q.get("all") or ["0"])[0] not in ("0", "")
            return self._json(snapshot(show_all))
        if u.path == "/needs":
            return self._json(needs_rows())
        if u.path == "/skips":
            with SKIPS_LOCK:
                return self._json(dict(SKIPS))
        if u.path == "/dry":
            try:
                tmdb = int((q.get("tmdb") or [""])[0])
            except ValueError:
                return self._json({"error": "tmdb required"}, 400)
            try:
                plan = source.choose(str(tmdb))
            except Exception as e:
                return self._json({"error": str(e)}, 502)
            return self._json(plan)
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)

        if u.path == "/cancel":
            jid = (q.get("id") or [""])[0]
            with JOBS_LOCK:
                job = JOBS.get(jid)
            if not job:
                return self._json({"error": "no such job"}, 404)
            if job["state"] in TERMINAL and job["state"] != "cancelled":
                return self._json({"ok": True, "state": job["state"], "kept": True})
            if job["gid"] and ARIA:
                ARIA.delete(job["gid"])
            kill_tree(FETCHERS.pop(job["id"], None))
            job["state"] = "cancelled"
            add_skip(job["tmdb"], "cancelled")
            log(f"cancel: {job['title'] or job['tmdb']}")
            return self._json({"ok": True})

        if u.path == "/skip":
            raw = (q.get("tmdb") or [""])[0].strip()
            if not raw.isdigit():
                return self._json({"error": "tmdb required"}, 400)
            tmdb = int(raw)
            add_skip(tmdb, (q.get("why") or ["by hand"])[0])
            job = find_job(tmdb)
            if job is not None and job["state"] not in BUSY:
                job["state"] = "skipped"
                job["error"] = "skipped"
            log(f"skip: {tmdb}")
            return self._json({"ok": True, "tmdb": tmdb, "skipped": True})

        if u.path == "/unskip":
            raw = (q.get("tmdb") or [""])[0].strip()
            if not raw.isdigit():
                return self._json({"error": "tmdb required"}, 400)
            tmdb = int(raw)
            had = drop_skip(tmdb)
            job = find_job(tmdb)
            if job is not None and job["state"] == "skipped":
                return self._rechoose(job)
            log(f"unskip: {tmdb}")
            return self._json({"ok": True, "tmdb": tmdb, "cleared": had})

        if u.path == "/clear":
            with JOBS_LOCK:
                drop = [k for k, j in JOBS.items() if j["state"] in TERMINAL]
                for k in drop:
                    JOBS.pop(k, None)
            log(f"cleared {len(drop)} finished")
            return self._json({"ok": True, "cleared": len(drop)})

        if u.path == "/requeue":
            jid = (q.get("id") or [""])[0]
            raw = (q.get("tmdb") or [""])[0].strip()
            with JOBS_LOCK:
                job = JOBS.get(jid) if jid else None
            if not job and raw.isdigit():
                job = find_job(int(raw))
            if not job:
                return self._json({"error": "no such job"}, 404)
            drop_skip(job["tmdb"])
            return self._rechoose(job)

        if u.path == "/forgive":
            vid = (q.get("video") or [""])[0]
            if not vid:
                return self._json({"error": "video required"}, 400)
            ok = blacklist_remove(BLACKLIST_PATH, vid, keep_sticky=False)
            log(f"forgive: {vid} ({'cleared' if ok else 'not present'})")
            return self._json({"ok": True, "cleared": ok})

        if u.path == "/wrong":
            jid = (q.get("id") or [""])[0]
            vid = (q.get("video") or [""])[0]
            raw_tmdb = (q.get("tmdb") or [""])[0].strip()
            with JOBS_LOCK:
                job = JOBS.get(jid) if jid else None
            if not job and raw_tmdb.isdigit():
                job = find_job(int(raw_tmdb))
            if not job and not raw_tmdb.isdigit():
                return self._json({"error": "need a job id or a tmdb id"}, 400)

            tmdb = int(raw_tmdb) if raw_tmdb.isdigit() else int(job["tmdb"])
            prov = prov_read(tmdb)
            if not vid:
                vid = (job or {}).get("video_id") or prov.get("video_id") or ""

            if job:
                kill_tree(FETCHERS.pop(job["id"], None))
                if job.get("gid") and ARIA:
                    ARIA.delete(job["gid"])
                    job["gid"] = ""

            path = (job or {}).get("path") or in_library(tmdb)
            removed = ""
            if path and Path(path).exists():
                try:
                    Path(path).unlink()
                    removed = path
                except OSError as e:
                    return self._json({"error": f"delete: {e}"}, 500)
            if vid:
                blacklist_add(BLACKLIST_PATH, vid, "wrong file", sticky=True)
            prov_drop(tmdb)
            drop_skip(tmdb)

            if job:
                job["state"] = "wrong"
                job["error"] = "marked wrong" + (f", deleted {Path(path).name}" if removed else "")
            if removed:
                threading.Thread(target=poke_scan, daemon=True).start()
            log(f"wrong: tmdb {tmdb} {vid} -> deleted {removed or 'nothing'} (sticky)")
            return self._json({"ok": True, "deleted": removed, "blacklisted": bool(vid),
                               "requeue": {"tmdb": tmdb}})

        if u.path != "/grab":
            return self._json({"error": "not found"}, 404)

        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json({"error": "bad json"}, 400)
        try:
            tmdb = int(body.get("tmdb"))
        except (TypeError, ValueError):
            return self._json({"error": "tmdb required"}, 400)

        force = bool(body.get("force"))
        with grab_lock_for(tmdb):
            existing = find_job(tmdb)

            if force:
                drop_skip(tmdb)
                if existing:
                    log(f"force re-run: {tmdb}")
                    return self._rechoose(existing, force=True)

            if not force:
                have = in_library(tmdb)
                if have and not is_cam_copy(tmdb):
                    if existing:
                        if existing["state"] not in TERMINAL and existing["state"] != "queued":
                            return self._json(public(existing), 202)
                        existing.update(state="present", path=have, progress=1.0,
                                        source="library", error="already in library")
                        return self._json(public(existing), 200)
                    job = new_job(tmdb)
                    job["state"] = "present"
                    job["path"] = have
                    job["progress"] = 1.0
                    job["source"] = "library"
                    job["error"] = "already in library"
                    with JOBS_LOCK:
                        JOBS[job["id"]] = job
                    log(f"present: {tmdb} {Path(have).name}")
                    return self._json(public(job), 200)

                if is_skipped(tmdb):
                    return self._skipped(tmdb, existing)

                if existing:
                    log(f"held: {tmdb} ({existing['state']})")
                    return self._json(public(existing), 202)

            job = new_job(tmdb)
            job["force"] = force
            with JOBS_LOCK:
                JOBS[job["id"]] = job

            try:
                plan = source.choose(str(tmdb))
            except Exception as e:
                job["state"] = "failed"
                job["error"] = f"choose: {e}"
                return self._json(public(job), 502)

            job.update(title=plan.get("title") or "", year=str(plan.get("year") or ""),
                       imdb=plan.get("imdb") or "", rung=plan.get("rung") or "",
                       source=plan.get("rung") or "", runtime=int(plan.get("runtime") or 0))
            out, code = dispatch(job, plan)
            return self._json(out, code)

    def _skipped(self, tmdb: int, existing: dict | None):
        if existing is not None and existing["state"] in BUSY:
            return self._json(public(existing), 202)
        if existing is None:
            existing = new_job(tmdb)
            with JOBS_LOCK:
                JOBS[existing["id"]] = existing
        existing["state"] = "skipped"
        existing["error"] = "skipped"
        log(f"skipped: {tmdb}")
        return self._json(public(existing), 200)

    def _rechoose(self, job: dict, force: bool = False):
        kill_tree(FETCHERS.pop(job["id"], None))
        if job.get("gid") and ARIA:
            ARIA.delete(job["gid"])
            job["gid"] = ""
        job["state"] = "resolving"
        job["error"] = ""
        job["proof"] = ""
        job["tried"] = []
        job["attempts"] = 0
        job["progress"] = 0.0
        job["upgrade"] = False
        job["force"] = bool(force)
        job["verify_fails"] = 0
        job["rejected"] = []
        try:
            plan = source.choose(str(job["tmdb"]))
        except Exception as e:
            job["state"] = "failed"
            job["error"] = f"choose: {e}"
            return self._json(public(job), 502)
        job.update(title=plan.get("title") or job["title"],
                   year=str(plan.get("year") or job["year"]),
                   imdb=plan.get("imdb") or job["imdb"],
                   rung=plan.get("rung") or "", source=plan.get("rung") or "",
                   runtime=int(plan.get("runtime") or job.get("runtime") or 0))
        out, code = dispatch(job, plan)
        return self._json(out, code)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"

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
                    if "allow_youtube" not in loaded and "yt_fallback" in loaded:
                        cfg["allow_youtube"] = bool(loaded["yt_fallback"])
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
        cfg["stale_handoff_min"] = max(0, int(cfg.get("stale_handoff_min") or 0))
    except (TypeError, ValueError):
        cfg["stale_handoff_min"] = 120
    try:
        cfg["cam_retry_hours"] = min(168, max(0, int(cfg.get("cam_retry_hours") or 0)))
    except (TypeError, ValueError):
        cfg["cam_retry_hours"] = 12
    try:
        cfg["min_seeds"] = max(0, int(cfg.get("min_seeds") or 0))
    except (TypeError, ValueError):
        cfg["min_seeds"] = 3
    try:
        cfg["max_audio_tracks"] = min(8, max(1, int(cfg.get("max_audio_tracks") or 4)))
    except (TypeError, ValueError):
        cfg["max_audio_tracks"] = 4
    try:
        cfg["lang_windows"] = min(7, max(1, int(cfg.get("lang_windows") or 5)))
    except (TypeError, ValueError):
        cfg["lang_windows"] = 5
    try:
        cfg["lang_window_s"] = min(60, max(10, int(cfg.get("lang_window_s") or 30)))
    except (TypeError, ValueError):
        cfg["lang_window_s"] = 30
    try:
        cfg["lang_min_p"] = min(1.0, max(0.0, float(cfg.get("lang_min_p") or 0.4)))
    except (TypeError, ValueError):
        cfg["lang_min_p"] = 0.4
    try:
        cfg["lang_min_agree"] = min(7, max(1, int(cfg.get("lang_min_agree") or 2)))
    except (TypeError, ValueError):
        cfg["lang_min_agree"] = 2
    try:
        cfg["lang_max_probe"] = min(8, max(1, int(cfg.get("lang_max_probe") or 3)))
    except (TypeError, ValueError):
        cfg["lang_max_probe"] = 3
    return cfg


def find_ffmpeg(cfg: dict) -> str:
    exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    candidate = os.path.join(cfg.get("ffmpeg_dir") or "", exe_name)
    if cfg.get("ffmpeg_dir") and os.path.isfile(candidate):
        return candidate
    return shutil.which("ffmpeg") or ""


def find_ytdlp(cfg: dict) -> str:
    candidate = cfg.get("ytdlp_path") or ""
    if candidate and os.path.isfile(candidate):
        return candidate
    return shutil.which("yt-dlp") or shutil.which("yt-dlp.exe") or ""


def find_whisper(cfg: dict) -> str:
    candidate = cfg.get("whisper_path") or ""
    if candidate and os.path.isfile(candidate):
        return candidate
    return shutil.which("whisper-cli") or shutil.which("whisper-cli.exe") or ""


def main() -> None:
    global CFG, ARIA, FFMPEG, YTDLP, WHISPER
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="grab.json")
    ap.add_argument("--client", choices=["aria2", "fdm", "drop"])
    args = ap.parse_args()
    CFG = load_config(args.config)
    if args.client:
        CFG["client"] = args.client

    load_skips()

    FFMPEG = find_ffmpeg(CFG)
    if not FFMPEG:
        log("warning: ffmpeg was not found; probing, transcoding, and provider rung unavailable")

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

    threading.Thread(target=cam_loop, daemon=True).start()

    if CFG["allow_youtube"]:
        YTDLP = find_ytdlp(CFG)
        if not YTDLP:
            log("warning: allow_youtube is on but yt-dlp was not found; rung disabled")
            CFG["allow_youtube"] = False

    if CFG["allow_provider"]:
        if FFMPEG:
            log(f"provider rung on, ffmpeg {FFMPEG}")
        else:
            log("warning: allow_provider is on but ffmpeg was not found; rung disabled")
            CFG["allow_provider"] = False

    if CFG["lang_check"]:
        WHISPER = find_whisper(CFG)
        model = str(CFG.get("whisper_model") or "")
        if not WHISPER or not model or not Path(model).is_file():
            log("warning: lang_check is on but whisper-cli or the model is missing; "
                "audio language will fall back to tags")
            CFG["lang_check"] = False
        else:
            log(f"audio language proof on, whisper {WHISPER}, "
                f"up to {CFG['lang_windows']}x{CFG['lang_window_s']}s windows, "
                f"agree>={CFG['lang_min_agree']}, max {CFG['max_audio_tracks']} track(s), "
                f"{CFG['lang_max_probe']} probed")

    if YTDLP or FFMPEG:
        threading.Thread(target=fetch_loop, daemon=True).start()

    bind = CFG["bind"]
    srv = Server((bind, int(CFG["port"])), Handler)
    log(f"grab {VERSION} on http://{bind}:{CFG['port']} mode={CFG['client']}")
    if bind == "0.0.0.0":
        log("listening on every interface")
    log(f"library {CFG['library_root']}")
    log(f"staging {CFG['staging_root']}")
    log(f"watch depth {CFG['watch_depth']}")
    log(f"stale hand-off limit {CFG['stale_handoff_min']} min")
    log(f"cam retry {CFG['cam_retry_hours']} h")
    log(f"min seeds {CFG['min_seeds']}")
    with SKIPS_LOCK:
        log(f"skips {len(SKIPS)}")
    for r in watch_roots():
        log(f"watching {r}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        STOP.set()
        log("stopped")


if __name__ == "__main__":
    main()
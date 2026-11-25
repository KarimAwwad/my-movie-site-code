#!/usr/bin/env python3
"""
grab.py — RUIN.TO acquisition daemon (port 8789)

Resolves a TMDB id to an IMDb id, finds a matching YTS torrent, and gets the video into
your library folder under a name library.py can match:

    <Title> (Year) [tmdb-<id>].mp4

Three client modes, set "client" in grab.json:

  aria2   Fully automatic. Single .exe, no install. Real progress and completion detection.
  fdm     Hands the magnet to Free Download Manager. FDM pops its own window and uses its own
          default folder, so the file lands loose in the staging root and is adopted by title.
  drop    Nothing is launched. The API returns the magnet; the watcher files whatever lands.

In fdm and drop modes a watcher thread files new videos automatically, so you never rename
or move anything by hand. In aria2 mode the job gets its own folder, because aria2 honours
the path it is given and the folder then doubles as proof of whose file it is.

watch_roots is the list of EXTRA folders the watcher looks in, on top of the staging root.
watch_depth bounds how far each root is walked, since a deep sweep of a whole drive is wasted work.

Adoption is strict on purpose. A file is only claimed when every meaningful title word is present,
or when its size is within tolerance of the torrent, and never while the job's own staging folder
already holds a video. A loose "only one job, take it" rule filed a 3-minute Valorant clip as
Insidious Chapter 3 and then closed the job, orphaning the real film. A file also has to be within
10% of the expected size, so a stalled download cannot be filed half-written.

A torrent with a root folder of its own (every YTS release has one) puts the video one level down
inside staging, next to residue like www.YTS.AM.jpg. Once the video has been taken out, that whole
folder goes: it is staging, not library content, so nothing of yours is lost by removing it.

"bind" is the interface the daemon listens on and defaults to 0.0.0.0. It is separate from
"host" on purpose: the site is reached through a hostname that is not loopback, so a daemon
bound to 127.0.0.1 refuses every request from the page even though it answers in a browser tab.

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
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.3.5"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ruin-grab/" + VERSION
VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".ts", ".m2ts"}
QUALITY_RANK = {"2160p": 4, "1080p": 3, "720p": 2, "480p": 1}
YTS_HOSTS = ("yts.bz", "yts.mx", "yts.lt", "yts.rs", "yts.am")
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
# words too common to prove anything when matching a file to a waiting job
STOP_TOKENS = {
    "the", "and", "of", "a", "an", "in", "on", "to", "for", "with", "part", "chapter",
    "vol", "aka", "yts", "yify", "x264", "x265", "aac", "web", "webrip", "bluray",
    "brrip", "bdrip", "hdtv", "remux", "proper", "repack", "extended", "unrated",
    "1080p", "720p", "2160p", "480p",
}
# a file far smaller than the torrent is not the film: a 3-minute clip must not pass for a 1.4 GB movie
MIN_SIZE_RATIO = 0.5

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
}

STOP = threading.Event()
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
SEEN: dict[str, int] = {}
CFG: dict = {}
ARIA = None


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #

def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


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

def tmdb_imdb(tmdb_id: int) -> str | None:
    url = (
        f"https://api.themoviedb.org/3/movie/{int(tmdb_id)}/external_ids"
        f"?api_key={CFG['tmdb_key']}"
    )
    data = http_json(url)
    imdb = (data or {}).get("imdb_id")
    return imdb if imdb and imdb.startswith("tt") else None


def yts_candidates(imdb_id: str) -> list[dict]:
    for host in YTS_HOSTS:
        try:
            url = f"https://{host}/api/v2/list_movies.json?query_term={imdb_id}&limit=5"
            data = http_json(url)
        except Exception as e:
            log(f"yts {host}: {e}")
            continue
        movies = ((data or {}).get("data") or {}).get("movies") or []
        out: list[dict] = []
        for m in movies:
            if (m.get("imdb_code") or "") != imdb_id:
                continue
            for t in m.get("torrents") or []:
                h = (t.get("hash") or "").lower()
                if not h:
                    continue
                dn = f"{m.get('title_long') or m.get('title') or 'movie'} [{t.get('quality')}] [YTS]"
                magnet = "magnet:?xt=urn:btih:" + h + "&dn=" + urllib.parse.quote(dn)
                for tr in TRACKERS:
                    magnet += "&tr=" + urllib.parse.quote(tr)
                out.append(
                    {
                        "quality": t.get("quality") or "?",
                        "size": int(t.get("size_bytes") or 0),
                        "seeds": int(t.get("seeds") or 0),
                        "peers": int(t.get("peers") or 0),
                        "hash": h,
                        "url": t.get("url") or "",
                        "magnet": magnet,
                        "title": m.get("title_long") or m.get("title") or "",
                        "year": m.get("year"),
                    }
                )
        if out:
            return out
    return []


def rank(cands: list[dict]) -> list[dict]:
    allow = QUALITY_RANK.get(CFG["max_quality"], 3)
    min_seeds = int(CFG["min_seeds"])
    fit = [
        c
        for c in cands
        if c["seeds"] >= min_seeds and QUALITY_RANK.get(c["quality"], 0) <= allow
    ]
    if not fit:
        fit = [c for c in cands if QUALITY_RANK.get(c["quality"], 0) <= allow] or list(cands)
    fit.sort(
        key=lambda c: (QUALITY_RANK.get(c["quality"], 0), c["seeds"], c["size"]),
        reverse=True,
    )
    return fit


def resolve(tmdb_id: int) -> tuple[list[dict], str | None]:
    imdb = tmdb_imdb(tmdb_id)
    if not imdb:
        return [], None
    return rank(yts_candidates(imdb)), imdb


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
    }


def job_dir(job: dict) -> Path:
    """aria2's own working folder, named after the film."""
    return Path(CFG["staging_root"]) / (job.get("dir") or job["id"])


def public(j: dict) -> dict:
    d = dict(j)
    d["size_h"] = human(j["size"]) if j["size"] else ""
    d["speed_h"] = human(j["speed"]) + "/s" if j["speed"] else ""
    d["progress_pct"] = round(j["progress"] * 100, 1)
    # FDM and drop write loose into the staging root, so there is no per-job folder to report
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
    # YTS title_long already ends in the year ("The Matrix (1999)"), and the year is appended again
    # below, which produced "The Matrix (1999) (1999) [tmdb-603]". Drop a trailing year first.
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


def finalize(job: dict, video: Path) -> None:
    try:
        dest = file_into_library(video, job["tmdb"], job["title"], job["year"])
    except Exception as e:
        job["state"] = "failed"
        job["error"] = f"move: {e}"
        return
    job["path"] = str(dest)
    job["progress"] = 1.0
    job["state"] = "done"
    try:
        log(f"filed {dest.name} ({human(dest.stat().st_size)})")
    except OSError:
        log(f"filed {dest.name}")
    poke_scan()


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
    # a file adopted from elsewhere closes the job while a downloader may still be writing into this folder;
    # removing it there loses the film, so leave anything holding a video alone
    if find_video(folder):
        return
    shutil.rmtree(folder, ignore_errors=True)


def clear_source_folder(video: Path) -> None:
    """Remove the folder the video came out of.

    Torrents carry a root folder of their own, so a finished download leaves the video one level down in
    staging beside residue like www.YTS.AM.jpg. Staging is working space, not library content, so that whole
    folder goes once the video has been moved out. A folder outside staging is a real watch root and is only
    removed when nothing at all is left in it."""
    parent = video.parent
    try:
        staging = Path(CFG["staging_root"]).resolve()
        par = parent.resolve()
    except OSError:
        return
    if par == staging:
        return                                    # the file was loose in staging: nothing to clean
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
            job["state"] = "moving"
            d = job_dir(job)
            video = find_video(d)
            if video:
                finalize(job, video)
                clear_source_folder(video)
                cleanup_staging(job)
            else:
                job["state"] = "failed"
                job["error"] = "no video after download"
            ARIA.delete(job["gid"])
        elif st.get("status") == "error":
            job["state"] = "failed"
            job["error"] = st.get("errorMessage") or "aria2 error"


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
    # "The" and "of" alone must not tie a file to a job, but an all-stopword title still needs something
    return meaningful or raw


def adoptable(video: Path, size: int) -> dict | None:
    """Which waiting job does this file belong to?

    FDM can save anywhere, so a file is only claimed when it actually looks like the job's film:
    every meaningful title word is present, or the size is within tolerance. A job whose own
    staging folder already holds a video is left to the deterministic path in watcher_loop."""
    with JOBS_LOCK:
        pending = [j for j in JOBS.values() if j["state"] == "handed_off"]
    if not pending:
        return None

    # the job's own folder is authoritative: if a video is sitting there, this file is somebody else's.
    # only near-complete files too: a stalled swarm freezes the size and would otherwise look finished
    free = [j for j in pending
            if not find_video(job_dir(j))
            and (not j["size"] or size >= j["size"] * 0.9)]

    have = name_tokens(video.stem)
    for job in free:
        want = name_tokens(job["title"] or "")
        if want and want <= have:
            return job
    for job in free:
        if not job["size"]:
            continue
        if size < job["size"] * MIN_SIZE_RATIO:
            continue
        if abs(size - job["size"]) <= job["size"] * 0.35:
            return job
    return None


def scan_roots(min_size: int) -> None:
    lib = Path(CFG["library_root"]).resolve()
    # FDM drops files at the root of its default folder, so a deep recursive walk of a whole drive
    # is wasted work. watch_depth bounds it; files sitting at the root are still seen.
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
                # two sightings with the same size = it has stopped growing
                if SEEN.get(str(p)) != size:
                    SEEN[str(p)] = size
                    continue
                job = adoptable(p, size)
                if not job:
                    continue
                job["state"] = "moving"
                finalize(job, p)
                SEEN.pop(str(p), None)
                clear_source_folder(p)
                cleanup_staging(job)


def watcher_loop() -> None:
    min_size = int(CFG["min_file_mb"]) * 1024 * 1024
    while not STOP.is_set():
        try:
            # 1. the job's own folder (aria2, and FDM when it honours the path)
            with JOBS_LOCK:
                handed = [j for j in JOBS.values() if j["state"] == "handed_off"]
            for job in handed:
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
                job["state"] = "moving"
                finalize(job, v)
                clear_source_folder(v)
                cleanup_staging(job)

            # 2. every other place a file can land
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
button{background:#1b1b20;color:#bbb;border:1px solid #2b2b32;border-radius:4px;padding:4px 9px;cursor:pointer;font-size:12px}
button:hover{color:#fff;border-color:#444}
</style><h1>RUIN grab</h1><div class=n>mode: __MODE__</div><table id=rows></table>
<script>
async function tick(){
  const r = await fetch('/queue'); const rows = await r.json();
  document.getElementById('rows').innerHTML = rows.map(j=>{
    const cls = j.state==='done'?'done':j.state==='failed'?'fail':'';
    return `<tr><td><div class="t">${j.title||'…'} ${j.year?('('+j.year+')'):''}</div>
    <div class="s">tmdb ${j.tmdb} · ${j.quality} · ${j.size_h}</div>
    <div class="s ${cls}">${j.state}${j.speed_h?(' · '+j.speed_h):''}${j.error?(' · '+j.error):''}</div>
    ${j.state==='downloading'?`<div class="bar"><i style="width:${j.progress_pct}%"></i></div>`:''}
    ${j.state==='handed_off'?`<div class="mono">save to: ${j.staging}</div>`:''}
    ${j.magnet?`<div class="mono" title="${j.magnet}">${j.magnet.slice(0,90)}…</div>`:''}
    </td><td style="width:1%"><button onclick="fetch('/cancel?id=${j.id}',{method:'POST'})">x</button></td></tr>`;
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
            return self._send(
                200, PAGE.replace("__MODE__", CFG["client"]).encode(), "text/html; charset=utf-8"
            )
        if u.path == "/health":
            return self._json({"ok": True, "version": VERSION, "mode": CFG["client"]})
        if u.path == "/queue":
            return self._json(snapshot())
        if u.path == "/dry":
            try:
                tmdb = int((q.get("tmdb") or [""])[0])
            except ValueError:
                return self._json({"error": "tmdb required"}, 400)
            try:
                cands, imdb = resolve(tmdb)
            except Exception as e:
                return self._json({"error": str(e)}, 502)
            return self._json(
                {
                    "tmdb": tmdb,
                    "imdb": imdb,
                    "free": human(free_bytes(Path(CFG["staging_root"]))),
                    "candidates": [
                        dict(
                            (k, c[k]) for k in ("quality", "size", "seeds", "peers", "title", "year")
                        )
                        | {"size_h": human(c["size"])}
                        for c in cands
                    ],
                }
            )
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
            if job["gid"] and ARIA:
                ARIA.delete(job["gid"])
            job["state"] = "cancelled"
            return self._json({"ok": True})

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

        job = new_job(tmdb)
        with JOBS_LOCK:
            JOBS[job["id"]] = job

        try:
            cands, imdb = resolve(tmdb)
        except Exception as e:
            job["state"] = "failed"
            job["error"] = f"resolve: {e}"
            return self._json(public(job), 502)

        if not cands:
            job["state"] = "failed"
            job["error"] = "no yts torrent for this imdb id"
            return self._json(public(job), 404)

        pick = cands[0]
        need = int(pick["size"] * 1.5) + int(CFG["min_free_gb"]) * (1024 ** 3)
        have = free_bytes(Path(CFG["staging_root"]))
        if have and have < need:
            job["state"] = "failed"
            job["error"] = f"low disk: {human(have)} free, need {human(need)}"
            return self._json(public(job), 507)

        # The destination depends on the client. aria2 is handed its own folder and writes into it, so the
        # folder doubles as the proof that a file is this job's. FDM ignores the path and uses its default,
        # so there is nothing to create: the file lands loose in the staging root and is adopted by title.
        # The magnet is left behind either way, as a readable note rather than a folder.
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
        )
        link = pick["url"] or pick["magnet"]

        if CFG["client"] == "aria2":
            try:
                job["gid"] = ARIA.add(link, staging)
            except Exception as e:
                job["state"] = "failed"
                job["error"] = f"aria2: {e}"
                return self._json(public(job), 502)
            job["state"] = "downloading"
            log(f"queued {pick['title']} [{pick['quality']}] {human(pick['size'])}")
            return self._json(public(job), 202)

        if CFG["client"] == "fdm":
            Path(job["magnet_file"]).write_text(pick["magnet"], encoding="utf-8")
            exe = CFG["fdm_path"]
            try:
                subprocess.Popen([exe, pick["magnet"]], close_fds=True)
            except Exception as e:
                job["state"] = "failed"
                job["error"] = f"fdm launch: {e}"
                return self._json(public(job), 502)
            job["state"] = "handed_off"
            log(f"handed to FDM: {pick['title']} [{pick['quality']}] -> {staging}")
            return self._json(public(job), 202)

        Path(job["magnet_file"]).write_text(pick["magnet"], encoding="utf-8")
        job["state"] = "handed_off"
        log(f"magnet ready: {pick['title']} [{pick['quality']}] -> {staging}")
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
    # bind wins over host, and a loopback bind is corrected rather than silently refusing the site
    if not cfg.get("bind"):
        cfg["bind"] = "0.0.0.0"
    try:
        cfg["watch_depth"] = max(1, int(cfg.get("watch_depth") or 3))
    except (TypeError, ValueError):
        cfg["watch_depth"] = 3
    return cfg


def main() -> None:
    global CFG, ARIA
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="grab.json")
    ap.add_argument("--client", choices=["aria2", "fdm", "drop"])
    args = ap.parse_args()
    CFG = load_config(args.config)
    if args.client:
        CFG["client"] = args.client

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
    log(f"grab {VERSION} on http://{bind}:{CFG['port']} mode={CFG['client']}")
    if bind == "0.0.0.0":
        log("listening on every interface")
    log(f"library {CFG['library_root']}")
    log(f"staging {CFG['staging_root']}")
    log(f"watch depth {CFG['watch_depth']}")
    for r in watch_roots():
        log(f"watching {r}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        STOP.set()
        log("stopped")


if __name__ == "__main__":
    main()

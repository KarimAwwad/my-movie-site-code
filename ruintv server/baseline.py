#!/usr/bin/env python3
"""
baseline.py — read-only health check for RUIN.TO. Writes nothing, downloads nothing.

Run it from the folder that holds grab.json (ruintv server), because config is read
relative to the working directory.

    cd /d "D:\\my development work\\unfinished and finished development projects\\ruintv server"
    python baseline.py
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SITE = Path(r"D:\my development work\unfinished and finished development projects\movie site")
SERVER_DIR = Path(r"D:\my development work\unfinished and finished development projects\ruintv server")
RELAY_DIR = Path(r"D:\my development work\unfinished and finished development projects\ruin-stream")
UA = "Mozilla/5.0 ruin-baseline"
RESULTS: list[tuple[str, str, str]] = []


def mark(state: str, name: str, detail: str = "") -> None:
    RESULTS.append((state, name, detail))
    print(f"[{state:<4}] {name}" + (f"  -- {detail}" if detail else ""), flush=True)


def http(url: str, timeout: int = 20, headers: dict | None = None) -> tuple[int, str]:
    req_headers = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def getjson(url: str, timeout: int = 60, headers: dict | None = None):
    status, body = http(url, timeout, headers=headers)
    try:
        return status, json.loads(body)
    except Exception:
        return status, None


def tmdb_get(path: str, key: str, timeout: int = 20):
    key = str(key or "").strip()
    if not key:
        return 0, None
    url = f"https://api.themoviedb.org/3{path}"
    headers = {"Accept": "application/json"}
    if len(key) > 60 or key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    else:
        sep = "&" if "?" in url else "?"
        url += f"{sep}api_key={urllib.parse.quote(key, safe='')}"
    return getjson(url, timeout=timeout, headers=headers)


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--relay", type=int, default=8787)
    ap.add_argument("--library", type=int, default=8788)
    ap.add_argument("--grab", type=int, default=8789)
    args = ap.parse_args()

    relay = f"http://127.0.0.1:{args.relay}"
    library = f"http://127.0.0.1:{args.library}"
    grab = f"http://127.0.0.1:{args.grab}"

    print("RUIN.TO baseline\n" + "=" * 58 + "\n")

    # ---- A. layout
    print("A. layout")
    for label, path in (("movie site", SITE), ("ruintv server", SERVER_DIR), ("ruin-stream", RELAY_DIR)):
        mark("PASS" if path.is_dir() else "FAIL", f"{label} folder", str(path))
    for name in ("relay.py", "library.py", "grab.py", "server.py", "source.py", "proofs.py"):
        found = (SERVER_DIR / name).is_file() or (RELAY_DIR / name).is_file()
        mark("PASS" if found else "FAIL", f"{name} present")
    if (SERVER_DIR / "server.py").is_file():
        text = (SERVER_DIR / "server.py").read_text(encoding="utf-8", errors="replace")
        m = re.search(r'SITE_DIR\s*=\s*r?"([^"]+)"', text)
        got = Path(m.group(1)) if m else None
        ok = got is not None and got.resolve() == SITE.resolve()
        mark("PASS" if ok else "FAIL", "server.py SITE_DIR points at the movie site",
             str(got) if got else "SITE_DIR not found")

    # ---- B. files
    print("\nB. player files")
    player_ui = SITE / "player-ui.js"
    components = SITE / "components.js"
    script = SITE / "script.js"
    if player_ui.is_file():
        ui = player_ui.read_text(encoding="utf-8", errors="replace")
        mark("PASS", "player-ui.js exists", f"{len(ui)} bytes")
        for needle, why in (("bindPlayerControls", "overrides bindPlayerControls"),
                            ("pl-servers", "knows the source menu"),
                            ("pl-server-row", "builds server rows"),
                            ("embedbar", "wires the embed bar"),
                            ("pl-seekwrap", "drives the seek rail"),
                            ("pl-quality-label", "drives the quality readout")):
            mark("PASS" if needle in ui else "FAIL", f"player-ui.js {why}")
    else:
        mark("FAIL", "player-ui.js exists")

    if components.is_file() and script.is_file():
        emitted = set(re.findall(r'id="(pl-[a-z0-9-]+)"',
                                 components.read_text(encoding="utf-8", errors="replace")))
        emitted |= set(re.findall(r"pel\('(pl-[a-z0-9-]+)'\)",
                                  script.read_text(encoding="utf-8", errors="replace")))
        if player_ui.is_file():
            ui = player_ui.read_text(encoding="utf-8", errors="replace")
            missing = sorted(i for i in emitted if i not in ui)
            mark("PASS" if not missing else "FAIL", "every player id is known to player-ui.js",
                 "missing: " + ", ".join(missing) if missing else f"{len(emitted)} ids")

    # ---- C. config
    print("\nC. config")
    cfg_path = SERVER_DIR / "grab.json" if (SERVER_DIR / "grab.json").is_file() else Path("grab.json")
    grab_src_path = SERVER_DIR / "grab.py" if (SERVER_DIR / "grab.py").is_file() else Path("grab.py")
    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        src = grab_src_path.read_text(encoding="utf-8", errors="replace") if grab_src_path.is_file() else ""
        dead = [k for k in cfg if f'"{k}"' not in src and f"'{k}'" not in src]
        mark("PASS" if not dead else "FAIL", "grab.json keys are all read by grab.py",
             "dead: " + ", ".join(dead) if dead else f"{len(cfg)} keys")
        mark("PASS" if "allow_youtube" in cfg else "FAIL", "grab.json declares allow_youtube")
    else:
        mark("FAIL", "grab.json readable", f"checked {cfg_path}")

    # ---- D. services
    print("\nD. services")
    for name, base in (("relay", relay), ("library", library), ("grab", grab)):
        status, _body = http(f"{base}/health", 6)
        mark("PASS" if status == 200 else "FAIL", f"{name} /health", f"HTTP {status}")
    for port in (80, 8080):
        status, body = http(f"http://127.0.0.1:{port}/", 6)
        if status == 200 and "RUIN" in body:
            mark("PASS", "static site serves", f"port {port}")
            break
    else:
        mark("FAIL", "static site serves", "80 and 8080 both refused")

    # ---- E. CSP reachability
    print("\nE. CSP")
    if (SERVER_DIR / "server.py").is_file():
        text = (SERVER_DIR / "server.py").read_text(encoding="utf-8", errors="replace")
        ip = lan_ip()
        csp_ips = set(re.findall(r"http://(\d+\.\d+\.\d+\.\d+):87", text))
        mark("PASS" if ip and ip in csp_ips else "FAIL", "CSP allows this machine's LAN address",
             f"machine {ip or 'unknown'}, CSP has {', '.join(sorted(csp_ips)) or 'none'}")
        mark("PASS" if "localhost:8787" in text else "FAIL", "CSP allows localhost daemons")

    # ---- F. identity
    print("\nF. identity")
    tmdb_key = ""
    if cfg_path.is_file():
        tmdb_key = json.loads(cfg_path.read_text(encoding="utf-8-sig")).get("tmdb_key", "")

    status, res = getjson(f"{relay}/resolve?id=603", 70)
    if status == 200 and res and res.get("sources"):
        sources = res["sources"]
        mark("PASS", "relay resolves a known film (603)", f"{len(sources)} source(s), top {sources[0].get('label')}")
        url = urllib.parse.urljoin(relay + "/", sources[0].get("url") or "")
        m_status, manifest = http(url, 40)
        secs = sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", manifest)) if m_status == 200 else 0.0
        if m_status == 200 and not secs:
            child = next((l.strip() for l in manifest.splitlines() if l.strip() and not l.startswith("#")), "")
            if child:
                c_status, body = http(urllib.parse.urljoin(url, child), 40)
                if c_status == 200:
                    secs = sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", body))
        runtime = 0
        if tmdb_key:
            _, meta = tmdb_get("/movie/603", tmdb_key, 20)
            runtime = int((meta or {}).get("runtime") or 0) * 60
        if m_status != 200:
            mark("FAIL", "stream duration readable", f"manifest HTTP {m_status}")
        elif not secs:
            mark("FAIL", "stream duration readable", "no EXTINF in the playlist")
        elif not runtime:
            mark("SKIP", "stream duration vs TMDB runtime", f"stream {secs:.0f}s, no TMDB runtime")
        else:
            ratio = secs / runtime
            mark("PASS" if 0.88 <= ratio <= 1.12 else "FAIL", "stream duration vs TMDB runtime",
                 f"stream {secs:.0f}s vs {runtime}s ({ratio:.2f}x)")
    else:
        mark("FAIL", "relay resolves a known film (603)", f"HTTP {status}")

    status, tv = getjson(f"{relay}/resolve?id=1399", 70)
    if status == 200 and tv and tv.get("sources"):
        tv_url = urllib.parse.urljoin(relay + "/", tv["sources"][0].get("url") or "")
        _, manifest = http(tv_url, 40)
        secs = sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", manifest))
        if not secs:
            child = next((l.strip() for l in manifest.splitlines() if l.strip() and not l.startswith("#")), "")
            if child:
                _, body = http(urllib.parse.urljoin(tv_url, child), 40)
                secs = sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", body))
        movie_runtime = tv_runtime = 0
        if tmdb_key:
            _, m = tmdb_get("/movie/1399", tmdb_key, 20)
            movie_runtime = int((m or {}).get("runtime") or 0) * 60
            _, s = tmdb_get("/tv/1399", tmdb_key, 20)
            ep_list = (s or {}).get("episode_run_time") or []
            ep_mins = (ep_list[0] if ep_list else 0) or ((s or {}).get("last_episode_to_air") or {}).get("runtime") or 0
            tv_runtime = int(ep_mins) * 60
        if not secs:
            mark("FAIL", "relay is type-aware (series 1399)", "no EXTINF in playlist")
        elif not tv_runtime:
            mark("SKIP", "relay is type-aware (series 1399)", f"stream {secs:.0f}s, no TV episode runtime")
        else:
            closer = "movie" if (movie_runtime and abs(secs - movie_runtime) < abs(secs - tv_runtime)) else "tv"
            mark("PASS" if closer == "tv" else "FAIL", "relay is type-aware (series 1399)",
                 f"stream {secs:.0f}s, movie cut {movie_runtime}s, episode cut {tv_runtime}s -> {closer}")
    else:
        mark("FAIL", "relay resolves a series (1399)", f"HTTP {status}")

    # ---- G. library matching
    print("\nG. library matching")
    status, idx = getjson(f"{library}/index.json", 20)
    if status == 200 and isinstance(idx, dict):
        files = sum(len(v) for v in idx.values() if isinstance(v, list))
        mark("PASS" if files else "FAIL", "library index returns matches", f"{files} file(s), {len(idx)} id(s)")
        bad = [k for k in idx if not str(k).isdigit()]
        mark("PASS" if not bad else "FAIL", "every library key is a TMDB id", ", ".join(bad[:5]))
    else:
        mark("FAIL", "library index returns matches", f"HTTP {status}")

    # ---- H. player markup
    print("\nH. player markup")
    if components.is_file():
        text = components.read_text(encoding="utf-8", errors="replace")
        for need, why in (('class="pl-row"', "control row"),
                          ('class="pl-seekwrap"', "seek rail"),
                          ('class="pl-vol"', "volume wrapper"),
                          ('id="pl-servers"', "source menu"),
                          ('class="pl-spinner"', "spinner"),
                          ('class="pl-embedbar"', "embed bar")):
            mark("PASS" if need in text else "FAIL", f"components.js has {why}")

    passed = sum(1 for s, _, _ in RESULTS if s == "PASS")
    failed = sum(1 for s, _, _ in RESULTS if s == "FAIL")
    skipped = sum(1 for s, _, _ in RESULTS if s == "SKIP")
    print("\n" + "=" * 58)
    print(f"PASS {passed}   FAIL {failed}   SKIP {skipped}")
    print("Send this whole output back. FAIL lines are the work list.")


if __name__ == "__main__":
    main()
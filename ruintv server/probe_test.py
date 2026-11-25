#!/usr/bin/env python3
"""
probe_test.py — run the proof ladder against a real YouTube search.

Mirrors what the grabber sees: it searches, then scores every hit and prints the
verdict per hit. Nothing is downloaded.

    python probe_test.py 1505424          # unreleased film, trailers + a podcast: expect 0 accepts
    python probe_test.py 92060            # released short with real uploads: expect accepts
    python probe_test.py 92060 --id sOnqjkJTMaA

A hit rejected only as "blacklisted" is re-scored with the blacklist ignored and
both verdicts are printed, because a stale entry otherwise hides the real result.

The film dict is built from live TMDB with empty tmdb_video_keys, directors and
companies, so P1, P2, P5 and P6 cannot fire here. That is deliberate: the harness
targets P3, P4, P7 and the gates, which is where the misfilings live.

Exit code 0 = at least one accept, 1 = none.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import grab
from proofs import blacklist_load, evaluate, title_tokens

CFG = grab.load_config("grab.json")
grab.CFG = CFG


def yt_json(target: str, flat: bool) -> dict:
    exe = grab.find_ytdlp(CFG)
    if not exe:
        raise SystemExit("yt-dlp not found (set ytdlp_path in grab.json)")
    cmd = [exe, "-J", "--no-warnings", "--no-playlist"]
    if flat:
        cmd.append("--flat-playlist")
    cmd.append(target)
    proc = subprocess.run(cmd, capture_output=True, timeout=240)
    if proc.returncode != 0:
        raise SystemExit("yt-dlp: " + proc.stderr.decode("utf-8", "replace").strip()[-300:])
    return json.loads(proc.stdout.decode("utf-8", "replace"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tmdb", type=int)
    ap.add_argument("--id", default="")
    ap.add_argument("--count", type=int, default=8)
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    meta = grab.tmdb_meta(args.tmdb)
    if not meta.get("title"):
        raise SystemExit(f"TMDB {args.tmdb}: no title (bad id?)")
    imdb = grab.tmdb_imdb(args.tmdb) or ""
    runtime = int(meta["runtime"]) * 60
    film = {
        "title": meta["title"], "year": meta["year"], "runtime": runtime,
        "imdb": imdb, "tmdb": args.tmdb, "homepage": meta.get("homepage") or "",
        "directors": [], "companies": [], "tmdb_video_keys": [],
        "duration_agreement": 0,
    }
    bl_path = getattr(grab, "BLACKLIST_PATH", Path(__file__).with_name("youtube_blacklist.json"))
    black = blacklist_load(str(bl_path))

    print(f"film     {film['title']} ({film['year']})  runtime {runtime}s  imdb {imdb or '-'}")
    print(f"tokens   {title_tokens(film['title'])}")
    if runtime <= 0:
        print("warning  no TMDB runtime: flat 300s floor, title and kind gates only")

    if args.id:
        info = yt_json(f"https://www.youtube.com/watch?v={args.id}", False)
        entries = [{
            "id": args.id, "title": info.get("title") or "",
            "duration": info.get("duration") or 0,
            "channel": info.get("channel") or info.get("uploader") or "",
            "description": info.get("description") or "",
        }]
    else:
        query = f"{film['title']} {film['year']} full movie"
        data = yt_json(f"ytsearch{args.count}:{query}", True)
        entries = data.get("entries") or []

    accepted = 0
    for e in entries:
        cand = {
            "id": e.get("id") or "", "title": e.get("title") or "",
            "seconds": int(e.get("duration") or 0),
            "channel": e.get("channel") or e.get("uploader") or "",
            "description": e.get("description") or "",
        }
        v = evaluate(cand, film, black)
        accepted += 1 if v.get("accept") else 0
        mark = "ACCEPT" if v.get("accept") else "reject"
        print(f"\n[{mark}] {cand['id']}  {cand['seconds']}s  {cand['channel']}")
        print(f"        {cand['title']}")
        print(f"        {json.dumps(v)}")
        if v.get("why") == "blacklisted":
            alt = evaluate(cand, film, None)
            print(f"        ignoring blacklist: {json.dumps(alt)}")

    print(f"\nRESULT   {accepted} accept(s) of {len(entries)}")
    return 0 if accepted else 1


if __name__ == "__main__":
    sys.exit(main())
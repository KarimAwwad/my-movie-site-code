#!/usr/bin/env python3
"""ids_pull.py — fill ids.txt with real TMDB ids for a verification run.

Walks the discover endpoint one page per year, newest first, so the sample spans
the catalogue instead of one genre page. Reads TMDB_KEY from env, .env,
config.json, or grab.json, same as library.py.

    python ids_pull.py --count 500 --out ids.txt
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def config_value(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if val:
        return val
    candidates = [key, key.lower()]
    for name in (".env", "config.json", "grab.json"):
        p = HERE / name
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        if name.endswith(".json"):
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    for k in candidates:
                        got = str(data.get(k) or "").strip()
                        if got:
                            return got
            except ValueError:
                pass
        else:
            for line in text.splitlines():
                stripped = line.strip()
                for k in candidates:
                    if stripped.startswith(k + "="):
                        return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def tmdb_get(path: str, key: str):
    url = f"https://api.themoviedb.org/3{path}"
    headers = {"Accept": "application/json"}
    if len(key) > 60 or key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    else:
        sep = "&" if "?" in url else "?"
        url += f"{sep}api_key={urllib.parse.quote(key, safe='')}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=500)
    ap.add_argument("--out", default="ids.txt")
    ap.add_argument("--from-year", type=int, default=2026)
    ap.add_argument("--to-year", type=int, default=1950)
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    key = config_value("TMDB_KEY")
    if not key:
        print("no TMDB_KEY in env, .env, config.json, or grab.json")
        return 2

    seen: list[str] = []
    seen_set: set[str] = set()

    year = args.from_year
    while year >= args.to_year and len(seen) < args.count:
        for page in range(1, 6):
            if len(seen) >= args.count:
                break
            path = (
                f"/discover/movie?sort_by=popularity.desc&vote_count.gte=30"
                f"&include_adult=false&primary_release_year={year}&page={page}"
            )
            try:
                data = tmdb_get(path, key)
            except Exception as exc:
                print(f"{year} page {page}: {exc}")
                time.sleep(1.5)
                continue
            for row in data.get("results") or []:
                tmdb = str(row.get("id") or "")
                if tmdb.isdigit() and tmdb not in seen_set:
                    seen_set.add(tmdb)
                    seen.append(tmdb)
            if page >= int(data.get("total_pages") or 1):
                break
            time.sleep(0.12)
        print(f"{year}: {len(seen)} so far")
        year -= 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(seen) + "\n", encoding="utf-8")
    print(f"wrote {len(seen)} id(s) to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
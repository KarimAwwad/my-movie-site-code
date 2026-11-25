#!/usr/bin/env python3
"""Read-only 500-movie /dry sweep against grab.py to verify YTS match coverage."""

import json
import pathlib
import sys
import time
import urllib.request

CFG_PATH = pathlib.Path(__file__).with_name("grab.json")
OUT_PATH = pathlib.Path(__file__).with_name("dry_sweep_500_report.json")
TARGET_COUNT = 500
DELAY_SEC = 0.35


def fetch_json(url: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "RUIN-dry-sweep/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main() -> int:
    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8-sig"))
    tmdb_key = cfg["tmdb_key"]
    grab_url = f"http://{cfg.get('host', '127.0.0.1')}:{cfg.get('port', 8789)}"

    health = fetch_json(f"{grab_url}/health")
    print(
        f"Connected to grab {health.get('version')} "
        f"(max_quality={health.get('max_quality')}, min_seeds={health.get('min_seeds')})"
    )

    movies = []
    seen_ids = set()
    page = 1
    while len(movies) < TARGET_COUNT and page <= 35:
        discover_url = (
            f"https://api.themoviedb.org/3/discover/movie?api_key={tmdb_key}"
            f"&include_adult=false&include_video=false&sort_by=popularity.desc"
            f"&vote_count.gte=500&primary_release_date.lte=2026-10-01&page={page}"
        )
        data = fetch_json(discover_url)
        for m in data.get("results") or []:
            tid = m.get("id")
            if tid and tid not in seen_ids:
                seen_ids.add(tid)
                movies.append(m)
                if len(movies) >= TARGET_COUNT:
                    break
        page += 1
        time.sleep(0.2)

    print(f"Collected {len(movies)} released mainstream TMDB titles. Running /dry sweep...")
    matched = []
    missed = []

    for idx, m in enumerate(movies, 1):
        tid = m["id"]
        try:
            res = fetch_json(f"{grab_url}/dry?tmdb={tid}")
        except Exception as e:
            missed.append({
                "tmdb": tid,
                "title": m.get("title"),
                "year": (m.get("release_date") or "")[:4],
                "reason": f"http error: {e}",
            })
            continue

        cands = res.get("candidates") or []
        if cands:
            top = cands[0]
            matched.append({
                "tmdb": tid,
                "title": res.get("title"),
                "quality": top.get("quality"),
                "uncut": top.get("uncut", False),
                "size_h": top.get("size_h"),
                "seeds": top.get("seeds"),
            })
        else:
            missed.append({
                "tmdb": tid,
                "title": res.get("title") or m.get("title"),
                "year": (m.get("release_date") or "")[:4],
                "imdb": res.get("imdb", ""),
                "reason": res.get("rejected") or "no candidates",
            })

        if idx % 25 == 0 or idx == len(movies):
            pct = (len(matched) / idx) * 100.0
            print(f"[{idx}/{len(movies)}] matched={len(matched)} missed={len(missed)} ({pct:.1f}%)")
        time.sleep(DELAY_SEC)

    hit_rate = (len(matched) / max(1, len(movies))) * 100.0
    report = {
        "total": len(movies),
        "matched": len(matched),
        "missed": len(missed),
        "hit_rate_pct": round(hit_rate, 2),
        "passed_95_pct_gate": hit_rate >= 95.0,
        "missed_details": missed,
    }
    OUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nDone: {len(matched)}/{len(movies)} matched ({hit_rate:.2f}%). Report saved to {OUT_PATH.name}")
    return 0 if hit_rate >= 95.0 else 1


if __name__ == "__main__":
    sys.exit(main())
#!/usr/bin/env python3
r"""
live_test_500.py - Large-scale real-time live test suite (~500 live TMDB movies).
Harvests ~500 real movies live from TMDB (popular / top_rated / discover across pages &
genres/years) and runs live routing/resolution/verification/failure/anomaly checks with
concurrency, rate-limit awareness, resumable checkpointing (JSONL), and a structured
bug/anomaly report so real edge cases across hundreds of titles surface immediately.

Run from:
  cd /d "D:\my development work\active and archived projects\ruintv server"
  python live_test_500.py --count 500

For a faster initial pass or custom slice:
  python live_test_500.py --count 500 --workers 8 --relay-sample 40 --out live_500_results.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SERVER_DIR = Path(r"D:\my development work\unfinished and finished development projects\ruintv server")
RELAY_DIR = Path(r"D:\my development work\unfinished and finished development projects\ruin-stream")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ruin-live-500/1.0"
PRINT_LOCK = threading.Lock()
BUG_LOCK = threading.Lock()
BUG_SAMPLES: dict[str, list[dict]] = {}


def log(msg: str) -> None:
    with PRINT_LOCK:
        print(msg, flush=True)


def record_bug(category: str, item: dict, max_samples: int = 8) -> None:
    with BUG_LOCK:
        bucket = BUG_SAMPLES.setdefault(category, [])
        if len(bucket) < max_samples:
            bucket.append(item)


def http_json(url: str, timeout: int = 25, headers: dict | None = None):
    req_headers = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, json.loads(raw), raw
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body), body
        except Exception:
            return e.code, None, body
    except Exception as e:
        return 0, None, str(e)


def tmdb_get(path: str, key: str, timeout: int = 20):
    key = (key or "").strip()
    if not key:
        return 0, None, "missing tmdb_key"
    url = f"https://api.themoviedb.org/3{path}"
    headers = {"Accept": "application/json"}
    if len(key) > 60 or key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    else:
        sep = "&" if "?" in url else "?"
        url += f"{sep}api_key={urllib.parse.quote(key, safe='')}"
    return http_json(url, timeout=timeout, headers=headers)


def harvest_tmdb_movies(key: str, target_count: int) -> list[dict]:
    """Pull up to target_count unique live movies across TMDB feeds and discover pages."""
    seen_ids: set[str] = set()
    movies: list[dict] = []

    feeds = [
        "/trending/movie/week",
        "/trending/movie/day",
        "/movie/popular",
        "/movie/top_rated",
        "/movie/now_playing",
        "/movie/upcoming",
    ]
    for path in feeds:
        for page in range(1, 6):
            if len(movies) >= target_count:
                break
            sep = "&" if "?" in path else "?"
            st, data, _ = tmdb_get(f"{path}{sep}page={page}", key, timeout=20)
            if st != 200 or not isinstance(data, dict):
                break
            results = data.get("results") or []
            if not results:
                break
            for row in results:
                tid = str(row.get("id") or "").strip()
                if not tid.isdigit() or tid in seen_ids:
                    continue
                seen_ids.add(tid)
                movies.append(row)
                if len(movies) >= target_count:
                    break

    discover_slices = [
        "&sort_by=popularity.desc",
        "&sort_by=vote_count.desc",
        "&sort_by=primary_release_date.desc&primary_release_date.lte=2026-11-25",
        "&primary_release_year=2025&sort_by=popularity.desc",
        "&primary_release_year=2024&sort_by=popularity.desc",
        "&primary_release_year=2023&sort_by=popularity.desc",
    ]
    for sl in discover_slices:
        if len(movies) >= target_count:
            break
        for page in range(1, 12):
            if len(movies) >= target_count:
                break
            st, data, _ = tmdb_get(f"/discover/movie?include_adult=false{sl}&page={page}", key, timeout=20)
            if st != 200 or not isinstance(data, dict):
                break
            results = data.get("results") or []
            if not results:
                break
            for row in results:
                tid = str(row.get("id") or "").strip()
                if not tid.isdigit() or tid in seen_ids:
                    continue
                seen_ids.add(tid)
                movies.append(row)
                if len(movies) >= target_count:
                    break

    return movies[:target_count]


def test_one_movie(
    idx: int,
    total: int,
    summary_row: dict,
    tmdb_key: str,
    relay_url: str,
    run_relay: bool,
    source_mod,
) -> dict:
    tid = str(summary_row.get("id") or "")
    started = time.time()
    rec: dict = {
        "index": idx,
        "tmdb": tid,
        "title": summary_row.get("title") or summary_row.get("original_title") or "",
        "release_date": summary_row.get("release_date") or "",
        "runtime_min": 0,
        "original_language": (summary_row.get("original_language") or "").lower(),
        "plan_rung": "",
        "plan_state": "",
        "plan_why": "",
        "relay_status": None,
        "relay_sources": 0,
        "relay_verified": 0,
        "relay_cam": 0,
        "relay_tried_rejected": 0,
        "anomalies": [],
        "elapsed_s": 0.0,
    }

    st_d, det, raw_d = tmdb_get(f"/movie/{tid}", tmdb_key, timeout=20)
    if st_d == 200 and isinstance(det, dict):
        rec["title"] = det.get("title") or rec["title"]
        rec["runtime_min"] = int(det.get("runtime") or 0)
        rec["original_language"] = (det.get("original_language") or rec["original_language"]).lower()
        rec["release_date"] = det.get("release_date") or rec["release_date"]
    else:
        rec["anomalies"].append(f"tmdb_detail_http_{st_d}")
        record_bug("tmdb_detail_error", {"tmdb": tid, "title": rec["title"], "http": st_d, "raw": raw_d[:140]})

    try:
        plan = source_mod.choose(tid)
        rec["plan_rung"] = str(plan.get("rung") or "none")
        rec["plan_state"] = str(plan.get("state") or "unknown")
        rec["plan_why"] = str(plan.get("why") or "")

        if rec["plan_rung"] == "none" and rec["plan_state"] == "failed":
            rec["anomalies"].append(f"plan_failed:{rec['plan_why']}")
            record_bug(
                "source_choose_failed",
                {
                    "tmdb": tid,
                    "title": rec["title"],
                    "runtime_min": rec["runtime_min"],
                    "why": rec["plan_why"],
                },
            )
        elif rec["plan_state"] == "ready" and not (
            plan.get("url") or plan.get("video_id") or plan.get("quality") or plan.get("rung") == "yts"
        ):
            rec["anomalies"].append("ready_missing_target")
            record_bug("ready_missing_target", {"tmdb": tid, "title": rec["title"], "plan": plan})

        plan_secs = int(plan.get("seconds") or 0)
        rt_secs = int(rec["runtime_min"] or 0) * 60
        if rt_secs > 0 and plan_secs > 0 and rec["plan_rung"] in ("provider", "youtube"):
            ratio = plan_secs / rt_secs
            if ratio < 0.70 or ratio > 1.45:
                rec["anomalies"].append(f"duration_ratio_{ratio:.2f}")
                record_bug(
                    "duration_outlier",
                    {
                        "tmdb": tid,
                        "title": rec["title"],
                        "rung": rec["plan_rung"],
                        "plan_secs": plan_secs,
                        "runtime_secs": rt_secs,
                        "ratio": round(ratio, 3),
                    },
                )
    except Exception as exc:
        rec["plan_rung"] = "exception"
        rec["plan_state"] = "error"
        rec["plan_why"] = repr(exc)
        rec["anomalies"].append(f"source_choose_exc:{exc}")
        record_bug("source_choose_exception", {"tmdb": tid, "title": rec["title"], "exc": repr(exc)})

    if run_relay:
        st_r, r_data, r_raw = http_json(f"{relay_url}/resolve?id={tid}", timeout=75)
        rec["relay_status"] = st_r
        if st_r == 200 and isinstance(r_data, dict):
            srcs = r_data.get("sources") or []
            rec["relay_sources"] = len(srcs)
            st_s, s_data, _ = http_json(f"{relay_url}/status?id={tid}", timeout=20)
            if st_s == 200 and isinstance(s_data, dict):
                kept = s_data.get("sources") or []
                tried = s_data.get("tried") or []
                rec["relay_verified"] = sum(1 for x in kept if x.get("verified"))
                rec["relay_cam"] = sum(1 for x in kept if x.get("cam"))
                rec["relay_tried_rejected"] = len(tried)
                if len(kept) > 0 and rec["relay_verified"] == 0 and rec["runtime_min"] > 0:
                    rec["anomalies"].append("relay_zero_verified_with_runtime")
                    record_bug(
                        "relay_zero_verified",
                        {
                            "tmdb": tid,
                            "title": rec["title"],
                            "runtime_min": rec["runtime_min"],
                            "kept": len(kept),
                            "tried_rejected": len(tried),
                        },
                    )
        else:
            rec["anomalies"].append(f"relay_http_{st_r}")
            record_bug("relay_error", {"tmdb": tid, "title": rec["title"], "http": st_r, "raw": r_raw[:140]})

    rec["elapsed_s"] = round(time.time() - started, 2)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=500, help="Number of live TMDB movies to test")
    ap.add_argument("--workers", type=int, default=6, help="Concurrent worker threads")
    ap.add_argument(
        "--relay-sample",
        type=int,
        default=50,
        help="How many movies also hit live relay /resolve + /status (0 to skip relay, or --count for all)",
    )
    ap.add_argument("--relay", default="http://127.0.0.1:8787")
    ap.add_argument("--out", default="live_500_results.jsonl", help="Checkpoint output JSONL path")
    ap.add_argument("--fresh", action="store_true", help="Ignore existing output file and start fresh")
    args = ap.parse_args()

    cfg_path = SERVER_DIR / "grab.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig")) if cfg_path.is_file() else {}
    tmdb_key = str(cfg.get("tmdb_key") or "").strip()
    if not tmdb_key:
        print("ERROR: no tmdb_key found in grab.json", file=sys.stderr)
        sys.exit(2)

    out_path = Path(args.out)
    if args.fresh and out_path.exists():
        out_path.unlink()

    existing_ids: set[str] = set()
    rows: list[dict] = []
    if out_path.exists():
        for ln in out_path.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)
                rows.append(obj)
                if obj.get("tmdb"):
                    existing_ids.add(str(obj["tmdb"]))
            except Exception:
                pass

    log(f"Harvesting up to {args.count} live movies from TMDB...")
    movies = harvest_tmdb_movies(tmdb_key, args.count)
    log(f"Harvested {len(movies)} unique live movies ({len(existing_ids)} already in {out_path}).")

    sys.path.insert(0, str(SERVER_DIR))
    sys.path.insert(0, str(RELAY_DIR))
    import source  # type: ignore

    pending = [m for m in movies if str(m.get("id") or "") not in existing_ids]
    relay_budget = max(0, args.relay_sample)
    relay_assigned = 0
    tasks = []
    for idx_offset, m in enumerate(pending, start=len(existing_ids) + 1):
        use_relay = False
        if relay_assigned < relay_budget:
            use_relay = True
            relay_assigned += 1
        tasks.append((idx_offset, len(movies), m, use_relay))

    t_start = time.time()
    completed_count = len(rows)

    with open(out_path, "a", encoding="utf-8", newline="\n") as out_f, ThreadPoolExecutor(
        max_workers=max(1, args.workers)
    ) as pool:
        fut_map = {
            pool.submit(
                test_one_movie,
                idx,
                tot,
                m,
                tmdb_key,
                args.relay.rstrip("/"),
                use_relay,
                source,
            ): (idx, m)
            for idx, tot, m, use_relay in tasks
        }

        for fut in as_completed(fut_map):
            idx, m = fut_map[fut]
            try:
                rec = fut.result()
            except Exception as exc:
                rec = {
                    "index": idx,
                    "tmdb": str(m.get("id") or ""),
                    "title": m.get("title") or "",
                    "plan_rung": "exception",
                    "plan_state": "error",
                    "plan_why": repr(exc),
                    "anomalies": [f"worker_exc:{exc}"],
                    "elapsed_s": 0.0,
                }
                record_bug("worker_exception", rec)

            with BUG_LOCK:
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_f.flush()
                rows.append(rec)
                completed_count += 1

            if completed_count % 25 == 0 or completed_count == len(movies) or rec.get("anomalies"):
                anom_tag = f" ANOM={rec['anomalies']}" if rec.get("anomalies") else ""
                log(
                    f"[{completed_count}/{len(movies)}] tmdb={rec['tmdb']} "
                    f"rung={rec['plan_rung']}/{rec['plan_state']} "
                    f"({rec['elapsed_s']}s) {rec['title'][:36]}{anom_tag}"
                )

    total_time = time.time() - t_start
    rung_counts = Counter(r.get("plan_rung") or "unknown" for r in rows)
    state_counts = Counter(r.get("plan_state") or "unknown" for r in rows)
    anom_counts = Counter(a for r in rows for a in (r.get("anomalies") or []))
    movies_with_anom = sum(1 for r in rows if r.get("anomalies"))
    zero_runtime = sum(1 for r in rows if int(r.get("runtime_min") or 0) <= 0)

    print("\n" + "=" * 72)
    print(f"500-MOVIE LIVE TEST SUMMARY ({len(rows)} total rows in {total_time:.1f}s)")
    print("Rungs :", dict(rung_counts))
    print("States:", dict(state_counts))
    print(f"Movies with anomalies: {movies_with_anom}/{len(rows)} | Zero/missing TMDB runtime: {zero_runtime}")
    if anom_counts:
        print("Anomaly breakdown:", dict(anom_counts))
    if BUG_SAMPLES:
        print("\nSAMPLE BUGS / EDGE CASES TO INSPECT:")
        for cat, samples in BUG_SAMPLES.items():
            print(f"  [{cat}] ({len(samples)} sample(s))")
            for s in samples[:4]:
                print("   ", json.dumps(s, ensure_ascii=False)[:220])
    print("=" * 72)


if __name__ == "__main__":
    main()

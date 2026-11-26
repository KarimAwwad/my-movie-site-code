#!/usr/bin/env python3
"""
dry_sweep_yt.py — Read-only /dry verification sweep for Phase 2B (YTS + YouTube fallback)

Usage:
    python dry_sweep_yt.py
"""

from __future__ import annotations

import json
import time
import urllib.request

BASE = "http://127.0.0.1:8789"

# Mix of YTS-indexed movies and YouTube-hosted / indie titles (including Remain Calm)
TEST_CASES = [
    {"tmdb": 631842, "note": "Knock at the Cabin (2023) — YTS primary"},
    {"tmdb": 49018, "note": "Insidious (2010) — YTS primary"},
    {"tmdb": 1261152, "note": "Remain Calm — YouTube multi-dub fallback"},
    {"tmdb": 1218925, "note": "Chainsaw Man Reze Arc (2025) — 2160p ceiling gate"},
    {"tmdb": 1248832, "note": "Digger (2026) — Unreleased / noise rejection gate"},
]


def main() -> None:
    report = []
    for item in TEST_CASES:
        tmdb = item["tmdb"]
        t0 = time.time()
        url = f"{BASE}/dry?tmdb={tmdb}"
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            data = {"tmdb": tmdb, "error": str(e)}
        elapsed = round(time.time() - t0, 2)
        cands = data.get("candidates") or []
        top = cands[0] if cands else {}
        aud = [a["label"] for a in (top.get("audio_tracks") or [])]
        row = {
            "tmdb": tmdb,
            "note": item["note"],
            "title": data.get("title", ""),
            "source": data.get("source", "none"),
            "matched": bool(cands),
            "quality": top.get("quality", ""),
            "audio_count": len(aud),
            "audio_tracks": aud,
            "rejected": data.get("rejected", data.get("error", "")),
            "elapsed_s": elapsed,
        }
        report.append(row)
        print(
            f"[{row['source'].upper():7s}] tmdb={tmdb} | {row['title'] or '?'} | "
            f"matched={row['matched']} | {row['quality']} | audio={row['audio_count']} {aud} | "
            f"why={row['rejected'] or 'OK'} ({elapsed}s)"
        )

    with open("dry_sweep_yt_report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print("\nSaved dry_sweep_yt_report.json")


if __name__ == "__main__":
    main()
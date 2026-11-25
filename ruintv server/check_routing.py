#!/usr/bin/env python3
"""
check_routing.py — Read-only check of source.py routing and grab/library state.
Does not download anything.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SERVER_DIR = Path(r"D:\my development work\unfinished and finished development projects\ruintv server")
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

TEST_IDS = ["631842", "2166599", "693134", "496243", "1008042"]


def main() -> None:
    try:
        import source
    except Exception as e:
        print("Could not import source.py:", e)
        return

    for tmdb_id in TEST_IDS:
        try:
            plan = source.choose(tmdb_id)
            summary = {
                k: plan.get(k)
                for k in ("tmdb", "title", "year", "kind", "original_language", "rung", "state", "quality", "cam", "verified", "why")
                if plan.get(k) is not None
            }
            print(json.dumps(summary, ensure_ascii=False))
        except Exception as e:
            print(f"{tmdb_id} -> error: {e}")

    for fname in ("library.json", "skip.json", "review.jsonl"):
        p = SERVER_DIR / fname
        if p.exists():
            print(f"{fname}: {p.stat().st_size} bytes")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
check_pipeline.py — Read-only diagnostic across baseline + 5 test movies.
Does not download full video files or open a player.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MOVIES = [
    (631842, "Knock at the Cabin (2023)"),
    (2166599, "Remain Calm (2026)"),
    (693134, "Dune: Part Two (2024)"),
    (496243, "Parasite (2019)"),
    (1008042, "Talk to Me (2022)"),
]


def fetch_json(url: str, timeout: int = 45):
    req = urllib.request.Request(url, headers={"User-Agent": "ruin-check/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "replace")[:300]}
    except Exception as e:
        return 0, {"error": str(e)}


def fetch_text(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "ruin-check/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def playlist_seconds(manifest_url: str) -> float:
    st, body = fetch_text(manifest_url)
    if st != 200 or not body:
        return 0.0
    secs = sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", body))
    if secs > 0:
        return secs
    child = next((ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("#")), "")
    if child:
        st2, body2 = fetch_text(urllib.parse.urljoin(manifest_url, child))
        if st2 == 200 and body2:
            return sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", body2))
    return 0.0


def main() -> None:
    server_dir = Path(r"D:\my development work\unfinished and finished development projects\ruintv server")
    baseline = server_dir / "baseline.py"

    print("=== 1. BASELINE ===")
    if baseline.is_file():
        proc = subprocess.run([sys.executable, str(baseline)], cwd=str(server_dir), text=True, capture_output=True)
        print(proc.stdout)
        if proc.stderr.strip():
            print("STDERR:", proc.stderr.strip())
    else:
        print("baseline.py not found at", baseline)

    print("=== 2. MOVIE RESOLUTION & METADATA CHECK ===")
    for tmdb_id, label in MOVIES:
        st, data = fetch_json(f"http://127.0.0.1:8787/resolve?id={tmdb_id}", timeout=60)
        print(f"\n--- {label} [TMDB {tmdb_id}] -> HTTP {st} ---")
        if st != 200 or not isinstance(data, dict):
            print("  resolve failed:", data)
            continue

        sources = data.get("sources") or []
        meta_top = {
            k: data.get(k)
            for k in ("title", "year", "runtime", "original_language", "lang", "error", "why")
            if data.get(k) is not None
        }
        print("  meta:", json.dumps(meta_top, ensure_ascii=False))
        print(f"  sources ({len(sources)}):")
        for idx, s in enumerate(sources[:6]):
            if not isinstance(s, dict):
                continue
            s_meta = s.get("meta") or {}
            src_url = s.get("url") or ""
            full_url = urllib.parse.urljoin("http://127.0.0.1:8787/", src_url) if src_url else ""
            m_secs = s.get("seconds") or s_meta.get("seconds") or 0
            if not m_secs and full_url and "/hls" in full_url:
                m_secs = round(playlist_seconds(full_url), 1)
            info = {
                "i": idx,
                "provider": s.get("provider") or s.get("label") or "",
                "secs": m_secs,
                "lang": s.get("lang") or s_meta.get("lang") or s_meta.get("audio_lang") or "",
                "verified": s_meta.get("verified"),
                "cam": s_meta.get("cam") or s_meta.get("cam_guess"),
                "why": s_meta.get("verify_why") or s.get("why") or "",
            }
            print("   ", json.dumps(info, ensure_ascii=False))

        st_g, job = fetch_json(f"http://127.0.0.1:8789/status?id={tmdb_id}", timeout=10)
        if st_g == 200 and isinstance(job, dict):
            g_summary = {
                k: job.get(k)
                for k in ("state", "rung", "quality", "why", "error", "rejected_count")
                if job.get(k) is not None
            }
            if g_summary:
                print("  grab:", json.dumps(g_summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
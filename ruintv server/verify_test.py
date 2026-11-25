#!/usr/bin/env python3
"""
verify_test.py — score the verifier against the library and the grab plan.

Read-only: nothing is downloaded, filed or deleted. For every id it either checks the
file already in the library, or asks source.choose() what it would fetch and checks
that candidate instead. It records which rung fired, the length against the TMDB
runtime, the title evidence, the verdict, and three failure classes:

  wrong       accepted but the numbers say it is not the film  (must stay 0)
  false flag  rejected but the numbers say it was the film      (must stay 0)
  soon        not released yet, so out of the coverage maths

A library entry whose cached length is 0 is probed on disk before it is judged, so a
stale index can never be read as a wrong verdict.

Targets: 0 wrong, 0 false flags, coverage >= 95% of released ids.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import verify
import source

HERE = Path(__file__).resolve().parent

VERIFIED, UNVERIFIED, REJECTED = verify.VERIFIED, verify.UNVERIFIED, verify.REJECTED

FFPROBE_FALLBACK = r"D:\my development work\development tools\ffmpeg\bin\ffprobe.exe"

SOON_WORDS = ("releases", "no release date", "in production", "announced", "post production")


def log(msg: str) -> None:
    print(msg, flush=True)


def config_value(key: str) -> str:
    """Environment, then .env, config.json, or grab.json — matching library.py."""
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


def grab_cfg() -> dict:
    try:
        data = json.loads((HERE / "grab.json").read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def ffprobe_bin() -> str:
    ff_dir = config_value("ffmpeg_dir")
    for cand in (os.environ.get("FFPROBE_BIN", ""),
                 str(Path(os.environ["FFMPEG_BIN"]).with_name("ffprobe.exe"))
                 if os.environ.get("FFMPEG_BIN") else "",
                 os.path.join(ff_dir, "ffprobe.exe" if os.name == "nt" else "ffprobe") if ff_dir else "",
                 FFPROBE_FALLBACK):
        if cand and Path(cand).is_file():
            return cand
    return shutil.which("ffprobe") or ""


def probe_seconds(path: Path) -> int:
    """Read the real length off disk. 0 when the file or the tool is missing."""
    ff = ffprobe_bin()
    if not ff or not path.is_file():
        return 0
    try:
        out = subprocess.run(
            [ff, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, timeout=90).stdout.decode("utf-8", "replace").strip()
        return int(float(out.splitlines()[-1]))
    except Exception:
        return 0


def http_json(url: str, timeout: int = 25, headers: dict | None = None):
    h = {"Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def tmdb_meta(key: str, tmdb: str) -> dict:
    """Title, original title, year and runtime (seconds). Always returns the full shape."""
    meta = {"title": "", "original": "", "year": "", "runtime": 0}
    if not key:
        return meta
    url = f"https://api.themoviedb.org/3/movie/{tmdb}"
    headers = {}
    if len(key) > 60 or key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    else:
        url += f"?api_key={urllib.parse.quote(key, safe='')}"
    for attempt in range(3):
        try:
            data = http_json(url, 20, headers=headers)
        except Exception:
            time.sleep(1.0 + attempt)
            continue
        meta.update({
            "title": data.get("title") or data.get("original_title") or "",
            "original": data.get("original_title") or "",
            "year": str(data.get("release_date") or "")[:4],
            "runtime": int(data.get("runtime") or 0) * 60,
        })
        return meta
    return meta


def library_index(base: str) -> dict[str, list[dict]]:
    try:
        data = http_json(f"{base}/index.json", 20)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def library_files(base: str, tmdb: str, full_index: dict[str, list[dict]]) -> list[dict]:
    try:
        detailed = http_json(f"{base}/index.json?tmdb={tmdb}", 20).get("files") or []
    except Exception:
        detailed = []
    raw_items = full_index.get(tmdb) or []
    if not detailed and raw_items:
        return [{"file": r.get("file") or "", "seconds": 0} for r in raw_items]
    out = []
    for i, entry in enumerate(detailed):
        merged = dict(entry)
        if not merged.get("file") and i < len(raw_items):
            merged["file"] = raw_items[i].get("file") or ""
        out.append(merged)
    return out


def numbers(seconds: int, runtime: int, title: str, blobs, id_keyed: bool) -> dict:
    """The raw measurements a human would look at, independent of the verdict."""
    wanted = verify.tokens(title)
    score = 1.0 if id_keyed or not wanted else verify.evidence(blobs, wanted)
    band = verify.band_ok(seconds, runtime, verify.POST_LOW, verify.POST_HIGH)
    return {
        "seconds": seconds,
        "runtime": runtime,
        "evidence": round(score, 2),
        "band": band,
        "ratio": round(seconds / runtime, 3) if runtime else 0.0,
    }


def check_file(base: str, root: Path, tmdb: str, meta: dict, full_index: dict[str, list[dict]]) -> list[dict]:
    """Verify every file the library already holds for this id."""
    out = []
    for entry in library_files(base, tmdb, full_index):
        seconds = int(entry.get("seconds") or 0)
        name = entry.get("file") or ""
        probed = False
        if seconds <= 0 and name:             # stale index: read the file instead of trusting a 0
            seconds = probe_seconds(root / name)
            probed = True
        blobs = [name, meta.get("title", ""), meta.get("original", "")]
        pre = verify.precheck(seconds, meta.get("runtime", 0), meta.get("title", ""), blobs, False)
        # no source promise for a file already on disk, so expected is 0
        post = verify.postcheck(seconds, 0, meta.get("runtime", 0), True, True)
        verdict = post if post["verdict"] == REJECTED else pre
        out.append({"stage": "library", "name": name, "verdict": verdict["verdict"],
                    "why": verdict["why"], "keyed": False, "rung": "file", "probed": probed,
                    **numbers(seconds, meta.get("runtime", 0), meta.get("title", ""), blobs, False)})
    return out


def check_plan(tmdb: str, meta: dict) -> dict:
    """Ask the planner what it would fetch and verify that candidate."""
    try:
        plan = source.choose(tmdb)
    except Exception as exc:
        return {"stage": "plan", "name": "", "verdict": REJECTED, "keyed": False, "rung": "-",
                "probed": False, "why": f"planner error: {exc}",
                **numbers(0, meta.get("runtime", 0), meta.get("title", ""), [], False)}
    rung = plan.get("rung") or "-"
    if plan.get("state") != "ready":
        return {"stage": "plan", "name": "", "verdict": REJECTED, "keyed": False, "rung": rung,
                "probed": False, "why": plan.get("why") or plan.get("state") or "no candidate",
                **numbers(0, meta.get("runtime", 0), meta.get("title", ""), [], False)}
    seconds = int(plan.get("seconds") or 0)
    title = plan.get("title") or meta.get("title", "")
    target_ref = plan.get("url") or (f"https://youtu.be/{plan['video_id']}" if plan.get("video_id") else "")
    blobs = [target_ref, title, plan.get("why", "")]
    keyed = bool(plan.get("id_keyed")) or plan.get("proof") in ("P1", "P2", "P3", "P4")
    pre = verify.precheck(seconds, meta.get("runtime", 0), meta.get("title", ""), blobs, keyed)
    return {"stage": "plan", "name": target_ref[:90], "verdict": pre["verdict"],
            "why": pre["why"], "keyed": keyed, "rung": rung, "probed": False,
            **numbers(seconds, meta.get("runtime", 0), meta.get("title", ""), blobs, keyed)}


def judge(row: dict) -> str:
    """PASS/FLAG/WRONG/SOON from the measurements, not from the verdict string."""
    if row["verdict"] == REJECTED:
        why = row["why"].lower()
        if row["rung"] in ("none", "-") and any(w in why for w in SOON_WORDS):
            return "SOON"
        # rejected while the numbers said it was the right film
        return "FALSE FLAG" if (row["band"] and row["evidence"] >= verify.EVIDENCE_MIN) else "REJECT"
    if row["evidence"] < verify.EVIDENCE_MIN and not row["keyed"]:
        return "WRONG"
    return "PASS" if row["verdict"] == VERIFIED else "UNVERIFIED"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--library", type=int, default=8788)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    base = f"http://127.0.0.1:{args.library}"
    try:
        http_json(f"{base}/health", 10)
    except Exception:
        log(f"library daemon not answering on {args.library} — start library.py first")
        return 2

    key = config_value("TMDB_KEY")
    root = Path(grab_cfg().get("library_root") or r"D:\movies\library")
    if not ffprobe_bin():
        log("warning: ffprobe not found — stale zero lengths cannot be re-read")

    full_index = library_index(base)
    if args.ids:
        ids = [x.strip() for x in Path(args.ids).read_text(encoding="utf-8-sig").splitlines()
               if x.strip().isdigit()]
    else:
        ids = sorted((k for k in full_index if str(k).isdigit()), key=int)
    if args.limit:
        ids = ids[:args.limit]
    if not ids:
        log("no ids: pass --ids ids.txt, or POST /scan to the library and try again")
        return 2

    log(f"verify_test: {len(ids)} id(s), tmdb key {'yes' if key else 'NO'}\n")

    rows: list[dict] = []
    for n, tmdb in enumerate(ids, 1):
        meta = tmdb_meta(key, tmdb)
        found = [] if args.ids else check_file(base, root, tmdb, meta, full_index)
        if not found:
            found = [check_plan(tmdb, meta)]
        for row in found:
            row["tmdb"] = tmdb
            row["title"] = meta.get("title", "")
            row["judge"] = judge(row)
            rows.append(row)
            if not args.json:
                log(f"[{n}/{len(ids)}] {tmdb} {row['title'][:34]:<34} {row['judge']:<11} "
                    f"{row['rung']:<6} {row['seconds']:>6}s/{row['runtime']:<6}s "
                    f"ev {row['evidence']:.2f}{' P' if row['probed'] else ''}  {row['why']}")

    live = [r for r in rows if r["judge"] != "SOON"]
    total = len(live)
    passes = sum(r["judge"] in ("PASS", "UNVERIFIED") for r in live)
    wrong = [r for r in live if r["judge"] == "WRONG"]
    flags = [r for r in live if r["judge"] == "FALSE FLAG"]
    soon = [r for r in rows if r["judge"] == "SOON"]
    coverage = passes / total * 100 if total else 0.0

    log("\n" + "=" * 60)
    log(f"released {total}  pass {passes}  reject {sum(r['judge'] == 'REJECT' for r in live)}"
        f"  wrong {len(wrong)}  false flags {len(flags)}  not released {len(soon)}")
    log(f"coverage {coverage:.1f}% of released  (target 95.0)   wrong {len(wrong)}  (target 0)")

    for r in wrong:
        log(f"  WRONG  {r['tmdb']} {r['title']}  {r['name']}  ev {r['evidence']:.2f} {r['ratio']}x")
    for r in flags:
        log(f"  FLAG   {r['tmdb']} {r['title']}  {r['name']}  ev {r['evidence']:.2f} {r['ratio']}x")
    for r in soon:
        log(f"  SOON   {r['tmdb']} {r['title']}  {r['why']}")

    ok = not wrong and not flags and coverage >= 95.0
    log("RESULT: PASS" if ok else "RESULT: FAIL")

    if args.out:
        Path(args.out).write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
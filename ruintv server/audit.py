#!/usr/bin/env python3
"""
audit.py — find the wrong films already sitting in the library.

Read-only. Every file is probed with ffprobe and its length and audio language
compared to TMDB metadata, using the same postcheck() the grabber uses before
filing. Nothing is moved unless --apply is given.

Files already in the library were filed without the gate, so this is the only
way "no wrong movies" is true for what is on disk today.

    python audit.py                  report only
    python audit.py --apply          move the failures to D:\\movies\\_wrong
    python audit.py --apply --purge  ...and empty _wrong first

_wrong is a SIBLING of the library folder, because library.py walks the library
root recursively and would otherwise index the quarantined copies again.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import verify

VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".ts", ".m2ts", ".mpg", ".mpeg"}
TMDB_TAG = re.compile(r"[\[(]tmdb[-_ ]?(\d+)[\])]", re.I)
UA = "Mozilla/5.0 ruin-audit"

DEFAULTS = {
    "library_root": r"D:\movies\library",
    "ffmpeg_dir": r"D:\my development work\development tools\ffmpeg\bin",
    "tmdb_key": "c8b3444f786125dd2b69a88d34202de4",
    "library_scan_url": "http://127.0.0.1:8788/scan",
    "auto_scan": True,
}

CONFIG = Path(__file__).with_name("grab.json")
META_CACHE: dict[int, tuple[int, str]] = {}


def log(msg: str) -> None:
    print(msg, flush=True)


def config() -> dict:
    cfg = dict(DEFAULTS)
    if not CONFIG.exists():
        return cfg
    try:
        loaded = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"grab.json unreadable: {exc}")
    if isinstance(loaded, dict):
        cfg.update(loaded)
    return cfg


def ffprobe(ffmpeg_dir: str) -> str:
    exe_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    if ffmpeg_dir:
        p = Path(ffmpeg_dir) / exe_name
        if p.is_file():
            return str(p)
    return shutil.which("ffprobe") or ""


def probe(exe: str, path: Path) -> dict:
    """Probe duration, stream presence, and audio language tags."""
    out = {"seconds": 0, "video": False, "audio": False, "audio_langs": [], "error": ""}
    if not exe:
        out["error"] = "no ffprobe"
        return out
    try:
        proc = subprocess.run(
            [exe, "-v", "error", "-print_format", "json",
             "-show_streams", "-show_format", str(path)],
            capture_output=True, timeout=60,
        )
        info = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except Exception as exc:
        out["error"] = str(exc)[:120]
        return out
    for stream in info.get("streams") or []:
        if stream.get("codec_type") == "video":
            out["video"] = True
        elif stream.get("codec_type") == "audio":
            out["audio"] = True
            lang = ((stream.get("tags") or {}).get("language") or "").strip().lower()
            out["audio_langs"].append(lang)
    try:
        out["seconds"] = int(float((info.get("format") or {}).get("duration") or 0))
    except (TypeError, ValueError):
        pass
    return out


def meta_of(tmdb: int, key: str) -> tuple[int, str]:
    """Return (runtime_seconds, original_language) from TMDB, cached."""
    if tmdb in META_CACHE:
        return META_CACHE[tmdb]
    seconds = 0
    orig_lang = ""
    key = str(key or "").strip()
    if key:
        url = f"https://api.themoviedb.org/3/movie/{tmdb}"
        headers = {"User-Agent": UA, "Accept": "application/json"}
        if len(key) > 60 or key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {key}"
        else:
            url += f"?api_key={urllib.parse.quote(key, safe='')}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            seconds = int(payload.get("runtime") or 0) * 60
            orig_lang = (payload.get("original_language") or "").strip().lower()
        except Exception:
            seconds = 0
            orig_lang = ""
    META_CACHE[tmdb] = (seconds, orig_lang)
    return seconds, orig_lang


def pick_audio_lang(audio_langs: list[str], want_lang: str) -> str:
    """Choose the representative audio tag for verify.postcheck().

    Accepts files where at least one audio stream is untagged or matches want_lang;
    only surfaces a mismatch when every audio stream is explicitly tagged as another language.
    """
    if not audio_langs or not want_lang:
        return ""
    for lang in audio_langs:
        if verify.audio_ok(lang, want_lang):
            return lang
    return audio_langs[0]


def poke_scan(cfg: dict) -> None:
    if not cfg.get("auto_scan", True):
        return
    scan_url = str(cfg.get("library_scan_url") or "").strip()
    if not scan_url:
        return
    try:
        req = urllib.request.Request(scan_url, data=b"", headers={"User-Agent": UA}, method="POST")
        with urllib.request.urlopen(req, timeout=60):
            pass
    except Exception as exc:
        log(f"scan poke skipped ({exc})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--purge", action="store_true")
    args = ap.parse_args()

    cfg = config()
    root = Path(cfg["library_root"]).resolve()
    if not root.is_dir():
        raise SystemExit(f"library not found: {root}")
    wrong_dir = root.parent / "_wrong"
    exe = ffprobe(cfg.get("ffmpeg_dir") or "")
    key = cfg.get("tmdb_key") or ""

    if args.purge and wrong_dir.is_dir():
        count = sum(1 for f in wrong_dir.rglob("*") if f.is_file())
        log(f"purge: deleting {count} file(s) from {wrong_dir}")
        if args.apply:
            shutil.rmtree(wrong_dir, ignore_errors=True)

    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXT]
    log(f"library  {root}")
    log(f"files    {len(files)}")
    log(f"mode     {'APPLY' if args.apply else 'dry run'}")
    log("")

    bad: list[tuple[Path, str]] = []
    untagged: list[Path] = []
    clean = 0
    unverified = 0

    for path in sorted(files):
        hit = TMDB_TAG.search(path.stem)
        if not hit:
            untagged.append(path)
            continue
        tmdb = int(hit.group(1))
        runtime, want_lang = meta_of(tmdb, key)
        info = probe(exe, path)
        audio_lang = pick_audio_lang(info["audio_langs"], want_lang)
        result = verify.postcheck(
            info["seconds"], 0, runtime, info["video"], info["audio"],
            audio_lang=audio_lang, want_lang=want_lang,
        )
        if result["verdict"] == verify.VERIFIED:
            clean += 1
        elif result["verdict"] == verify.UNVERIFIED:
            unverified += 1
            log(f"  unverified  {path.name}  ({result['why']})")
        else:
            bad.append((path, result["why"]))
            log(f"  WRONG       {path.name}  ({result['why']})")

    log("")
    log("=" * 62)
    log(f"match      {clean}")
    log(f"unverified {unverified}")
    log(f"wrong      {len(bad)}")
    log(f"untagged   {len(untagged)}  (no [tmdb-<id>] in the name, cannot be checked)")

    if args.apply and bad:
        wrong_dir.mkdir(parents=True, exist_ok=True)
        moved = 0
        for path, _ in bad:
            try:
                rel = path.relative_to(root.parent)
            except ValueError:
                rel = Path(path.name)
            dest = wrong_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest = dest.with_name(f"{dest.stem} ({int(time.time())}){dest.suffix}")
            try:
                shutil.move(str(path), str(dest))
                moved += 1
                log(f"moved  {path.name}")
            except OSError as exc:
                log(f"move failed  {path.name}: {exc}")
        if moved:
            poke_scan(cfg)
    elif bad:
        log("re-run with --apply to move them out of the library")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
dedupe.py — quarantine duplicate films and leftovers under D:\\movies.

Duplicates are grouped by the [tmdb-<id>] tag grab.py writes, or by the cleaned
file name when there is no tag. Within a group the copy to KEEP is chosen by size,
and when two sizes are within 2% the OLDEST wins: that is the copy that was
verified first, and the later one is the re-fetch.

Nothing is deleted. Copies move to D:\\movies\\_dupes, a SIBLING of the library
folder, because library.py walks the library root recursively and would otherwise
index the quarantined copies as fresh duplicates. --purge empties that folder first.

    python dedupe.py                     dry run, report only
    python dedupe.py --apply             move the duplicates to _dupes
    python dedupe.py --apply --purge     ...and delete what is already there
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
import urllib.request
from pathlib import Path

VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".ts", ".m2ts", ".mpg", ".mpeg"}
TMDB_TAG = re.compile(r"[\[(]tmdb[-_ ]?(\d+)[\])]", re.I)
COPY_SUFFIX = re.compile(r"\s\(\d+\)$")
STALE_PART_HOURS = 24
EMPTY_STAGE_HOURS = 2
UA = "Mozilla/5.0 ruin-dedupe"

DEFAULT_LIBRARY = r"D:\movies\library"
DEFAULT_STAGING = r"D:\movies\staging"
CONFIG_PATH = Path(__file__).with_name("grab.json")


def load_config() -> dict:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def group_key(path: Path) -> str | None:
    hit = TMDB_TAG.search(path.stem)
    if hit:
        return "tmdb:" + hit.group(1)
    stem = COPY_SUFFIX.sub("", path.stem)
    stem = re.sub(r"\s*\((19|20)\d{2}\)", "", stem)
    stem = re.sub(r"[^a-z0-9]+", " ", stem.lower()).strip()
    return "name:" + stem if stem else None


def collect(library: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for path in sorted(library.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXT:
            continue
        key = group_key(path)
        if key:
            groups.setdefault(key, []).append(path)
    return {k: v for k, v in groups.items() if len(v) > 1}


def choose_keep(paths: list[Path]) -> Path:
    sized: list[tuple[int, float, Path]] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        sized.append((stat.st_size, stat.st_mtime, path))
    if not sized:
        return paths[0]
    biggest = max(s for s, _, _ in sized)
    near = [(s, m, p) for s, m, p in sized if s >= biggest * 0.98]
    if len(near) > 1:
        return min(near, key=lambda t: t[1])[2]
    return max(sized, key=lambda t: t[0])[2]


def relative_to_movies(path: Path, movies: Path) -> Path:
    try:
        return path.relative_to(movies)
    except ValueError:
        return Path(path.name)


def unique_dest(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stamp = int(time.time())
    candidate = dest.with_name(f"{dest.stem} ({stamp}){dest.suffix}")
    counter = 1
    while candidate.exists():
        candidate = dest.with_name(f"{dest.stem} ({stamp}-{counter}){dest.suffix}")
        counter += 1
    return candidate


def move_to(path: Path, quarantine: Path, movies: Path, apply: bool) -> bool:
    dest = quarantine / relative_to_movies(path, movies)
    print(f"    move -> {dest}")
    if not apply:
        return True
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        final = unique_dest(dest)
        shutil.move(str(path), str(final))
        return True
    except OSError as exc:
        print(f"    move failed: {exc}")
        return False


def orphan_magnets(staging: Path, library: Path) -> list[Path]:
    out = []
    if not staging.is_dir():
        return out
    names = {p.stem for p in library.rglob("*") if p.suffix.lower() in VIDEO_EXT}
    for note in staging.glob("*.magnet.txt"):
        if note.stem.replace(".magnet", "") not in names:
            out.append(note)
    return out


def empty_stage_dirs(staging: Path) -> list[Path]:
    out = []
    if not staging.is_dir():
        return out
    now = time.time()
    for entry in staging.iterdir():
        if not entry.is_dir():
            continue
        files = [f for f in entry.rglob("*") if f.is_file()]
        if any(f.suffix.lower() in VIDEO_EXT for f in files):
            continue
        try:
            if now - entry.stat().st_mtime < EMPTY_STAGE_HOURS * 3600:
                continue
        except OSError:
            continue
        out.append(entry)
    return out


def stale_parts(staging: Path) -> list[Path]:
    out = []
    if not staging.is_dir():
        return out
    now = time.time()
    for part in staging.rglob("*.part"):
        try:
            if now - part.stat().st_mtime > STALE_PART_HOURS * 3600:
                out.append(part)
        except OSError:
            pass
    return out


def poke_scan(cfg: dict) -> None:
    if not cfg.get("auto_scan", True):
        return
    scan_url = str(cfg.get("library_scan_url") or "http://127.0.0.1:8788/scan").strip()
    if not scan_url:
        return
    try:
        req = urllib.request.Request(scan_url, data=b"", headers={"User-Agent": UA}, method="POST")
        with urllib.request.urlopen(req, timeout=60):
            pass
    except Exception as exc:
        print(f"scan poke skipped ({exc})")


def main() -> None:
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", default=cfg.get("library_root") or DEFAULT_LIBRARY)
    ap.add_argument("--staging", default=cfg.get("staging_dir") or DEFAULT_STAGING)
    ap.add_argument("--quarantine", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--purge", action="store_true")
    args = ap.parse_args()

    library = Path(args.library).resolve()
    staging = Path(args.staging).resolve()
    quarantine = Path(args.quarantine).resolve() if args.quarantine else (library.parent / "_dupes")
    if not library.is_dir():
        raise SystemExit(f"library not found: {library}")
    if quarantine == library or library in quarantine.parents:
        raise SystemExit("quarantine must sit OUTSIDE the library folder")

    if args.purge:
        if quarantine.is_dir():
            count = sum(1 for f in quarantine.rglob("*") if f.is_file())
            print(f"purge: deleting {count} file(s) already in quarantine")
            if args.apply:
                shutil.rmtree(quarantine, ignore_errors=True)
        else:
            print("purge: quarantine folder is empty")

    scanned = sum(1 for p in library.rglob("*")
                  if p.is_file() and p.suffix.lower() in VIDEO_EXT)

    groups = collect(library)
    planned: list[Path] = []
    moved: list[Path] = []
    reclaim = 0

    print(f"library    {library}")
    print(f"quarantine {quarantine}")
    print(f"mode       {'APPLY' if args.apply else 'dry run'}")
    print(f"files      {scanned}")
    if scanned < 2:
        print("           (library holds fewer than two videos — nothing to compare)")
    print()

    print(f"duplicate groups: {len(groups)}")
    for key, paths in sorted(groups.items()):
        keep = choose_keep(paths)
        label = key.split(":", 1)[1]
        print(f"\n  [{label}]  keeping {keep.name}")
        for path in paths:
            if path == keep:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            reclaim += size
            planned.append(path)
            print(f"    dupe  {path.name}  ({human(size)})")
            if move_to(path, quarantine, library.parent, args.apply) and args.apply:
                moved.append(path)

    magnets = orphan_magnets(staging, library)
    if magnets:
        print(f"\norphaned magnet notes: {len(magnets)}")
        for note in magnets:
            print(f"    {note.name}")
            if args.apply:
                try:
                    note.unlink()
                except OSError:
                    pass

    dirs = empty_stage_dirs(staging)
    if dirs:
        print(f"\nempty staging folders: {len(dirs)}")
        for folder in dirs:
            print(f"    {folder.name}")
            if args.apply:
                shutil.rmtree(folder, ignore_errors=True)

    parts = stale_parts(staging)
    if parts:
        print(f"\nstale .part files (>{STALE_PART_HOURS}h): {len(parts)}")
        for part in parts:
            print(f"    {part.name}")
            if args.apply:
                try:
                    part.unlink()
                except OSError:
                    pass

    print(f"\n{'=' * 60}")
    print(f"duplicates to quarantine: {len(planned)}   reclaimable: {human(reclaim)}")
    if not args.purge and planned:
        print("inspect the folder, then re-run with --apply --purge to delete for good")

    if args.apply:
        if moved:
            poke_scan(cfg)
        summary = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "groups": len(groups),
            "moved": [str(p) for p in moved],
            "magnets": [str(p) for p in magnets],
            "empty_dirs": [str(p) for p in dirs],
            "stale_parts": [str(p) for p in parts],
        }
        try:
            (Path(__file__).parent / "dedupe.last.json").write_text(
                json.dumps(summary, indent=1), encoding="utf-8")
        except OSError:
            pass


if __name__ == "__main__":
    main()
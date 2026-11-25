#!/usr/bin/env python3
"""
coverage.py — measure how many titles can actually be obtained. Never downloads.

Per id: TMDB details, the tags the site would show, YTS availability, what the
running relay's provider stack returns, and the best YouTube candidate with the
proof it satisfied. One verdict per title, appended to a JSONL file as it goes,
so a crash loses nothing.

YTS IS THE SOURCE. A title that YTS indexes is a YTS title and nothing else is
consulted; the provider and YouTube rungs exist for the residue — short films,
AI-generated work, YouTube-hosted uploads — and for the rare released feature
that YTS has not touched at all. For a short, an AI film or a YouTube upload YTS
is tried LAST, after YouTube, because those are the cases where a torrent is a
surprise rather than the expectation. A missing yt-dlp does not short-circuit
that last resort: the residue still gets its YTS attempt, and the missing-binary
reason is recorded only if YTS misses too.

YTS IS SEARCHED BY TITLE, NOT BY ID. `query_term` no longer matches an IMDb code
and silently returns nothing for one, which is what made every title look
untorrented and pushed the whole library onto providers. The lookup takes the
title and keeps only rows whose title and year match exactly; an IMDb code match
is accepted too and sorted first, but it cannot be the only route because TMDB's
own imdb_id is stale on plenty of films — 631842 carries tt8272064 while YTS
carries tt15679400 for the same picture. Title plus year cannot drift onto a
remake, so that is the key that is trusted.

TMDB reports runtime in MINUTES; every comparison here and in proofs.py is in
SECONDS, converted once in build_film.

Verdicts:
    yts             a torrent exists
    provider        the relay returns a stream long enough for the film
    youtube-strong  a YouTube candidate satisfied a proof
    unreleased      not out yet; nothing can exist
    nothing         tried, found nothing
    error           a step blew up; re-run with --redo

    python coverage.py --ids ids.txt --out coverage.jsonl
    python coverage.py --ids ids.txt --out coverage.jsonl --redo
    python coverage.py --summary coverage.jsonl
    python coverage.py --sweep needs.jsonl --out coverage.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from proofs import (
    blacklist_load,
    evaluate as evaluate_proof,
    fingerprint,
    stale,
)

TMDB_KEY = "c8b3444f786125dd2b69a88d34202de4"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ruin-coverage/1.6"

# The sanctioned API base is movies-api.accel.li; yts.gg is sunset and the rest are
# legacy mirrors kept as fallbacks in case the base moves again.
YTS_HOSTS = ("movies-api.accel.li", "yts.bz", "yts.pw", "yts.mx", "yts.lt", "yts.rs", "yts.am")

MIN_SECONDS = 480

QUALITY_ORDER = ("1080p", "720p", "480p", "2160p")
CAM_TYPES = {"cam", "hdcam", "hqcam", "ts", "telesync", "tc", "telecine", "scr", "screener", "r5"}
CAM_RE = re.compile(r"\b(cam|hdcam|hqcam|telesync|telecine|screener|scr|r5)\b", re.I)

CONFIG_PATH = Path(__file__).with_name("grab.json")
BLACKLIST_PATH = Path(__file__).with_name("yt_blacklist.json")
BLACKLIST = blacklist_load(BLACKLIST_PATH)
_YTDLP_CACHE: str | None = None

AI_KEYWORD_RE = re.compile(
    r"^(ai[- ]generated( (film|movie|video|content))?|generative ai|ai[- ]made|ai film|made with ai)$",
    re.I,
)
YT_KEYWORD_RE = re.compile(
    r"^(youtube|youtube video|youtube movie|youtube short|youtube film|youtube original)$", re.I
)


def log(msg: str) -> None:
    print(msg, flush=True)


def as_int(value) -> int:
    """Best-effort int. Payloads arrive as ints, floats or strings like "5400.0"."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def quality_pos(quality: str) -> int:
    """Position in the fixed preference order; unknown qualities sort last."""
    try:
        return QUALITY_ORDER.index((quality or "").lower())
    except ValueError:
        return len(QUALITY_ORDER)


def is_cam(kind: str, text: str = "") -> bool:
    """A torrent filmed in a cinema. `type` is authoritative; the name is the fallback."""
    if (kind or "").lower() in CAM_TYPES:
        return True
    return bool(CAM_RE.search(text or ""))


def config_value(key: str, default: str = "") -> str:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict) and data.get(key) not in (None, ""):
            return str(data[key]).strip()
    except (OSError, ValueError):
        pass
    return default


def get(url: str, timeout: int = 20, headers: dict | None = None) -> tuple[int, str]:
    h = {"User-Agent": UA, "Accept": "application/json, */*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def get_json(url: str, timeout: int = 20, headers: dict | None = None):
    status, body = get(url, timeout, headers)
    if status != 200:
        return status, None
    try:
        return status, json.loads(body)
    except Exception:
        return status, None


def tmdb_get(path: str, timeout: int = 20):
    key = config_value("tmdb_key", TMDB_KEY)
    if not key:
        return 0, None
    url = f"https://api.themoviedb.org/3{path}"
    headers = {}
    if len(key) > 60 or key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    else:
        sep = "&" if "?" in url else "?"
        url += f"{sep}api_key={urllib.parse.quote(key, safe='')}"
    for attempt in range(2):
        status, data = get_json(url, timeout=timeout, headers=headers)
        if status == 200 and isinstance(data, dict):
            return status, data
        if status not in (0, 429, 502, 503, 504) or attempt == 1:
            return status, data
        time.sleep(1.0)
    return 0, None


def ytdlp() -> str:
    global _YTDLP_CACHE
    if _YTDLP_CACHE is not None:
        return _YTDLP_CACHE
    configured = config_value("ytdlp_path")
    if configured and Path(configured).is_file():
        _YTDLP_CACHE = configured
        return _YTDLP_CACHE
    _YTDLP_CACHE = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe") or ""
    return _YTDLP_CACHE


def classify(details_obj: dict) -> dict:
    words = [str(k.get("name") or "").strip()
             for k in ((details_obj.get("keywords") or {}).get("keywords") or [])]
    host = ""
    try:
        host = urllib.parse.urlsplit(details_obj.get("homepage") or "").hostname or ""
    except Exception:
        pass
    host = host.replace("www.", "").lower()
    runtime = as_int(details_obj.get("runtime"))
    short = (0 < runtime <= 40) or any(w.lower() == "short film" for w in words)
    ai = any(AI_KEYWORD_RE.match(w) for w in words)
    yt = bool(re.match(r"(^|\.)(youtube\.com|youtu\.be)$", host)) or any(
        YT_KEYWORD_RE.match(w) for w in words)
    return {"short": short, "ai": ai, "youtube": yt, "host": host}


def details(tmdb: str) -> dict | None:
    status, data = tmdb_get(
        f"/movie/{tmdb}?append_to_response=keywords,external_ids,credits,videos"
    )
    if status != 200 or not isinstance(data, dict):
        return None
    return data


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def yts_rows(imdb: str, title: str, year: str = "") -> list[dict]:
    """Raw YTS movie rows for a title, first host that answers wins.

    `query_term` matches titles only — an IMDb code returns movie_count 0 — so the
    search is by title. A row is kept when its title and year match exactly, and an
    exact `imdb_code` match is kept as well and sorted ahead of the rest, because
    TMDB's imdb_id is stale on enough films that the code cannot be the only route.
    Title plus year is the pair that cannot drift onto a remake.
    """
    want = _norm(title)
    if not want:
        return []
    for host in YTS_HOSTS:
        status, data = get_json(
            f"https://{host}/api/v2/list_movies.json"
            f"?query_term={urllib.parse.quote(title)}&limit=10", timeout=15)
        if status != 200 or not isinstance(data, dict):
            continue
        by_id: list[dict] = []
        by_name: list[dict] = []
        for m in ((data.get("data") or {}).get("movies") or []):
            year_ok = not year or str(m.get("year") or "") == str(year)
            if imdb and (m.get("imdb_code") or "") == imdb:
                by_id.append(m)
                continue
            if _norm(m.get("title")) == want and year_ok:
                by_name.append(m)
        rows = by_id + by_name
        if rows:
            return rows
    return []


def has_yts(imdb: str, title: str, year: str = "") -> dict:
    """Whether a torrent exists, and how good the best of them is."""
    rows = yts_rows(imdb, title, year)
    if not rows:
        return {"found": False}
    torrents = [t for m in rows for t in (m.get("torrents") or [])]
    if not torrents:
        return {"found": False}
    qualities = sorted({(t.get("quality") or "").lower() for t in torrents if t.get("quality")},
                       key=quality_pos)
    cams = [
        is_cam(t.get("type"), m.get("title_long") or m.get("title") or "")
        for m in rows for t in (m.get("torrents") or [])
    ]
    return {
        "found": True,
        "cam": bool(cams) and all(cams),
        "qualities": qualities,
        "best": qualities[0] if qualities else "",
        "language": (rows[0].get("language") or "").lower(),
    }


def via_relay(tmdb: str, runtime: int) -> dict:
    """Ask the running relay, so the probe measures the real stack rather than a copy of it."""
    base = config_value("relay_url", "http://127.0.0.1:8787").rstrip("/")
    status, data = get_json(f"{base}/resolve?id={tmdb}", timeout=60)
    if status == 0:
        return {"found": False, "why": "relay unreachable (is it running?)"}
    if status != 200 or not isinstance(data, dict):
        return {"found": False, "why": f"relay {status}"}

    sources = data.get("sources") or []
    if not sources:
        return {"found": False, "why": "relay: no source", "tried": data.get("tried") or []}

    best = sources[0]
    meta = best.get("meta") or {}
    secs = as_int(best.get("seconds"))
    floor = min(MIN_SECONDS, max(45, int(runtime * 0.6))) if runtime else 45
    if secs < floor:
        return {"found": False, "seconds": secs, "why": f"too short {secs}s < {floor}s"}

    return {
        "found": True,
        "provider": best.get("provider"),
        "label": best.get("label"),
        "seconds": secs,
        "height": meta.get("height"),
        "cam": bool(meta.get("cam")),
        "cam_guess": bool(meta.get("cam_guess")),
        "count": len(sources),
    }


def describe(video_id: str) -> str:
    binary = ytdlp()
    if not binary:
        return ""
    try:
        out = subprocess.run(
            [binary, "--skip-download", "--no-warnings", "--print", "description", video_id],
            capture_output=True, timeout=90).stdout.decode("utf-8", "replace")
        return out[:4000]
    except Exception:
        return ""


def _search(query: str) -> list[dict]:
    binary = ytdlp()
    if not binary:
        return []
    cmd = [binary, "--flat-playlist", "--no-warnings", "--ignore-errors",
           "--print", "%(id)s\t%(title)s\t%(duration)s\t%(channel)s", query]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        try:
            secs = int(float(parts[2]))
        except ValueError:
            continue
        rows.append({"id": parts[0], "title": parts[1], "seconds": secs,
                     "channel": parts[3], "description": ""})
    return rows


def direct_lookup(tmdb: str, imdb: str, film: dict) -> dict:
    """Ask YouTube for the literal identifier instead of the name.

    A hit here is categorical: the video only surfaces for that string because the
    string is in its title or description, so P3/P4 fires by construction. The
    duration band still applies, which is what rejects an id-dropping reaction.
    """
    if not ytdlp():
        return {"state": "unavailable"}

    queries = []
    if imdb and imdb.startswith("tt"):
        queries.append((f"ytsearch5:{imdb}", "imdb-search"))
    if tmdb.isdigit():
        queries.append((f"ytsearch5:themoviedb.org/movie/{tmdb}", "tmdb-search"))
    if not queries:
        return {"state": "ok", "best": None, "tried": []}

    bl = blacklist_load(BLACKLIST_PATH)
    tried = []
    for query, route in queries:
        for row in _search(query):
            row["description"] = describe(row["id"])
            verdict = evaluate_proof(row, film, bl)
            tried.append({"id": row["id"], "title": row["title"], "seconds": row["seconds"],
                          "channel": row["channel"], "route": route,
                          "accept": verdict["accept"],
                          "proof": verdict.get("proof", ""), "why": verdict.get("why", "")})
            if verdict["accept"]:
                return {"state": "ok", "found_by": route,
                        "best": dict(row, proof=verdict["proof"],
                                     detail=verdict["detail"], route=route),
                        "tried": tried}
    return {"state": "ok", "best": None, "tried": tried}


def youtube_search(title: str, year: str, runtime: int, film: dict) -> dict:
    if not ytdlp():
        return {"state": "unavailable"}
    rows = _search(f"ytsearch10:{title} {year} full movie".strip())
    if not rows:
        return {"state": "ok", "best": None, "tried": []}

    # two independent uploads agreeing on a duration (within 5s) is the real runtime when TMDB has none
    agreement = 0
    for row in rows:
        s = row["seconds"]
        if s > 0:
            near = sum(1 for other in rows if abs(other["seconds"] - s) <= 5)
            if near > agreement:
                agreement = near
    film = dict(film)
    film["duration_agreement"] = agreement

    bl = blacklist_load(BLACKLIST_PATH)
    tried = []
    for row in rows[:5]:
        row["description"] = describe(row["id"])
        verdict = evaluate_proof(row, film, bl)
        tried.append({"id": row["id"], "title": row["title"], "seconds": row["seconds"],
                      "channel": row["channel"], "accept": verdict["accept"],
                      "proof": verdict.get("proof", ""), "why": verdict.get("why", "")})
        if verdict["accept"]:
            return {"state": "ok",
                    "best": dict(row, proof=verdict["proof"], detail=verdict["detail"]),
                    "tried": tried}
    return {"state": "ok", "best": None, "tried": tried}


def build_film(tmdb: str, d: dict) -> dict:
    """Runtime is converted to SECONDS here, once. Nothing downstream sees minutes."""
    return {
        "title": d.get("title") or d.get("original_title") or "",
        "year": (d.get("release_date") or "")[:4],
        "runtime": as_int(d.get("runtime")) * 60,
        "imdb": ((d.get("external_ids") or {}).get("imdb_id") or ""),
        "tmdb": tmdb,
        "homepage": d.get("homepage") or "",
        "release_date": d.get("release_date") or "",
        "status": d.get("status") or "",
        "poster_path": d.get("poster_path") or "",
        "overview": d.get("overview") or "",
        "directors": [c["name"] for c in ((d.get("credits") or {}).get("crew") or [])
                      if c.get("job") == "Director"],
        "companies": [c["name"] for c in (d.get("production_companies") or [])],
        "tmdb_video_keys": [v.get("key") for v in ((d.get("videos") or {}).get("results") or [])
                            if v.get("site") == "YouTube" and v.get("key")],
    }


def unreleased_reason(film: dict) -> str:
    """Non-empty when nothing can exist yet.

    Two ways to be unreleased: a future date, or no date at all on a title TMDB
    does not call Released. The second matters because In Production titles are
    routinely dateless, and without it they fall through to a search that cannot
    possibly succeed.
    """
    if film.get("status") == "Released":
        return ""
    date = film.get("release_date") or ""
    if date and date > time.strftime("%Y-%m-%d"):
        return "releases " + date
    if not date:
        return "no release date yet (" + (film.get("status") or "unknown") + ")"
    return ""


def probe(tmdb: str) -> dict:
    row: dict = {"tmdb": tmdb, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    d = details(tmdb)
    if not d:
        row["verdict"] = "error"
        row["why"] = "tmdb details failed"
        return row

    film = build_film(tmdb, d)
    title, year, runtime, imdb = film["title"], film["year"], film["runtime"], film["imdb"]
    kinds = classify(d)
    row.update({
        "title": title, "year": year, "runtime": runtime, "imdb": imdb,
        "kind": "/".join(k for k in ("ai", "youtube", "short") if kinds[k]) or "movie",
        "homepage": film["homepage"], "status": film["status"],
        "fp": fingerprint(film),
    })

    reason = unreleased_reason(film)
    if reason:
        row["verdict"] = "unreleased"
        row["why"] = reason
        row["needs"] = True
        return row

    # a short, an AI film or a YouTube upload is only a YTS title by accident
    yts_last = bool(kinds["short"] or kinds["ai"] or kinds["youtube"])

    if not yts_last:
        yts = has_yts(imdb, title, year)
        row["yts"] = yts
        if yts.get("found"):
            row["verdict"] = "yts"
            row["why"] = ("cam only, " if yts.get("cam") else "") + "torrent exists"
            return row

    src = via_relay(tmdb, runtime)
    row["provider"] = src
    if src.get("found"):
        row["verdict"] = "provider"
        return row

    direct = direct_lookup(tmdb, imdb, film)
    row["direct"] = direct
    if direct.get("best"):
        row["youtube"] = direct
        row["verdict"] = "youtube-strong"
        row["why"] = f"{direct['found_by']} -> {direct['best']['proof']} {direct['best']['detail']}"
        return row

    # unavailable means yt-dlp is missing, not that YouTube was searched and missed,
    # so a residue title still gets its YTS last resort below. The reason is only
    # recorded if YTS misses too.
    no_ytdlp = direct.get("state") == "unavailable"
    if not no_ytdlp:
        yt = youtube_search(title, year, runtime, film)
        row["youtube"] = yt
        if yt.get("best"):
            row["verdict"] = "youtube-strong"
            row["why"] = yt["best"]["proof"] + " " + yt["best"]["detail"]
            return row

    if yts_last:
        yts = has_yts(imdb, title, year)
        row["yts"] = yts
        if yts.get("found"):
            row["verdict"] = "yts"
            row["why"] = ("cam only, " if yts.get("cam") else "") + "torrent exists (last resort)"
            return row

    row["verdict"] = "nothing"
    row["why"] = "yt-dlp not installed" if no_ytdlp else "no candidate passed"
    row["needs"] = True
    return row


def summarise(path: Path) -> None:
    if not path.exists():
        print(f"no such file: {path}")
        print("  the summary reads an existing run — start one with --ids/--out, or")
        print("  point --summary at a file that is already there")
        return
    latest: dict[str, dict] = {}
    anonymous: list[dict] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                tmdb = str(row.get("tmdb") or "")
                if tmdb.isdigit():
                    latest[tmdb] = row
                else:
                    anonymous.append(row)
    except OSError as e:
        print(f"cannot read {path}: {e}")
        return
    rows = list(latest.values()) + anonymous
    total = len(rows)
    if not total:
        print(f"no rows in {path}")
        return
    verdicts = Counter(r.get("verdict") for r in rows)
    kinds = Counter(r.get("kind") for r in rows)

    print(f"titles: {total}\n")
    print("by tag:")
    for kind, n in kinds.most_common():
        print(f"  {kind:<16}{n:>6}")
    print("\nby verdict:")
    for verdict, n in verdicts.most_common():
        print(f"  {verdict:<16}{n:>6}  {n / total * 100:5.1f}%")

    obtainable = verdicts["yts"] + verdicts["provider"] + verdicts["youtube-strong"]
    print(f"\nobtainable outright   {obtainable}/{total}  {obtainable / total * 100:.1f}%")
    print(f"unreleased            {verdicts['unreleased']}")
    print(f"nothing found         {verdicts['nothing']}")
    print(f"errors                {verdicts['error']}")

    tail = [r for r in rows if r.get("kind") != "movie"]
    if tail:
        hit = sum(1 for r in tail if r.get("verdict") in ("yts", "provider", "youtube-strong"))
        print(f"\nnon-mainstream tail   {hit}/{len(tail)}  {hit / len(tail) * 100:.1f}%")


def sweep(needs_path: Path, out: Path) -> None:
    if not needs_path.exists():
        print(f"no needs file at {needs_path}")
        return
    latest: dict[str, dict] = {}
    order: list[str] = []
    with needs_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            tmdb = str(row.get("tmdb") or "")
            if not tmdb.isdigit():
                continue
            if tmdb not in latest:
                order.append(tmdb)
            latest[tmdb] = row

    rows = [latest[t] for t in order]
    retried = skipped = 0
    for index, row in enumerate(rows, 1):
        tmdb = str(row["tmdb"])
        d = details(tmdb)
        if not d:
            skipped += 1
            continue
        film = build_film(tmdb, d)
        if not stale(row, film):
            skipped += 1
            continue
        log(f"[{index}/{len(rows)}] {tmdb} changed, retrying")
        try:
            fresh = probe(tmdb)
        except Exception as e:
            fresh = {"tmdb": tmdb, "verdict": "error", "why": str(e)}
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(fresh) + "\n")
        retried += 1
        time.sleep(0.4)

    print(f"\nretried {retried}, skipped {skipped}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="ids.txt")
    ap.add_argument("--out", default="coverage.jsonl")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--summary", default="")
    ap.add_argument("--sweep", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.summary:
        summarise(Path(args.summary))
        return

    out = Path(args.out)
    if args.sweep:
        sweep(Path(args.sweep), out)
        return

    ids_path = Path(args.ids)
    if not ids_path.exists():
        print(f"no ids file at {ids_path}")
        print("  write one id per line, or point --ids at a file that is already there")
        return
    ids = list(dict.fromkeys(
        x.strip() for x in ids_path.read_text(encoding="utf-8-sig").splitlines()
        if x.strip().isdigit()
    ))
    if args.limit:
        ids = ids[:args.limit]

    done = set()
    if out.exists() and not args.redo:
        with out.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    done.add(str(json.loads(line)["tmdb"]))
                except Exception:
                    pass
    elif args.redo and out.exists():
        out.write_text("", encoding="utf-8")

    for index, tmdb in enumerate(ids, 1):
        if tmdb in done:
            log(f"[{index}/{len(ids)}] {tmdb}  skip")
            continue
        log(f"[{index}/{len(ids)}] {tmdb} ...")
        try:
            row = probe(tmdb)
        except Exception as e:
            row = {"tmdb": tmdb, "verdict": "error", "why": str(e)}
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        log(f"    {row.get('verdict')}  {row.get('title', '')}  {row.get('why', '')}")
        time.sleep(0.4)

    print()
    summarise(out)


if __name__ == "__main__":
    main()
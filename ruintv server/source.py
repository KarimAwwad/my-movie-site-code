#!/usr/bin/env python3
"""
source.py — decide how a title gets fetched, in the only safe order.

    feature:              yts  ->  provider  ->  youtube  ->  queue
    short / AI / youtube: provider  ->  youtube  ->  yts  ->  queue

We are the source. A film YTS indexes is taken from YTS and no provider is asked
for it, because a provider hands over the one copy it happens to hold while YTS
hands over a choice, at a quality and an audio track that are stated up front.
YTS is also the only rung that cannot serve a dub by accident.

A cam on YTS still ends the decision. A cam is the film, so it is fetched, played
and flagged, and the cam sweep replaces it with the first WEB or BluRay that
appears. Reaching a provider for a title that YTS already has is the failure this
ordering exists to prevent.

The exception is the residue: a short film, an AI-generated film, or a
YouTube-hosted upload is a YTS title only by accident, so the provider and
YouTube rungs go first and YTS is kept as a last resort before queueing. A queue
rung from the YouTube rung means yt-dlp is missing, not that YouTube was
consulted and missed, so it never short-circuits that last resort: YTS is still
asked, and both misses are carried into the queued plan.

A provider source must be VERIFIED by relay before it is considered: relay already
ran verify.precheck on every source it offered and dropped the failures, so a
source only arrives here carrying meta.verified or meta.unverified. Verified
sources win outright; unverified ones are used only when nothing verified exists,
and the plan says so.

`rejected` is the set of sources this job has already tried and failed, so a
re-resolve after a dead token can never hand the same dead copy back. It is
compared by src_id(), never literally: a host that mints a fresh token on every
resolve would otherwise look like a new source every time. A bare string is
accepted as a one-element set, so an external caller cannot iterate characters.

This module owns ordering and selection only. Every check is imported from
coverage.py and verify.py, so this and the numbers can never disagree.

    python source.py --ids ids.txt --limit 5
    python source.py --ids ids.txt --json > plans.jsonl

Never downloads anything.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path

import coverage as cov

MIN_SECONDS = cov.MIN_SECONDS


def log(msg: str) -> None:
    print(msg, flush=True)


def as_int(value) -> int:
    """Best-effort int. Relay and TMDb payloads are not always well typed."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def floor_for(runtime: int) -> int:
    """Seconds. A short film gets a short floor; a feature gets the full one."""
    secs = as_int(runtime)
    if secs <= 0:
        return 45
    return min(MIN_SECONDS, max(45, int(secs * 0.6)))


def quality_for(height: int) -> str:
    if height >= 1080:
        return "1080p"
    if height >= 720:
        return "720p"
    if height >= 480:
        return "480p"
    return "auto"


def src_id(url: str) -> str:
    """Stable identity for a source: scheme, host and path, with no query.

    A rejected URL cannot be compared literally. vixsrc mints a fresh token on every
    resolve, so the same copy returns with a different query string and a literal
    match misses it, and the retry re-downloads the identical dub. The relay's own
    proxy form carries the real URL in `u=`, so that is unwrapped first: otherwise
    every proxied source collapses to the same 127.0.0.1/hls key and one rejection
    would exclude the whole provider list.
    """
    parts = urllib.parse.urlsplit(url or "")
    inner = (urllib.parse.parse_qs(parts.query).get("u") or [""])[0]
    if inner:
        parts = urllib.parse.urlsplit(inner)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def provider_plan(tmdb: str, runtime: int, rejected=None) -> dict:
    """Ask relay for every source and choose one.

    Order inside the pool: digital before cam, then longest, then tallest. Only
    verified sources are considered while any exist. Anything in `rejected` is
    skipped by identity, so a retry moves forward instead of looping on the same
    dead or wrong-language copy.
    """
    if isinstance(rejected, str):
        rejected = {rejected} if rejected else set()
    else:
        rejected = {r for r in (rejected or ()) if r}
    rejected_ids = {src_id(r) for r in rejected}
    base = cov.config_value("relay_url", "http://127.0.0.1:8787").rstrip("/")
    status, data = cov.get_json(f"{base}/resolve?id={tmdb}", timeout=60)
    if status == 0:
        return {"rung": "none", "why": "relay unreachable (is it running?)"}
    if status != 200 or not isinstance(data, dict):
        return {"rung": "none", "why": f"relay {status}"}

    sources = [s for s in (data.get("sources") or [])
               if isinstance(s, dict) and s.get("url")
               and src_id(s["url"]) not in rejected_ids
               and src_id(s.get("direct") or "") not in rejected_ids]
    if not sources:
        return {"rung": "none", "why": "relay: no usable source"}

    verified = [s for s in sources if (s.get("meta") or {}).get("verified")]
    pool = verified or sources
    unverified = not verified

    usable = [s for s in pool if as_int(s.get("seconds")) > 0] or pool

    floor = floor_for(runtime)
    fit = [s for s in usable if as_int(s.get("seconds")) >= floor]
    ranked = fit or usable
    ranked.sort(key=lambda s: (
        bool((s.get("meta") or {}).get("cam")),
        -as_int(s.get("seconds")),
        -as_int((s.get("meta") or {}).get("height")),
    ))
    best = ranked[0]
    meta = best.get("meta") or {}
    return {
        "rung": "provider",
        "url": best["url"],
        "direct": best.get("direct") or "",
        "seconds": as_int(best.get("seconds")),
        "height": as_int(meta.get("height")),
        "quality": quality_for(as_int(meta.get("height"))),
        "cam": bool(meta.get("cam")),
        "cam_guess": bool(meta.get("cam_guess")),
        "verified": bool(meta.get("verified")),
        "unverified": unverified,
        "verify_why": meta.get("verify_why") or "",
        "label": best.get("provider") or best.get("label") or "",
        "count": len(sources),
        "why": ("cam, " if meta.get("cam") else "")
               + ("unverified, " if unverified else "")
               + f"{as_int(best.get('seconds'))}s",
    }


def yts_plan(film: dict) -> dict:
    """The YTS rung. A hit of any kind ends the decision, cam included."""
    yts = cov.has_yts(film["imdb"], film["title"], film["year"])
    if not yts.get("found"):
        return {"rung": "none", "why": yts.get("why") or "no torrent"}
    return {
        "rung": "yts",
        "state": "ready",
        "id_keyed": bool(film.get("imdb")),
        "seconds": as_int(yts.get("seconds")),
        "cam": bool(yts.get("cam")),
        "quality": yts.get("best") or "",
        "qualities": yts.get("qualities") or [],
        "why": ("cam only, " if yts.get("cam") else "") + "torrent exists",
    }


def youtube_plan(tmdb: str, film: dict) -> dict | None:
    """The proof-gated YouTube rungs, direct identifier first, then the name."""
    direct = cov.direct_lookup(tmdb, film["imdb"], film)
    if direct.get("best"):
        best = direct["best"]
        return {"rung": "youtube", "state": "ready", "video_id": best["id"],
                "id_keyed": best.get("proof") in ("P1", "P2", "P3", "P4"),
                "seconds": as_int(best.get("seconds")), "quality": "auto",
                "proof": best.get("proof"),
                "why": best.get("detail") or best.get("proof"),
                "tried": direct.get("tried") or []}
    if direct.get("state") == "unavailable":
        return {"rung": "queue", "state": "queued", "why": "yt-dlp not installed"}

    yt = cov.youtube_search(film["title"], film["year"], film["runtime"], film)
    if yt.get("best"):
        best = yt["best"]
        return {"rung": "youtube", "state": "ready", "video_id": best["id"],
                "id_keyed": best.get("proof") in ("P1", "P2", "P3", "P4"),
                "seconds": as_int(best.get("seconds")), "quality": "auto",
                "proof": best.get("proof"),
                "why": best.get("detail") or best.get("proof"),
                "tried": yt.get("tried") or []}
    return {"rung": "none", "why": "no proof fired", "tried": yt.get("tried") or []}


def choose(tmdb: str, rejected=None) -> dict:
    """Return a plan for one title. Never downloads."""
    plan: dict = {"tmdb": tmdb, "rung": "none", "state": "failed", "why": ""}

    d = cov.details(tmdb)
    if not d:
        plan["why"] = "tmdb details failed"
        return plan

    film = cov.build_film(tmdb, d)
    kinds = cov.classify(d)
    plan.update({
        "title": film["title"], "year": film["year"], "runtime": film["runtime"],
        "imdb": film["imdb"],
        "original_language": (d.get("original_language") or "").lower(),
        "kind": "/".join(k for k in ("ai", "youtube", "short") if kinds[k]) or "movie",
        "homepage": film["homepage"], "fp": cov.fingerprint(film),
    })

    reason = cov.unreleased_reason(film)
    if reason:
        plan.update(rung="none", state="unreleased", why=reason)
        return plan

    yts_last = bool(kinds["short"] or kinds["ai"] or kinds["youtube"])

    if not yts_last:
        yts = yts_plan(film)
        if yts.get("rung") == "yts":
            plan.update(yts)
            return plan
        plan["yts"] = yts

    prov = provider_plan(tmdb, film["runtime"], rejected)
    if prov.get("rung") == "provider":
        plan.update(prov, state="ready")
        return plan

    yt = youtube_plan(tmdb, film)
    if yt and yt.get("rung") == "youtube":
        plan.update(yt)
        return plan

    # A queue rung here means yt-dlp is missing, not that YouTube was consulted
    # and missed, so it must not short-circuit the YTS last resort below. Both
    # misses are carried into the queued plan instead of being dropped.
    yt_why = (yt or {}).get("why") or ""
    yt_tried = (yt or {}).get("tried") or []

    if yts_last:
        yts = yts_plan(film)
        if yts.get("rung") == "yts":
            plan.update(yts)
            plan["why"] = (yts.get("why") or "") + " (last resort)"
            return plan
        plan["yts"] = yts

    prov_why = prov.get("why") or ""
    why = yt_why or "no proof fired"
    if prov_why:
        why = f"{why}; provider: {prov_why}"
    plan.update(rung="queue", state="queued", why=why,
                tried=yt_tried, yt_why=yt_why, provider_why=prov_why)
    return plan


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="ids.txt")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ids = [x.strip() for x in Path(args.ids).read_text(encoding="utf-8-sig").splitlines()
           if x.strip().isdigit()]
    if args.limit:
        ids = ids[:args.limit]
    if not ids:
        print(f"no ids in {args.ids}")
        return

    counts: dict[str, int] = {}
    for index, tmdb in enumerate(ids, 1):
        plan = choose(tmdb)
        counts[plan["rung"]] = counts.get(plan["rung"], 0) + 1
        if args.json:
            print(json.dumps(plan))
            continue
        detail = plan.get("video_id") or plan.get("url") or ""
        log(f"[{index}/{len(ids)}] {tmdb}  {plan['rung']:<9}{plan.get('title', '')}  {plan.get('why', '')}")
        if detail:
            log(f"          {detail[:110]}")

    print()
    for rung, n in sorted(counts.items()):
        print(f"  {rung:<10}{n:>4}")
    ready = counts.get("yts", 0) + counts.get("provider", 0) + counts.get("youtube", 0)
    print(f"\nready {ready}/{len(ids)}")


if __name__ == "__main__":
    main()
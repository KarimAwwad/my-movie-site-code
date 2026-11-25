#!/usr/bin/env python3
"""
proofs.py — decide whether a YouTube candidate is provably the film.

A proof is a fact, not a score. P1-P4 are categorical (the video is named by
TMDB, or the description names the film) and they outrank a SOFT blacklist entry.
P5-P7 are strong but weaker, and a blacklist entry beats them.

A STICKY blacklist entry — written by /wrong, because a human looked at the file
and said it was the wrong thing — beats everything, including P1, and is tested
before any other check so the reported reason is always the human's. Otherwise the
same upload is re-taken by the same proof it always satisfied and the correction
loop goes in a circle. /forgive clears a sticky entry, and a soft re-add never
downgrades one.

RUNTIME IS IN SECONDS throughout this module. TMDB reports minutes, so the
caller converts once, at the point the film dict is built.

Hard rejects run first, so an explainer with the exact title and a matching
runtime still dies. Markers are tested after the film's own title has been
stripped out, so a film called "The Review" cannot reject itself.

Two gates sit behind the hard rejects and in front of P3, P4 and P7:

  title gate  every significant word of the film title must appear in the
              candidate's OWN title. A real rip names the film; an episode
              titled "Ep. 412 - Spooky Season" never does. P1 and P2 are
              exempt because TMDB named the video itself.

  kind gate   a film's trailer, teaser, clip, recap, review, reaction, podcast
              or episode vocabulary is rejected on the title and on the
              channel. An upload can name the film correctly and still be
              forty minutes of two men talking about it.

An UNRELEASED film has no runtime on TMDB, so the duration band cannot work and
falls back to a flat floor. That floor is deliberately high: unreleased titles
are feature films, not shorts, and the whole YouTube rung exists for them.

Over-rejecting is cheap: it falls to the provider rung, never to a wrong file.

    from proofs import evaluate, fingerprint, stale, blacklist_load
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata

PHRASE_MARKERS = (
    "ending explained", "behind the scenes", "making of", "kill count",
    "things you missed", "fan film", "easter eggs", "deleted scenes",
    "first time watching", "watch along", "full movie reaction",
)

# exact tokens, so "ep" cannot match inside "epic" and "clip" cannot match inside "eclipse"
TOKEN_MARKERS = {
    "reaction", "reactions", "recap", "recaps", "review", "reviews", "reviewed",
    "explained", "breakdown", "breakdowns", "trailer", "trailers", "teaser",
    "clip", "clips", "commentary", "analysis", "podcast", "podcasts", "pod",
    "interview", "interviews", "episode", "episodes", "ep", "eps", "season",
    "seasons", "special", "radio", "discussion", "unboxing",
}

# only the strongest of those are trusted on a channel name, because channel names are looser
CHANNEL_MARKERS = {"podcast", "podcasts", "pod", "radio"}

# words an uploader may legitimately add around a complete film title
NEUTRAL_TOKENS = {
    "official", "video", "videos", "4k", "8k", "hd", "hq", "full", "movie",
    "movies", "film", "films", "filme", "completo", "completa", "english",
    "espanol", "subtitles", "subs", "sub", "remastered", "remaster", "version",
    "ver", "vers", "long", "short", "extended", "unrated", "theatrical",
    "widescreen", "quality", "online", "free", "watch", "horror", "comedy",
    "drama", "thriller", "action", "scifi", "sci", "fi", "animation", "anime",
    "documentary", "spanish", "latino", "dubbed", "audio",
}

# joiners that never prove anything either way when deciding if extras are innocent
EXTRA_STOP = {"the", "and", "of", "a", "an", "in", "on", "to", "for", "with", "by"}

DURATION_LOW = 0.10        # mirrors verify.PRE_LOW — short is suspicious
DURATION_HIGH = 0.25       # mirrors verify.PRE_HIGH — longer is normal
MIN_SECONDS = 120          # flat floor when the runtime is known but tiny
MIN_SECONDS_UNKNOWN = 300  # flat floor when TMDB has no runtime at all
STICKY = "!"               # prefix marking a sticky id inside a loaded blacklist set
IMDB_RE = re.compile(r"\btt\d{7,9}\b")
TMDB_URL_RE = re.compile(r"themoviedb\.org/movie/(\d+)", re.I)
TMDB_ANY_RE = re.compile(r"\btmdb\b\D{0,12}(\d{3,9})", re.I)


def as_int(value) -> int:
    """Best-effort int. Payloads arrive as ints, floats or strings like "5400.0"."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"\((19|20)\d{2}\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_title(candidate_title: str, film_title: str) -> str:
    """Remove the film's own words so its title cannot trip a marker."""
    left = normalise(candidate_title)
    for word in normalise(film_title).split():
        left = re.sub(r"\b%s\b" % re.escape(word), " ", left)
    return re.sub(r"\s+", " ", left).strip()


def name_tokens(name: str) -> list[str]:
    return [w for w in normalise(name).split() if len(w) > 2]


def title_tokens(title: str) -> list[str]:
    return [w for w in normalise(title).split() if len(w) > 2 or w.isdigit()]


def title_gate(candidate_title: str, film_title: str) -> tuple[bool, list[str]]:
    """Every significant film-title word must be in the candidate's own title.

    Returns (ok, missing). A title with no significant words at all ("It") falls
    back to its full token set so the gate is not trivially satisfied.
    """
    want = title_tokens(film_title) or normalise(film_title).split()
    have = set(normalise(candidate_title).split())
    missing = [w for w in want if w not in have]
    return (not missing and bool(want)), missing


def extra_tokens(candidate_title: str, film_title: str) -> set[str]:
    """Title words the uploader added beyond the film's own. Years are neutral."""
    own = set(title_tokens(film_title))
    return {w for w in title_tokens(candidate_title)
            if w not in own and w not in EXTRA_STOP and not w.isdigit()}


def duration_ok(seconds: int, runtime: int) -> bool:
    """runtime is SECONDS. An unknown runtime cannot be banded, so it gets a flat floor.

    The band matches verify.precheck's on purpose: a proof must never refuse an upload the
    verifier would have accepted, or the YouTube rung ends up stricter than the gate it feeds.
    A short is floored at MIN_SECONDS and still capped, so a three-minute short cannot take a
    three-hour upload just because it is below the band threshold.
    """
    if runtime <= 0:
        return seconds >= MIN_SECONDS_UNKNOWN
    if runtime < MIN_SECONDS * 2:
        return MIN_SECONDS <= seconds <= max(MIN_SECONDS_UNKNOWN, runtime * (1 + DURATION_HIGH))
    return runtime * (1 - DURATION_LOW) <= seconds <= runtime * (1 + DURATION_HIGH)


def is_sticky(blacklist: set[str] | None, vid: str) -> bool:
    return bool(blacklist) and (STICKY + vid) in (blacklist or set())


def evaluate(candidate: dict, film: dict, blacklist: set[str] | None = None) -> dict:
    """
    candidate: {id, title, seconds, channel, description}
    film:      {title, year, runtime (SECONDS), imdb, tmdb, homepage,
                directors, companies, tmdb_video_keys, duration_agreement}

    Returns {"accept": True, "proof": "P3", "detail": ..., "unblacklist": bool}
    or {"accept": False, "why": ...}.
    """
    vid = str(candidate.get("id") or "")
    title = candidate.get("title") or ""
    channel = candidate.get("channel") or ""
    desc = candidate.get("description") or ""
    seconds = as_int(candidate.get("seconds"))
    runtime = as_int(film.get("runtime"))

    # a human marked this upload wrong; no proof may quietly take it again. This runs
    # before every other check, so the reason is always the human's, never a marker
    if is_sticky(blacklist, vid):
        return {"accept": False, "why": "blacklisted (marked wrong)"}

    weak_only = bool(blacklist) and (vid in (blacklist or set()))

    leftover = strip_title(title, film.get("title") or "")
    for phrase in PHRASE_MARKERS:
        if phrase in leftover:
            return {"accept": False, "why": "marker:" + phrase}
    for token in leftover.split():
        if token in TOKEN_MARKERS:
            return {"accept": False, "why": "marker:" + token}
    for token in sorted(set(normalise(channel).split()) & CHANNEL_MARKERS):
        return {"accept": False, "why": "channel:" + token}

    if not duration_ok(seconds, runtime):
        return {"accept": False, "why": "duration %ds vs %ss" % (seconds, runtime or "?")}

    ok, missing = title_gate(title, film.get("title") or "")
    gated_why = ""

    # --- exact proofs: these beat a SOFT blacklist entry, and clear it ---
    if vid and vid in (film.get("tmdb_video_keys") or []):
        return {"accept": True, "proof": "P1", "detail": "listed by TMDB",
                "unblacklist": weak_only}

    homepage = (film.get("homepage") or "").rstrip("/").lower()
    if homepage and vid and (vid in homepage):
        return {"accept": True, "proof": "P2", "detail": "TMDB homepage",
                "unblacklist": weak_only}

    imdb = (film.get("imdb") or "").strip()
    if imdb and IMDB_RE.fullmatch(imdb):
        if imdb.lower() in desc.lower() or imdb.lower() in title.lower():
            if ok:
                return {"accept": True, "proof": "P3", "detail": "IMDb id in description",
                        "unblacklist": weak_only}
            gated_why = "P3 matched, title missing " + ",".join(missing)

    tmdb = str(film.get("tmdb") or "")
    if tmdb:
        hit = TMDB_URL_RE.search(desc) or TMDB_ANY_RE.search(desc)
        if hit and hit.group(1) == tmdb:
            if ok:
                return {"accept": True, "proof": "P4", "detail": "TMDB id in description",
                        "unblacklist": weak_only}
            gated_why = gated_why or ("P4 matched, title missing " + ",".join(missing))

    # --- weak proofs: a blacklist entry wins here ---
    if weak_only:
        return {"accept": False, "why": "blacklisted"}

    chan = normalise(channel)
    if chan:
        for director in film.get("directors") or []:
            tokens = name_tokens(director)
            if tokens and all(t in chan for t in tokens):
                return {"accept": True, "proof": "P5", "detail": "director's channel",
                        "unblacklist": weak_only}
        for company in film.get("companies") or []:
            tokens = [t for t in name_tokens(company) if len(t) > 3]
            if tokens and all(t in chan for t in tokens):
                return {"accept": True, "proof": "P6", "detail": "studio channel",
                        "unblacklist": weak_only}

    # P7: every title word present, duration already inside the band, and the extras are all
    # innocent. The marker gate has already removed every known bad kind, so leftovers like
    # "official 4k video" are the uploader decorating a complete title, not a different thing.
    # An exact title, or two uploads agreeing on the duration, is still the strongest form.
    agree = as_int(film.get("duration_agreement"))
    if ok:
        if normalise(title) == normalise(film.get("title") or "") or agree >= 2:
            return {"accept": True, "proof": "P7",
                    "detail": "title complete + duration corroborated",
                    "unblacklist": weak_only}
        extra = extra_tokens(title, film.get("title") or "")
        if extra <= NEUTRAL_TOKENS:
            return {"accept": True, "proof": "P7",
                    "detail": "title complete, neutral extras only",
                    "unblacklist": weak_only}

    return {"accept": False, "why": gated_why or "no proof fired"}


def fingerprint(film: dict) -> str:
    """Hash of every field the ladder reads. A change means TMDB learned something."""
    keys = sorted(str(k) for k in (film.get("tmdb_video_keys") or []))
    blob = json.dumps([
        film.get("title") or "",
        as_int(film.get("year")),
        film.get("release_date") or "",
        film.get("status") or "",
        as_int(film.get("runtime")),
        film.get("homepage") or "",
        film.get("imdb") or "",
        str(film.get("tmdb") or ""),
        keys,
        sorted(str(d) for d in (film.get("directors") or [])),
        sorted(str(c) for c in (film.get("companies") or [])),
        as_int(film.get("duration_agreement")),
        film.get("poster_path") or "",
        len(film.get("overview") or ""),
    ], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def stale(row: dict, film: dict) -> bool:
    """True when the stored verdict was reached against different evidence."""
    stored = row.get("fp") or ""
    return not stored or stored != fingerprint(film)


def blacklist_add(path, vid: str, reason: str = "", sticky: bool = False) -> None:
    data = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    # an automatic soft re-add must not downgrade a human /wrong mark, or the upload is
    # re-taken by the very proof it was corrected for. Only sticky=True promotes.
    old = data.get(vid)
    keep = sticky or bool(isinstance(old, dict) and old.get("sticky"))
    data[vid] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "reason": reason,
                 "sticky": keep}
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)


def blacklist_remove(path, vid: str, keep_sticky: bool = True) -> bool:
    """Drop an entry. A sticky entry survives unless keep_sticky is False."""
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or vid not in data:
        return False
    entry = data[vid]
    if keep_sticky and isinstance(entry, dict) and entry.get("sticky"):
        return False
    data.pop(vid, None)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    return True


def blacklist_load(path) -> set[str]:
    """All blocked ids, with sticky ones also present as "!<id>"."""
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict):
        return set()
    out: set[str] = set()
    for key, entry in data.items():
        out.add(key)
        if isinstance(entry, dict) and entry.get("sticky"):
            out.add(STICKY + key)
    return out
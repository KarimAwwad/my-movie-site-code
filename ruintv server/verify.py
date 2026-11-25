#!/usr/bin/env python3
"""
verify.py — decide whether a candidate is provably the film. relay.py, source.py, grab.py,
audit.py and verify_test.py all import from here, so the rules can never drift apart.

RUNTIME IS IN SECONDS throughout. TMDB reports minutes; the caller converts once, at the
boundary.

THE BANDS ARE ASYMMETRIC ON PURPOSE. Shorter than the runtime is suspicious: something was
cut, or it is a different film. Longer is normal: cam pre-roll, untrimmed credits, an extended
cut, and TMDB runtimes that are simply short for films still in cinemas. So a lot of extra
length is tolerated, a lot of missing length is not.

Two layers, because a promise is cheap and a download is not:

  precheck    before a byte is fetched. Length inside the band, and for any provider that
              resolves by SEARCH or SCRAPE, the page must name the film. An id-keyed provider
              is trusted on identity by construction; the length band still applies to it.

  postcheck   after the file lands, before it may be filed. The file must match the length the
              source itself promised (a completeness check), hold a real video and a real
              audio stream, carry the film's own language, and still sit inside the band.

An unknown runtime cannot be banded, so it falls to a flat floor and the verdict is
UNVERIFIED. Unverified is only used when nothing verified exists, and it is recorded in
review.jsonl so it can be looked at later without blocking anyone.
"""

from __future__ import annotations

import re
import unicodedata

PRE_LOW = 0.10             # shorter than the runtime by more than this: rejected
PRE_HIGH = 0.25            # longer by more than this: rejected
POST_LOW = 0.15
POST_HIGH = 0.25
COMPLETE_TOL = 0.05        # the file against the length the source promised
EVIDENCE_MIN = 0.80

MIN_SECONDS = 480          # flat floor when the runtime is known but tiny
MIN_SECONDS_UNKNOWN = 300  # flat floor when TMDB has no runtime at all
MAX_SECONDS = 6 * 3600     # nothing longer than this is a film

VERIFIED = "verified"
UNVERIFIED = "unverified"
REJECTED = "rejected"

LANG_ANY = {"", "und", "mul", "zxx"}          # an untagged track proves nothing either way
LANG_ALIAS = {
    "en": "eng",
    "es": "spa",
    "fr": "fre", "fra": "fre",
    "de": "ger", "deu": "ger",
    "it": "ita",
    "pt": "por",
    "ru": "rus",
    "ja": "jpn",
    "ko": "kor",
    "zh": "chi", "zho": "chi", "cmn": "chi", "yue": "chi",
    "ar": "ara",
    "hi": "hin",
    "tr": "tur",
    "pl": "pol",
    "nl": "dut", "nld": "dut",
    "sv": "swe",
    "da": "dan",
    "no": "nor", "nb": "nor", "nn": "nor",
    "fi": "fin",
    "cs": "cze", "ces": "cze",
    "el": "gre", "ell": "gre",
    "he": "heb", "iw": "heb",
    "id": "ind", "in": "ind",
    "ms": "may", "msa": "may",
    "th": "tha",
    "vi": "vie",
    "uk": "ukr",
    "ro": "rum", "ron": "rum",
    "hu": "hun",
    "fa": "per", "fas": "per",
    "ta": "tam",
    "te": "tel",
    "bn": "ben",
    "ur": "urd",
    "tl": "tgl", "fil": "tgl",
}

STOP = {
    "the", "and", "of", "a", "an", "in", "on", "to", "for", "with", "by", "at",
    "from", "is", "it", "its", "as", "or", "de", "la", "le", "el", "der", "die",
    "das", "les", "los", "las", "il", "un", "una", "y", "e", "o",
}
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
NORM_RE = re.compile(r"[^a-z0-9]+")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return NORM_RE.sub(" ", text.lower()).strip()


def tokens(title: str) -> list[str]:
    """Significant words of a title. Short function words are dropped."""
    return [w for w in normalise(title).split()
            if len(w) > 2 and w not in STOP or w.isdigit()]


def evidence(blobs, wanted: list[str]) -> float:
    """Fraction of the title's words present across the given strings."""
    if not wanted:
        return 0.0
    haystack = " " + " ".join(normalise(b) for b in blobs if b) + " "
    found = sum(1 for word in wanted if " %s " % word in haystack)
    return found / len(wanted)


def band_ok(seconds: int, runtime: int, low: float, high: float) -> bool:
    """True when the length is compatible with the runtime."""
    if runtime <= 0:
        return seconds >= MIN_SECONDS_UNKNOWN
    if seconds <= 0 or seconds > MAX_SECONDS:
        return False
    if runtime < MIN_SECONDS * 2:                 # a short film: the band would mean nothing
        return seconds >= MIN_SECONDS
    return runtime * (1 - low) <= seconds <= runtime * (1 + high)


def norm_lang(code: str) -> str:
    """Canonicalize ISO-639-1 (2-letter), ISO-639-2 B/T (3-letter), and BCP-47 region tags."""
    raw = (code or "").strip().lower().replace("_", "-")
    if not raw:
        return ""
    base = raw.split("-", 1)[0].strip()
    return LANG_ALIAS.get(base, base)


def audio_ok(audio_lang: str, want_lang: str) -> bool:
    """True when the audio is the film's own language, or carries no tag at all.

    An untagged track is accepted on purpose: plenty of good rips have no language tag, and
    refusing those would cost more than the odd wrong dub.
    """
    want = norm_lang(want_lang)
    have = norm_lang(audio_lang)
    if not want or have in LANG_ANY:
        return True
    return have == want


def precheck(seconds: int, runtime: int, title: str, blobs,
             id_keyed: bool) -> dict:
    """Before fetching. Returns {verdict, why}."""
    wanted = tokens(title)

    # an mp4 handed over by a provider reports no length until it is fetched; the band cannot
    # judge it, but the title still can, so it passes on as unverified rather than being lost
    if seconds <= 0:
        if not id_keyed and wanted and evidence(blobs, wanted) < EVIDENCE_MIN:
            return {"verdict": REJECTED,
                    "why": "source names %.0f%% of the title" % (evidence(blobs, wanted) * 100)}
        return {"verdict": UNVERIFIED, "why": "no length reported"}

    if runtime > 0 and not band_ok(seconds, runtime, PRE_LOW, PRE_HIGH):
        return {"verdict": REJECTED,
                "why": "length %ss vs %ss runtime" % (seconds, runtime)}

    if not band_ok(seconds, runtime, PRE_LOW, PRE_HIGH):   # unknown runtime, under the floor
        return {"verdict": REJECTED, "why": "length %ss under the floor" % seconds}

    if not id_keyed:
        if not wanted:
            return {"verdict": UNVERIFIED, "why": "title has no usable words"}
        score = evidence(blobs, wanted)
        if score < EVIDENCE_MIN:
            return {"verdict": REJECTED,
                    "why": "source names %.0f%% of the title" % (score * 100)}

    if runtime <= 0:
        return {"verdict": UNVERIFIED, "why": "no runtime on TMDB"}
    return {"verdict": VERIFIED, "why": "length and name agree"}


def postcheck(seconds: int, expected: int, runtime: int, has_video: bool,
              has_audio: bool, audio_lang: str = "", want_lang: str = "") -> dict:
    """After the download, before filing.

    expected is the length the source itself claimed. It catches a half-finished
    download, which the runtime band cannot: a truncated file is shorter than the
    source said it would be.
    """
    if not has_video:
        return {"verdict": REJECTED, "why": "no video stream"}
    if not has_audio:
        return {"verdict": REJECTED, "why": "no audio stream"}
    if not audio_ok(audio_lang, want_lang):
        return {"verdict": REJECTED,
                "why": "audio is %s, film is %s" % (audio_lang, want_lang)}
    if expected > 0 and abs(seconds - expected) > expected * COMPLETE_TOL:
        return {"verdict": REJECTED,
                "why": "file is %ss, source promised %ss" % (seconds, expected)}
    if runtime > 0 and not band_ok(seconds, runtime, POST_LOW, POST_HIGH):
        return {"verdict": REJECTED,
                "why": "file is %ss, runtime is %ss" % (seconds, runtime)}
    if runtime <= 0:
        if seconds < MIN_SECONDS_UNKNOWN:
            return {"verdict": REJECTED, "why": "%ss is too short to be a film" % seconds}
        return {"verdict": UNVERIFIED, "why": "no runtime on TMDB"}
    return {"verdict": VERIFIED, "why": "file matches the runtime"}


def file_names_film(name: str, title: str, year: str) -> bool:
    """A release filename has to carry the title and, when known, the year."""
    if not name:
        return False
    wanted = tokens(title)
    if not wanted:
        return True
    if evidence([name], wanted) < EVIDENCE_MIN:
        return False
    if year and year not in name and not YEAR_RE.search(name):
        return False
    return True


def size_sane(size: int, runtime: int) -> bool:
    """Catch a 3-minute clip named like the film: below ~2 MB a minute it is not a feature."""
    if size <= 0:
        return False
    if runtime <= 0:
        return size >= 80 * 1024 * 1024
    minutes = max(1, runtime // 60)
    return size >= min(80, minutes * 2) * 1024 * 1024
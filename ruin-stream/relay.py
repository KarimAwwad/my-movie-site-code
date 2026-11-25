"""
ruin-stream relay — local resolver + HLS proxy + subtitle ranker for RUIN.TO.

    python relay.py          (listens on 0.0.0.0:8787)

GET /resolve?id=<tmdb>&imdb=<tt>    -> first sources, fast; rest via /more
GET /more?id=<tmdb>&since=<n>       -> sources after index n, plus a done flag
GET /status?id=<tmdb>               -> inspect per-provider probe results
GET /mark?id=<tmdb>&p=<provider>&cam=0|1 -> remember a provider's copy as a recording (or clear it)
GET /subs?id=<tmdb>&lang=en         -> ranked tracks for one language
GET /subs?id=<tmdb>&langs=en,ar,fr  -> best track per language for a set
GET /subs?id=<tmdb>&lang=all        -> best track for every language we know
GET /sub?u=<url>&lang=ar            -> CORS-safe, UTF-8 normalized subtitle proxy
GET /dump?id=<tmdb>&p=<name>        -> hop bodies / candidate statuses
GET /grep?id=<tmdb>&p=<name>&q=<re> -> matches inside a hop body
GET /grep2?u=<url>&ref=<url>&q=<re> -> matches inside any URL
GET /hls?u=<url>&ref=<url>[&bare=1] -> proxied playlist / segment / WebVTT
GET /trick?id=<tmdb>&i=<n>&secs=<s> -> seek-bar sprite sheet job (start / poll)
GET /trick/<tmdb>/thumbs.vtt        -> sprite cue sheet
GET /trick/<tmdb>/<sheet>.webp      -> sprite sheet
GET /tricklog[?n=200]               -> tail of relay.log (for a windowless launch)
GET /health

Everything printed also goes to relay.log next to this file, because the launcher usually
starts this with no console attached.
"""

import base64
import http.cookiejar
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8787

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "relay.log")
LOG_MAX_BYTES = 4 * 1024 * 1024
LOG_LOCK = threading.Lock()
LOG_SIZE = 0

MIN_SECONDS = 480
MIN_SECONDS_MASTER = 60
MAX_SOURCES = 12
FAST_S = 2.8
SLOW_S = 18
PER_PROVIDER_S = 18
BG_DEADLINE_S = 35
META_TIMEOUT = 3
JOBS_TTL = 180
HOP_TIMEOUT = 12
PROBE_TIMEOUT = 8
THROTTLE_RETRIES = 3

SEG_CACHE_BYTES = 64 * 1024 * 1024
SEG_CACHE_MAX_ENTRY = 4 * 1024 * 1024
SEG_CACHE = OrderedDict()
SEG_CACHE_USED = 0
SEG_CACHE_LOCK = threading.Lock()

# --- seek-bar trickplay (WebP -> Google Drive pool -> Supabase Postgres) -----------------
TRICK_INTERVAL = 10
TRICK_COLS = 10
TRICK_ROWS = 10
TRICK_W = 288
TRICK_H = 162
TRICK_TARGET_H = 720
TRICK_WEBP_QUALITY = 55
TRICK_MAX_SHEETS = 40
TRICK_MEM_BYTES = 128 * 1024 * 1024
TRICK_MAX_TITLES = 8
TRICK_TIMEOUT = 2400
TRICK_STALL_S = 360
TRICK_RETRY_S = 30
TRICK_MAX_TRIES = 3
GDRIVE_CAP_BYTES = int(14.2 * 1024 * 1024 * 1024)
GDRIVE_CFG_PATH = os.path.join(BASE_DIR, "gdrive_accounts.json")
TRICKS = {}
TRICKS_LOCK = threading.Lock()
GDRIVE_TOKEN_CACHE = {}
FFMPEG_CANDIDATES = (
    os.environ.get("FFMPEG_BIN", ""),
    "ffmpeg",
    r"D:\my development work\development tools\ffmpeg\bin\ffmpeg.exe",
)

SUBS_WORKERS = 10
SUBS_TIMEOUT = 12
SUBS_TTL = 6 * 3600
MAX_SUB_LANGS = 110
SUB_CHUNK = 10
SUB_MAX_VERIFY = 15
SUB_MIN_CUES_PER_MIN = 2.5
SUB_VERIFY_TIMEOUT = 8

DEFAULT_WYZIE_KEY = "wyzie-csmoxejnludklwa0im6d9g5rwbjn1e3r"

SUB_SOURCE_ORDER = "all"
SUB_SOURCE_BONUS = {
    "subdl": 38,
    "charlie": 34,
    "oscar": 30,
    "sierra": 28,
    "xray": 26,
    "quebec": -40,
}
SUB_FLAG_PENALTY = {
    "machine_translated": -120,
    "wrong_language": -120,
    "too_few_cues": -45,
    "bad_timing": -25,
    "overlapping_cues": -8,
    "leftover_ads": -6,
    "encoding_problems": -10,
}
SUB_ORIGIN_BONUS = {"WEB-DL": 16, "BLURAY": 14, "WEBRIP": 11, "WEB": 9, "HDTV": 4}
SUB_BAD_TOKENS = ("machine", "gtrans", "auto-translat", "ai-translat", "google", "deepl", "bing")
SUB_FORCED_RE = re.compile(
    r"\b(forced|signs[\s._-]*only|songs[\s._-]*and[\s._-]*signs|foreign[\s._-]*parts|non[\s._-]*english)\b",
    re.I,
)
SUB_PARTIAL_TOKENS = ("sample", "trailer")
ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
WYZIE_PROMO_RE = re.compile(
    r"(?:^|\n\n)(?:\d+\n)?\d{2}:\d{2}:0[0-9][.,]\d{3}\s*-->\s*\d{2}:\d{2}:0[0-9][.,]\d{3}[^\n]*\n"
    r"[\s\S]*?(?:sub\.wyzie\.io|free plan\. Unlock every source)[\s\S]*?(?=\n\n|$)",
    re.I,
)

AR_CREDIT_RE = re.compile(
    r"(ترجمة|تعديل|دمج|مراجعة|تصحيح|إعداد|تنسيق|مترجم|فريق|subscene|opensubtitles|"
    r"arabseed|egybest|fasel|cima|movizland|mycima|akwam|akoam)",
    re.I,
)
AR_CALQUE_RE = re.compile(
    r"(^|\s)(هيا يا\s|ما الجحيم|اللعنة المقدسة|أعني،|أتعلم ماذا|أنت تمزح معي|"
    r"هل تمزح معي|ابن العاهرة|ابن الكلبة|يا رجل\.?$)",
    re.M,
)
AR_PRONOUN_START_RE = re.compile(r"^(?:أنا|أنت|أنتِ|نحن|هو|هي|هم)\s+")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
RETRY_STATUS = {0, 429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 2
RETRY_PAUSE = 0.4

SSL_CTX = ssl._create_unverified_context()
LOCAL = threading.local()

PRIVATE_PREFIXES = ("127.", "10.", "192.168.", "169.254.", "0.", "[::1]", "localhost")
PRIVATE_172 = re.compile(r"^172\.(1[6-9]|2\d|3[01])\.")

ENC_API = "https://enc-dec.app/api"
VSRC_KEYS_FALLBACK = ("FWsfu0KQd9vxYGNB", "8z5Ag5wgagfsOuhz")
SUB_LANG_NAMES = {
    "english": "en", "arabic": "ar", "spanish": "es", "french": "fr", "german": "de",
    "italian": "it", "portuguese": "pt", "russian": "ru", "turkish": "tr", "hindi": "hi",
    "urdu": "ur", "bengali": "bn", "indonesian": "id", "malay": "ms", "filipino": "fil",
    "chinese": "zh", "japanese": "ja", "korean": "ko", "dutch": "nl", "polish": "pl",
    "swedish": "sv", "norwegian": "no", "danish": "da", "finnish": "fi", "greek": "el",
    "hebrew": "he", "persian": "fa", "thai": "th", "vietnamese": "vi", "czech": "cs",
    "hungarian": "hu", "romanian": "ro", "ukrainian": "uk", "bulgarian": "bg",
}

ALL_LANGS = [
    "en", "ar", "bg", "zh", "hr", "cs", "da", "nl", "et", "fi", "fr", "de", "el", "he", "hi",
    "hu", "id", "it", "ja", "ko", "lv", "lt", "ms", "no", "fa", "pl", "pt", "pt-br", "ro", "ru",
    "sr", "sk", "sl", "es", "sv", "th", "tr", "uk", "vi", "bn", "ta", "te", "ml", "ur", "fil",
    "sw", "af", "sq", "hy", "az", "be", "bs", "ca", "eu", "gl", "ka", "kk", "km", "ky", "lo",
    "mk", "mn", "mr", "my", "ne", "pa", "si", "so", "uz", "cy", "is", "ga", "mt", "lb", "fo",
    "ps", "ku", "am", "yo", "ig", "ha", "zu", "xh", "st", "tn", "sn", "rw", "tg", "tk", "ug",
    "bo", "dz", "iu", "kl", "se", "sm", "to", "fj", "mi", "haw", "eo", "la", "yi", "gd", "br",
]
LANG_RE = re.compile(r"^[a-z]{2,3}(-[a-z]{2})?$")


def opener():
    existing = getattr(LOCAL, "opener", None)
    if existing is None:
        existing = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=SSL_CTX),
        )
        LOCAL.opener = existing
    return existing


BASE_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
}

M3U8_RE = re.compile(r"https?://[^\s\"'<>\\)]+?\.(?:m3u8|txt)[^\s\"'<>\\)]*", re.I)
REL_M3U8_RE = re.compile(r"[\"'](/[^\"']*\.m3u8[^\"']*)[\"']", re.I)
URL_RE = re.compile(r"https?://[^\s\"'<>\\)]+", re.I)
EXTINF_RE = re.compile(r"#EXTINF:([\d.]+)")
API_PATH_RE = re.compile(r"[\"'`](/[a-z0-9_\-./]*(?:api|stream|source|playlist|manifest|prorcp|srcrcp|server)[a-z0-9_\-./?=&]*)", re.I)
IFRAME_RE = re.compile(r"<(?:iframe|source)[^>]+(?:data-)?src=[\"']([^\"']+)[\"']", re.I)
AD_HOST_RE = re.compile(r"(doubleclick|googlesyndication|adsystem|popads|adsterra|googletagmanager|facebook\.com/tr)", re.I)

STREAM_INF_RE = re.compile(r"#EXT-X-STREAM-INF:([^\r\n]+)")
MEDIA_SUB_RE = re.compile(r'#EXT-X-MEDIA:[^\r\n]*TYPE="?SUBTITLES"?[^\r\n]*', re.I)
ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')
RELEASE_TAG_RE = re.compile(
    r"\b(2160p|1080p|720p|480p|WEB[-_. ]?DL|WEBRip|BluRay|BDRip|BRRip|HDRip|HDTV|"
    r"x264|x265|H\.?264|H\.?265|HEVC|10bit|AAC|DDP5\.1|Atmos|EXTENDED|DIRECTORS\.?CUT|"
    r"UNRATED|THEATRICAL|IMAX|REMASTERED|25fps|24fps|23\.976)\b",
    re.I,
)

# A recording of a cinema screen must never outrank a real digital file, however tall it claims to be:
# an HDCAM rip is often served as "1080p" and still looks worse than a 480p WEB-DL.
CAM_TOKENS = ("hdcam", "camrip", "hqcam", "cam", "telesync", "telecine", "hdts",
              "dvdscr", "screener", "workprint", "pdvd")
DIGITAL_TOKENS = ("web-dl", "webdl", "webrip", "web", "bluray", "blu-ray", "bdrip",
                  "brrip", "remux", "hdtv", "dvdrip")
TS_RE = re.compile(r"(?:^|[\s\-_.\[(])ts(?:[\s\-_.\])]|$)")

# TMDB release type ids: 3 = theatrical, 4 = digital, 5 = physical. Remembered per title for the process lifetime.
CINEMA_CACHE = {}
CINEMA_LOCK = threading.Lock()

# Which host to prefer when two sources are equally unknown (nothing in the URL either way). This is a TIEBREAK,
# never a ranking of its own: the weight is small enough that digital-vs-cam always wins first.
# vixsrc sits last because it is a single-source aggregator that hands out cinema recordings for new films.
PROVIDER_TRUST = {
    "vidsrc": 14, "vidlink": 13, "vidfast": 12, "vidsrc_me": 11, "autoembed": 10,
    "videasy": 9, "2embed": 8, "vidsrcto": 7, "multiembed": 6, "111movies": 5,
    "moviesapi": 4, "videm": 3, "embedsu": 2, "vixsrc": 1,
}
TRUST_WEIGHT = 0.6

# "That copy is a recording" said by hand, per title + provider. A guess cannot know; this can.
CAM_MARKS_PATH = os.path.join(BASE_DIR, "cam_marks.json")
CAM_MARKS = {}
CAM_MARKS_LOCK = threading.Lock()


def is_cam(*blobs):
    text = " ".join(b for b in blobs if b).lower()
    if any(token in text for token in CAM_TOKENS):
        return True
    return TS_RE.search(text) is not None


def mark_key(tmdb, provider):
    return "%s|%s" % (tmdb, provider)


def is_marked_cam(tmdb, provider):
    with CAM_MARKS_LOCK:
        return bool(CAM_MARKS.get(mark_key(tmdb, provider)))


def load_cam_marks():
    try:
        with open(CAM_MARKS_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    with CAM_MARKS_LOCK:
        for key, value in data.items():
            if value:
                CAM_MARKS[key] = True


def save_cam_mark(tmdb, provider, cam):
    with CAM_MARKS_LOCK:
        if cam:
            CAM_MARKS[mark_key(tmdb, provider)] = True
        else:
            CAM_MARKS.pop(mark_key(tmdb, provider), None)
        snapshot = dict(CAM_MARKS)
    try:
        with open(CAM_MARKS_PATH, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=1, sort_keys=True)
    except OSError as exc:
        say("cam mark save failed: %s" % exc)


def cinema_only(tmdb, deadline=None):
    """True = in cinemas, no home release anywhere yet. None = TMDB could not say.

    Provider URLs carry no release name at all (a vidsrc URL is a random host and a token), so a cam rip and a
    WEB-DL are byte-for-byte indistinguishable from the URL. Without this, every vidsrc source would be labelled
    digital even when the film only exists as a recording."""
    key = str(tmdb)
    with CINEMA_LOCK:
        if key in CINEMA_CACHE:
            return CINEMA_CACHE[key]

    api_key = tmdb_key()
    if not api_key:
        return None
    headers = {"User-Agent": UA, "Accept": "application/json", "Authorization": "Bearer " + api_key}
    req = urllib.request.Request("https://api.themoviedb.org/3/movie/%s/release_dates" % tmdb, headers=headers)
    value = None
    try:
        with opener().open(req, timeout=hop_timeout(deadline, 6)) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        types = {entry.get("type")
                 for country in (payload.get("results") or [])
                 for entry in (country.get("release_dates") or [])}
        if types & {4, 5}:
            value = False
        elif 3 in types:
            value = True
    except Exception:
        value = None

    with CINEMA_LOCK:
        CINEMA_CACHE[key] = value
    return value


def quality_rank(src):
    """Higher is better. Used to order the source list so the best copy is always the first one tried.

    Four things, in falling order of importance:

      1. a copy marked as a recording BY HAND loses to everything (-400). That is the only certain signal there is;
      2. a cam TOKEN in the URL or tags (HDCAM, TS, TC...) loses hard (-200), and a GUESS does too but softly (-70);
      3. a digital token (+60) and a progressive MP4 (+30) win, and a source that is neither gets a small nudge;
      4. only then does the height matter, and only slightly (/200). A 1080p HDCAM beating a 480p WEB-DL is exactly
         the bug that made the height a poor tiebreaker in the first place.

    When nothing at all is known the provider trust order decides, so an opaque host that keeps handing out
    recordings does not sit in front of the ones that do not.
    """
    meta = src.get("meta") or {}
    blob = "%s %s %s" % (src.get("direct") or "", src.get("_trickUrl") or "",
                         " ".join(meta.get("tags") or []))
    lowered = blob.lower()
    hard_cam = is_cam(blob)
    score = 0.0
    if src.get("kind") == "mp4":
        score += 30                                   # a progressive file is normally a real digital copy
    if any(token in lowered for token in DIGITAL_TOKENS):
        score += 60
    score += min(to_int(meta.get("height")), 2160) / 200.0
    if meta.get("cam_mark"):
        meta["cam"] = True
        score -= 400
    elif meta.get("cam") or hard_cam:
        meta["cam"] = True
        score -= 200 if hard_cam else 70
    else:
        score += 25
    score += PROVIDER_TRUST.get(src.get("provider") or "", 0) * TRUST_WEIGHT
    return score


def by_quality(sources):
    return sorted(sources, key=quality_rank, reverse=True)


JS_STR = r"['\"]%s['\"]\s*:\s*['\"]((?:[^'\"\\]|\\.)*)['\"]"

SUBS_CACHE = {}
SUBS_LOCK = threading.Lock()

JOBS = {}
JOBS_LOCK = threading.Lock()

# Readable, order-independent labels. The old RUIN-A/B/C were handed out by insertion order, so every re-sort
# shuffled them and the menu letters stopped meaning anything.
PROVIDER_LABELS = {
    "vixsrc": "VIXSRC", "vidsrc": "VIDSRC", "vidlink": "VIDLINK", "vidsrc_me": "VIDSRC-ME",
    "vidfast": "VIDFAST", "autoembed": "AUTOEMBED", "2embed": "2EMBED", "vidsrcto": "VIDSRC-TO",
    "multiembed": "MULTIEMBED", "videm": "VIDEM", "videasy": "VIDEASY", "111movies": "111MOVIES",
    "moviesapi": "MOVIESAPI", "embedsu": "EMBED.SU",
}


def say(message):
    global LOG_SIZE
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), message)
    try:
        print(line, flush=True)
    except (OSError, ValueError):
        pass
    try:
        with LOG_LOCK:
            if LOG_SIZE > LOG_MAX_BYTES:
                return
            with open(LOG_PATH, "a", encoding="utf-8", errors="replace") as handle:
                handle.write(line + "\n")
            LOG_SIZE += len(line) + 1
    except OSError:
        pass


def to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def unescape(value):
    return (value.replace("\\/", "/").replace("\\u0026", "&")
            .replace("\\u003d", "=").replace('\\"', '"'))


def js_field(body, key):
    match = re.search(JS_STR % re.escape(key), body)
    return unescape(match.group(1)) if match else None


def js_fields(body, key):
    return [unescape(m.group(1)) for m in re.finditer(JS_STR % re.escape(key), body)]


def grep(body, pattern, limit=25):
    hits = []
    for match in re.finditer(pattern, body, re.I):
        hits.append(body[max(0, match.start() - 90):match.start() + 170].replace("\n", " "))
        if len(hits) >= limit:
            break
    return hits


def is_private(url):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if not host:
        return True
    if PRIVATE_172.match(host):
        return True
    return any(host.startswith(p) or host == p.strip("[]") for p in PRIVATE_PREFIXES)


def out_of_time(deadline):
    return bool(deadline) and time.time() > deadline


def hop_timeout(deadline, ceiling=HOP_TIMEOUT):
    if not deadline:
        return ceiling
    return max(4, min(ceiling, deadline - time.time()))


def parse_attrs(line):
    return {
        k.upper(): v.strip('"')
        for k, v in ATTR_RE.findall(line)
    }


def inherit_query(child, parent):
    """A child line of a playlist keeps the parent's query string.

    urljoin() throws the query away, and several hosts (vidsrc among them) carry the access token there. That is
    why the manifest loaded and then every segment went out without a token and answered 403: the playlist fetch
    looked fine because it still had the token, the child requests did not.
    """
    if not child or child.startswith(("data:", "blob:")):
        return child
    head, sep, frag = child.partition("#")
    if "?" in head:
        return child
    query = urllib.parse.urlsplit(parent).query
    if not query:
        return child
    out = head + ("&" if "?" in head else "?") + query
    return out + sep + frag if sep else out


def master_variants(master):
    out = []
    attrs = None
    for raw in master.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = parse_attrs(line.split(":", 1)[1])
            continue
        if line.startswith("#"):
            continue
        if attrs is None:
            continue
        height, bandwidth = 0, 0
        res = attrs.get("RESOLUTION", "")
        if "x" in res:
            try:
                height = int(res.split("x")[1])
            except ValueError:
                height = 0
        try:
            bandwidth = int(attrs.get("BANDWIDTH") or 0)
        except ValueError:
            bandwidth = 0
        out.append({"uri": line, "height": height, "bandwidth": bandwidth})
        attrs = None
    return out


def best_variant(master):
    variants = master_variants(master)
    if not variants:
        return None
    return max(variants, key=lambda v: (v["height"], v["bandwidth"]))


def extract_stream_meta(master_text, master_url):
    max_height = 0
    fps = None
    for m in STREAM_INF_RE.finditer(master_text):
        attrs = parse_attrs(m.group(1))
        res = attrs.get("RESOLUTION", "")
        if "x" in res:
            try:
                max_height = max(max_height, int(res.split("x")[1]))
            except ValueError:
                pass
        if attrs.get("FRAME-RATE") and not fps:
            try:
                fps = round(float(attrs["FRAME-RATE"]), 3)
            except ValueError:
                pass

    sub_tracks = []
    for m in MEDIA_SUB_RE.finditer(master_text):
        attrs = parse_attrs(m.group(0))
        uri = attrs.get("URI")
        if uri:
            sub_tracks.append({
                "lang": attrs.get("LANGUAGE", "und"),
                "name": attrs.get("NAME", attrs.get("LANGUAGE", "Track")),
                "url": urllib.parse.urljoin(master_url, uri),
            })

    ref_sub = next(
        (t for t in sub_tracks if t["lang"].lower().startswith("en") or "english" in t["name"].lower()),
        sub_tracks[0] if sub_tracks else None,
    )

    tags = list(dict.fromkeys(m.group(1).upper() for m in RELEASE_TAG_RE.finditer(master_url)))
    if max_height and "%dP" % max_height not in tags:
        tags.insert(0, "%dP" % max_height)

    return {
        "height": max_height or None,
        "fps": fps,
        "tags": tags,
        "hasRefSubs": bool(ref_sub),
        "refSubUrl": ref_sub["url"] if ref_sub else None,
        "subTracks": sub_tracks,
        "cam": is_cam(master_url),
    }


def _read_config_key(name):
    env_val = os.environ.get(name, "").strip()
    if env_val:
        return env_val

    try:
        with open(os.path.join(BASE_DIR, ".env"), encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                k, v = stripped.split("=", 1)
                if k.strip() == name:
                    val = v.strip().strip('"').strip("'")
                    if val:
                        return val
    except OSError:
        pass

    try:
        with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as handle:
            cfg = json.load(handle)
            if isinstance(cfg, dict) and cfg.get(name):
                return str(cfg[name]).strip()
    except (OSError, ValueError):
        pass

    try:
        with open(os.path.join(BASE_DIR, "wrangler.toml"), encoding="utf-8") as handle:
            match = re.search(r'%s\s*=\s*"([^"]+)"' % re.escape(name), handle.read())
            if match:
                return match.group(1).strip()
    except OSError:
        pass

    return ""


def tmdb_key():
    return _read_config_key("TMDB_KEY")


def wyzie_key():
    return _read_config_key("WYZIE_KEY") or DEFAULT_WYZIE_KEY


def subdl_key():
    return _read_config_key("SUBDL_KEY")


def vidsrc_key():
    return _read_config_key("VSRC_KEY")


# ------------------------------------------------------------------ fetching

def fetch(url, referer=None, origin=None, accept=None, rng=None, data=None,
          method=None, extra=None, xhr=False, timeout=HOP_TIMEOUT, attempts=None):
    headers = dict(BASE_HEADERS)
    if referer:
        headers["Referer"] = referer
    if origin:
        headers["Origin"] = origin
    if accept:
        headers["Accept"] = accept
    if rng:
        headers["Range"] = rng
    if data is not None:
        headers["Content-Type"] = "application/json"
    if extra:
        headers.update(extra)
    if xhr:
        headers["Sec-Fetch-Dest"] = "empty"
        headers["Sec-Fetch-Mode"] = "cors"

    if attempts is None:
        attempts = RETRY_ATTEMPTS if data is None else 1

    req = urllib.request.Request(
        url, headers=headers, data=data, method=method or ("POST" if data else "GET")
    )
    last = (0, {}, b"")

    for attempt in range(attempts):
        try:
            with opener().open(req, timeout=timeout) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            last = (exc.code, dict(exc.headers or {}), exc.read())
        except Exception as exc:
            last = (0, {}, str(exc).encode())

        if attempt + 1 < attempts and last[0] in RETRY_STATUS:
            time.sleep(RETRY_PAUSE)
            continue
        break

    return last


def bare_fetch(url, referer, rng=None, deadline=None):
    headers = {"User-Agent": UA, "Accept": "*/*", "Referer": referer}
    if rng:
        headers["Range"] = rng
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener().open(req, timeout=hop_timeout(deadline)) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read()
    except Exception as exc:
        return 0, {}, str(exc).encode()


def bare_get(url, referer, deadline=None):
    status, _, body = bare_fetch(url, referer, deadline=deadline)
    return status, body.decode("utf-8", "replace")


def get_text(url, referer=None, extra=None, xhr=False, timeout=HOP_TIMEOUT):
    status, _, body = fetch(url, referer=referer, extra=extra, xhr=xhr, timeout=timeout)
    return status, body.decode("utf-8", "replace")


def get_json(url, referer=None, origin=None, data=None, method=None, extra=None,
             xhr=False, timeout=HOP_TIMEOUT):
    status, _, body = fetch(
        url, referer=referer, origin=origin, accept="application/json",
        data=data, method=method, extra=extra, xhr=xhr, timeout=timeout,
    )
    try:
        return status, json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return status, None


# ------------------------------------------------------------- segment cache

def seg_cache_get(key):
    with SEG_CACHE_LOCK:
        hit = SEG_CACHE.get(key)
        if hit is None:
            return None
        SEG_CACHE.move_to_end(key)
        return hit


def seg_cache_put(key, ctype, body):
    global SEG_CACHE_USED
    if not body or len(body) > SEG_CACHE_MAX_ENTRY:
        return
    with SEG_CACHE_LOCK:
        old = SEG_CACHE.pop(key, None)
        if old is not None:
            SEG_CACHE_USED -= len(old[1])
        SEG_CACHE[key] = (ctype, body)
        SEG_CACHE_USED += len(body)
        while SEG_CACHE_USED > SEG_CACHE_BYTES and SEG_CACHE:
            _, evicted = SEG_CACHE.popitem(last=False)
            SEG_CACHE_USED -= len(evicted[1])


# ---------------------------------------------------------------- trickplay

def ffmpeg_bin():
    cached = getattr(ffmpeg_bin, "value", None)
    if cached is not None:
        return cached
    found = ""
    for candidate in FFMPEG_CANDIDATES:
        if not candidate:
            continue
        if os.path.isabs(candidate):
            if os.path.isfile(candidate):
                found = candidate
                break
        else:
            hit = shutil.which(candidate)
            if hit:
                found = hit
                break
    ffmpeg_bin.value = found
    if not found:
        say("trick: ffmpeg not found, set FFMPEG_BIN")
    return found


def vtt_time(secs):
    secs = max(0, int(secs))
    return "%02d:%02d:%02d.000" % (secs // 3600, (secs % 3600) // 60, secs % 60)


def trick_bytes():
    return sum(len(body) for entry in TRICKS.values() for body in entry["sheets"].values())


def trick_evict():
    with TRICKS_LOCK:
        finished = [k for k, v in TRICKS.items() if v["state"] == "ready" and not v.get("building")]
        while len(finished) > TRICK_MAX_TITLES:
            TRICKS.pop(finished.pop(0), None)
        while trick_bytes() > TRICK_MEM_BYTES and finished:
            TRICKS.pop(finished.pop(0), None)


def supabase_cfg():
    return _read_config_key("SUPABASE_URL").rstrip("/"), _read_config_key("SUPABASE_KEY")


def supabase_get_trick(tmdb):
    sb_url, sb_key = supabase_cfg()
    if not sb_url or not sb_key:
        return None
    url = "%s/rest/v1/trickplay?tmdb_id=eq.%s&select=*" % (sb_url, urllib.parse.quote(tmdb))
    headers = {
        "apikey": sb_key,
        "Authorization": "Bearer " + sb_key,
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener().open(req, timeout=8) as resp:
            rows = json.loads(resp.read().decode("utf-8", "replace"))
            return rows[0] if isinstance(rows, list) and rows else None
    except Exception as exc:
        say("trick supabase get err: %s" % exc)
        return None


def supabase_save_trick(row):
    sb_url, sb_key = supabase_cfg()
    if not sb_url or not sb_key:
        return False
    url = "%s/rest/v1/trickplay" % sb_url
    headers = {
        "apikey": sb_key,
        "Authorization": "Bearer " + sb_key,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    req = urllib.request.Request(url, data=json.dumps(row).encode("utf-8"), headers=headers, method="POST")
    try:
        with opener().open(req, timeout=10) as resp:
            return resp.status in (200, 201)
    except Exception as exc:
        say("trick supabase save err: %s" % exc)
        return False


def gdrive_pick_account():
    if not os.path.exists(GDRIVE_CFG_PATH):
        return None, None
    try:
        with open(GDRIVE_CFG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return None, None

    accounts = cfg.get("accounts") or []
    if not accounts:
        return None, None

    usage = {a["email"]: 0 for a in accounts if a.get("email")}
    sb_url, sb_key = supabase_cfg()
    if sb_url and sb_key:
        try:
            req = urllib.request.Request(
                "%s/rest/v1/trickplay?select=account_email,size_bytes" % sb_url,
                headers={"apikey": sb_key, "Authorization": "Bearer " + sb_key},
            )
            with opener().open(req, timeout=8) as resp:
                for r in json.loads(resp.read().decode("utf-8", "replace")):
                    em = r.get("account_email")
                    if em in usage:
                        usage[em] += to_int(r.get("size_bytes"))
        except Exception:
            pass

    for acc in accounts:
        em = acc.get("email")
        if em and usage.get(em, 0) < GDRIVE_CAP_BYTES:
            return cfg, acc
    return cfg, accounts[-1]


def gdrive_access_token(cfg, acc):
    email = acc["email"]
    cached = GDRIVE_TOKEN_CACHE.get(email)
    if cached and cached[1] > time.time() + 60:
        return cached[0]

    data = urllib.parse.urlencode({
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": acc["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with opener().open(req, timeout=12) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    token = payload["access_token"]
    GDRIVE_TOKEN_CACHE[email] = (token, time.time() + int(payload.get("expires_in", 3500)))
    return token


def gdrive_upload_public_webp(token, filename, raw_bytes, folder_id=""):
    boundary = "----RuinTrickBoundary987654321"
    meta_obj = {"name": filename, "mimeType": "image/webp"}
    if folder_id:
        meta_obj["parents"] = [folder_id]
    meta = json.dumps(meta_obj).encode("utf-8")
    body = (
        b"--" + boundary.encode() + b"\r\n"
        b"Content-Type: application/json; charset=UTF-8\r\n\r\n" + meta + b"\r\n"
        b"--" + boundary.encode() + b"\r\n"
        b"Content-Type: image/webp\r\n\r\n" + raw_bytes + b"\r\n"
        b"--" + boundary.encode() + b"--\r\n"
    )
    up_req = urllib.request.Request(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id",
        data=body,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "multipart/related; boundary=" + boundary,
        },
        method="POST",
    )
    with opener().open(up_req, timeout=30) as resp:
        file_id = json.loads(resp.read().decode("utf-8", "replace"))["id"]

    perm_req = urllib.request.Request(
        "https://www.googleapis.com/drive/v3/files/%s/permissions" % file_id,
        data=b'{"role":"reader","type":"anyone"}',
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with opener().open(perm_req, timeout=15) as resp:
        resp.read()

    return file_id


def trick_build_vtt(sheet_refs, duration):
    per_sheet = TRICK_COLS * TRICK_ROWS
    total = len(sheet_refs) * per_sheet
    if duration > 0:
        total = min(total, int(duration / TRICK_INTERVAL) + 1)

    lines = ["WEBVTT", ""]
    for index in range(total):
        start = index * TRICK_INTERVAL
        ref = sheet_refs[index // per_sheet]
        tile = index % per_sheet
        x = (tile % TRICK_COLS) * TRICK_W
        y = (tile // TRICK_COLS) * TRICK_H
        lines.append("%s --> %s" % (vtt_time(start), vtt_time(start + TRICK_INTERVAL)))
        lines.append("%s#xywh=%d,%d,%d,%d" % (ref, x, y, TRICK_W, TRICK_H))
        lines.append("")
    return "\n".join(lines), total


def trick_probe(url, referer, bare):
    if bare:
        return bare_fetch(url, referer, deadline=time.time() + PROBE_TIMEOUT)
    return fetch(url, referer=referer, origin=_origin_of(referer), accept="*/*",
                 xhr=True, timeout=PROBE_TIMEOUT, attempts=1)


def trick_source_url(src):
    referer = src.get("_referer") or ""
    bare = bool(src.get("bare"))
    master = src.get("_trickUrl") or src.get("direct") or ""
    if not master:
        return "", referer, bare
    # never cut from the relay's own /hls URL: ffmpeg would have to repeat the referer dance the browser does
    if "127.0.0.1" in master or "localhost" in master:
        master = src.get("direct") or master
    if src.get("kind") not in ("hls", None):
        return master, referer, bare

    status, _, body = trick_probe(master, referer, bare)
    if status != 200:
        say("trick: master %d, cutting from it anyway" % status)
        return master, referer, bare

    variants = [v for v in master_variants(body.decode("utf-8", "replace")) if v["uri"]]
    if not variants:
        return master, referer, bare

    sized = [v for v in variants if v["height"]]
    if sized:
        pick = min(sized, key=lambda v: (abs(v["height"] - TRICK_TARGET_H), -v["height"]))
    else:
        pick = min(variants, key=lambda v: v["bandwidth"] or 10 ** 9)
    say("trick: cutting from %dp of %d rendition(s)" % (pick["height"] or 0, len(variants)))

    return urllib.parse.urljoin(master, inherit_query(pick["uri"], master)), referer, bare


def trick_fail(tmdb, entry, message):
    entry.update(
        state="failed", building=False, error=message,
        retry_at=time.time() + TRICK_RETRY_S,
        tries=entry.get("tries", 0) + 1,
    )
    say("trick %s failed %d/%d: %s"
        % (tmdb, entry["tries"], TRICK_MAX_TRIES, message))


def trick_live(tmdb, force=False):
    if force:
        with TRICKS_LOCK:
            TRICKS.pop(tmdb, None)
        return None
    with TRICKS_LOCK:
        entry = TRICKS.get(tmdb)
    if entry is not None:
        if entry["state"] in ("ready", "pending"):
            return entry
        if entry.get("tries", 0) >= TRICK_MAX_TRIES or time.time() < entry.get("retry_at", 0):
            return entry
        return None

    row = supabase_get_trick(tmdb)
    if row and row.get("vtt_text"):
        entry = {
            "state": "ready", "building": False, "sheets": {}, "vtt": row["vtt_text"],
            "sheet_ids": row.get("sheet_ids") or [],
            "frames": to_int(row.get("frames")), "done": to_int(row.get("frames")),
            "interval": to_int(row.get("interval"), TRICK_INTERVAL),
            "cols": to_int(row.get("cols"), TRICK_COLS),
            "rows": to_int(row.get("rows"), TRICK_ROWS),
            "w": to_int(row.get("w"), TRICK_W),
            "h": to_int(row.get("h"), TRICK_H),
            "started": time.time(), "error": "", "tries": 0, "retry_at": 0.0,
        }
        with TRICKS_LOCK:
            TRICKS[tmdb] = entry
        return entry
    return None


def trick_start(tmdb, url, referer, bare, duration):
    with TRICKS_LOCK:
        entry = TRICKS.get(tmdb)
        if entry is not None and entry["state"] in ("pending", "ready"):
            return entry
        if entry is None:
            entry = {
                "state": "pending", "building": True, "sheets": {}, "sheet_ids": [],
                "vtt": "", "frames": 0, "done": 0,
                "interval": TRICK_INTERVAL, "cols": TRICK_COLS, "rows": TRICK_ROWS,
                "w": TRICK_W, "h": TRICK_H, "started": time.time(), "error": "",
                "tries": 0, "retry_at": 0.0, "url": url, "referer": referer,
            }
            TRICKS[tmdb] = entry
        else:
            entry.update(state="pending", building=True, error="", sheets={}, sheet_ids=[],
                         vtt="", frames=0, done=0, url=url, referer=referer)
    trick_evict()
    say("trick %s: starting cut, %.0fs long" % (tmdb, duration))
    threading.Thread(target=trick_build, args=(tmdb, url, referer, bare, duration),
                     daemon=True).start()
    return entry


def trick_build(tmdb, url, referer, bare, duration):
    entry = TRICKS.get(tmdb)
    if entry is None:
        return
    binary = ffmpeg_bin()
    if not binary:
        trick_fail(tmdb, entry, "ffmpeg not found")
        return

    headers = ""
    if referer:
        headers = "Referer: %s\r\n" % referer
        origin = _origin_of(referer)
        if origin and not bare:
            headers += "Origin: %s\r\n" % origin

    tmp = tempfile.mkdtemp(prefix="ruin_trick_")
    proc = None
    try:
        cmd = [
            binary, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-extension_picky", "0", "-allowed_extensions", "ALL", "-f", "hls",
            "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
            "-reconnect", "1", "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5", "-rw_timeout", "20000000",
            "-user_agent", UA,
        ]
        if headers:
            cmd += ["-headers", headers]
        cmd += [
            "-skip_frame", "nokey",
            "-i", url,
            "-map", "0:v:0", "-an", "-sn", "-dn",
            "-vf", ("fps=1/%d,scale=%d:%d:force_original_aspect_ratio=decrease,"
                    "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,tile=%dx%d"
                    % (TRICK_INTERVAL, TRICK_W, TRICK_H, TRICK_W, TRICK_H, TRICK_COLS, TRICK_ROWS)),
            "-fps_mode", "passthrough",
            "-c:v", "libwebp", "-quality", str(TRICK_WEBP_QUALITY), "-compression_level", "4",
            "-frames:v", str(TRICK_MAX_SHEETS),
            "-start_number", "0",
            os.path.join(tmp, "s%03d.webp"),
        ]

        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        errors = []

        def read_errors():
            for raw in proc.stderr:
                text = raw.decode("utf-8", "replace").strip()
                if text:
                    errors.append(text)

        threading.Thread(target=read_errors, daemon=True).start()

        killed = ""
        made = 0
        published = 0
        moved = time.time()
        deadline = time.time() + TRICK_TIMEOUT
        while proc.poll() is None:
            time.sleep(3)
            now = time.time()
            current_files = sorted(f for f in os.listdir(tmp) if f.endswith(".webp"))
            count = len(current_files)
            if count != made:
                made = count
                moved = now
                entry["done"] = made * TRICK_COLS * TRICK_ROWS
                say("trick %s: %d sheet(s) written" % (tmdb, made))

                closed_files = current_files[:-1]
                if len(closed_files) > published:
                    sheets = dict(entry["sheets"])
                    for name in closed_files:
                        if name not in sheets:
                            try:
                                with open(os.path.join(tmp, name), "rb") as handle:
                                    sheets[name] = handle.read()
                            except OSError:
                                pass
                    ready_names = sorted(sheets.keys())
                    if ready_names:
                        vtt_text, total_frames = trick_build_vtt(ready_names, duration)
                        entry.update(
                            state="ready",
                            sheets=sheets,
                            vtt=vtt_text,
                            frames=total_frames,
                            error="",
                        )
                        published = len(ready_names)
            elif now - moved > TRICK_STALL_S:
                killed = "no new sheet for %ds at %d sheet(s)" % (TRICK_STALL_S, made)
                proc.kill()
                break
            if now > deadline:
                killed = "timed out after %ds at %d sheet(s)" % (TRICK_TIMEOUT, made)
                proc.kill()
                break

        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

        sheets_files = sorted(f for f in os.listdir(tmp) if f.endswith(".webp"))
        if not sheets_files:
            detail = " | ".join(errors[-3:])[-400:] or "no output"
            trick_fail(tmdb, entry, "%s (%s)" % (killed or "no sheets", detail))
            return

        sheets = {}
        total_bytes = 0
        for name in sheets_files:
            with open(os.path.join(tmp, name), "rb") as handle:
                blob = handle.read()
                sheets[name] = blob
                total_bytes += len(blob)

        cfg, acc = gdrive_pick_account()
        cdn_refs = list(sheets_files)
        sheet_ids = []
        uploaded_email = ""
        if cfg and acc:
            try:
                token = gdrive_access_token(cfg, acc)
                folder_id = acc.get("folder_id") or cfg.get("folder_id") or ""
                cdn_refs = []
                for name in sheets_files:
                    fid = gdrive_upload_public_webp(
                        token, "%s_%s" % (tmdb, name), sheets[name], folder_id=folder_id
                    )
                    sheet_ids.append(fid)
                    cdn_refs.append("https://lh3.googleusercontent.com/d/%s=s0" % fid)
                uploaded_email = acc["email"]
                say("trick %s uploaded %d sheet(s) (%.2f MB) to %s"
                    % (tmdb, len(sheet_ids), total_bytes / 1048576, uploaded_email))
            except Exception as up_exc:
                say("trick %s gdrive upload err: %s" % (tmdb, up_exc))
                cdn_refs = list(sheets_files)

        vtt_text, total = trick_build_vtt(cdn_refs, duration)

        if uploaded_email and sheet_ids:
            supabase_save_trick({
                "tmdb_id": tmdb,
                "account_email": uploaded_email,
                "vtt_text": vtt_text,
                "sheet_ids": sheet_ids,
                "frames": total,
                "interval": TRICK_INTERVAL,
                "cols": TRICK_COLS,
                "rows": TRICK_ROWS,
                "w": TRICK_W,
                "h": TRICK_H,
                "size_bytes": total_bytes,
            })

        entry.update(
            state="ready",
            building=False,
            sheets={} if uploaded_email else sheets,
            sheet_ids=sheet_ids,
            vtt=vtt_text,
            frames=total,
            done=total,
            error="",
            retry_at=0.0,
        )
        say("trick %s ready: %d frames in %d sheet(s), %.2f MB%s"
            % (tmdb, total, len(sheets_files), total_bytes / 1048576,
               " (partial: %s)" % killed if killed else ""))
        trick_evict()
    except Exception as exc:
        trick_fail(tmdb, entry, str(exc))
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


# -------------------------------------------------------------------- helpers

def playlists(text):
    if not text:
        return []
    cleaned = unescape(text)
    out = M3U8_RE.findall(cleaned)
    out += [u for u in REL_M3U8_RE.findall(cleaned) if not u.startswith("http")]
    out += js_fields(cleaned, "file")
    out += js_fields(cleaned, "hls")
    out += [u for u in js_fields(cleaned, "url") if any(k in u for k in (".m3u8", "/hls/", "playlist", "master"))]
    return list(dict.fromkeys(out))


def all_urls(text):
    if not text:
        return []
    return list(dict.fromkeys(URL_RE.findall(unescape(text))))


def absolutize(candidates, base):
    return [u if u.startswith("http") else urllib.parse.urljoin(base, u) for u in candidates]


def duration(playlist):
    return sum(float(x) for x in EXTINF_RE.findall(playlist))


def _origin_of(url):
    p = urllib.parse.urlsplit(url)
    return "%s://%s" % (p.scheme, p.netloc) if p.scheme and p.netloc else None


def with_scheme(host):
    value = (host or "").strip().rstrip("/")
    if not value:
        return ""
    if not value.startswith("http"):
        value = "https://" + value
    return value


def b64url_decode(text):
    cleaned = re.sub(r"\s+", "", text).replace("_", "/").replace("-", "+")
    cleaned += "=" * (-len(cleaned) % 4)
    return base64.b64decode(cleaned)


def rc4(key, data):
    state = list(range(256))
    key_bytes = key.encode("utf-8")
    j = 0
    for i in range(256):
        j = (j + state[i] + key_bytes[i % len(key_bytes)]) & 0xFF
        state[i], state[j] = state[j], state[i]
    i = j = 0
    out = bytearray()
    for byte in data:
        i = (i + 1) & 0xFF
        j = (j + state[i]) & 0xFF
        state[i], state[j] = state[j], state[i]
        out.append(byte ^ state[(state[i] + state[j]) & 0xFF])
    return bytes(out)


def looks_encrypted(value):
    if not isinstance(value, str) or len(value) < 32:
        return False
    if value.startswith("http") or " " in value:
        return False
    return re.fullmatch(r"[A-Za-z0-9_\-+/=]+", value) is not None


def url_ish(text):
    return bool(text) and "http" in text and any(
        token in text for token in (".m3u8", "/hls/", ".mp4", "master", "/playlist", "manifest", "/pl/")
    )


def walk_strings(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk_strings(value, "%s.%s" % (path, key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_strings(value, "%s[%d]" % (path, index))
    elif isinstance(node, str):
        yield path, node


def vidsrc_keys(token):
    keys = []
    override = vidsrc_key()
    if override:
        keys.append(override)
    keys.extend(VSRC_KEYS_FALLBACK)
    if token:
        parts = token.split(".")
        keys.append(token)
        if len(parts) > 1:
            keys.append(parts[1])
            keys.append(parts[-1])
        try:
            payload = b64url_decode(parts[0]).decode("utf-8", "replace")
            keys.append(payload)
            found = re.search(r'"k"\s*:\s*"([^"]+)"', payload)
            if found:
                keys.append(found.group(1))
        except Exception:
            pass
    return [k for k in dict.fromkeys(keys) if k]


def vs_decrypt(value, keys):
    try:
        raw = b64url_decode(value)
    except Exception:
        return None
    for key in keys:
        try:
            text = urllib.parse.unquote(rc4(key, raw).decode("utf-8", "replace"))
        except Exception:
            continue
        if url_ish(text):
            return text, key
    return None


VS_BRIDGE = r'''
const {readFileSync} = require("fs");
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";
(async () => {
  const job = JSON.parse(readFileSync(0, "utf-8"));
  const r = await fetch(job.wasm_url, {headers: {"user-agent": UA, referer: "https://vidsrc.sh/"}});
  if (r.status !== 200) { process.exit(3); }
  const mod = await WebAssembly.compile(new Uint8Array(await r.arrayBuffer()));
  const inst = await WebAssembly.instantiate(mod, {});
  const ct = Buffer.from(job.ct, "base64");
  const ptr = inst.exports.alloc(ct.length);
  new Uint8Array(inst.exports.memory.buffer, ptr, ct.length).set(ct);
  const outLen = inst.exports.decrypt(ptr, ct.length);
  const txt = new TextDecoder().decode(new Uint8Array(inst.exports.memory.buffer, ptr + 12, outLen));
  process.stdout.write(JSON.stringify(txt.split("\n").filter(Boolean)));
})();
'''

_BRIDGE_PATH = None
_BRIDGE_LOCK = threading.Lock()
_NODE_BIN = None
_NODE_DONE = False


def node_bin():
    global _NODE_BIN, _NODE_DONE
    if _NODE_DONE:
        return _NODE_BIN
    with _BRIDGE_LOCK:
        if not _NODE_DONE:
            _NODE_BIN = shutil.which("node") or shutil.which("node.exe")
            _NODE_DONE = True
    return _NODE_BIN


def bridge_path():
    global _BRIDGE_PATH
    with _BRIDGE_LOCK:
        if _BRIDGE_PATH and os.path.exists(_BRIDGE_PATH):
            return _BRIDGE_PATH
        path = os.path.join(tempfile.gettempdir(), "ruin_vs_bridge.js")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(VS_BRIDGE)
        _BRIDGE_PATH = path
        return path


def vs_wasm_decrypt(cipher_b64, wasm_url, log, deadline):
    binary = node_bin()
    if not binary:
        log.append("no node")
        return None
    try:
        proc = subprocess.run(
            [binary, bridge_path()],
            input=json.dumps({"ct": cipher_b64, "wasm_url": wasm_url}).encode(),
            capture_output=True, timeout=hop_timeout(deadline, 20),
        )
    except Exception as exc:
        log.append("node err %s" % exc)
        return None
    if proc.returncode != 0:
        log.append("node rc=%d" % proc.returncode)
        return None
    try:
        urls = json.loads(proc.stdout.decode("utf-8", "replace"))
    except Exception:
        log.append("node no json")
        return None
    if isinstance(urls, list) and urls:
        return "\n".join(u for u in urls if isinstance(u, str))
    return None


def stamp_token(url, token):
    base = url.split("#")[0].split("?")[0]
    return base + "?token=" + urllib.parse.quote(token)


def first_valid(candidates, referer, log, deadline=None):
    ref_origin = _origin_of(referer)
    for url in absolutize(list(dict.fromkeys(candidates)), referer)[:24]:
        if out_of_time(deadline):
            log.append("deadline while probing")
            return None
        timeout = hop_timeout(deadline, PROBE_TIMEOUT)

        status, _, body = fetch(url, referer=referer, origin=ref_origin, accept="*/*", xhr=True,
                                timeout=timeout, attempts=1)
        if status == 403:
            url_origin = _origin_of(url)
            status, _, body = fetch(url, referer=url_origin + "/" if url_origin else None,
                                    origin=url_origin, accept="*/*", xhr=True,
                                    timeout=timeout, attempts=1)
        if status != 200:
            continue
        text = body.decode("utf-8", "replace")
        if "#EXTM3U" not in text:
            continue

        if "#EXT-X-STREAM-INF" in text:
            pick = best_variant(text)
            child = pick["uri"] if pick else None
            if not child:
                log.append("master no variant %s" % url)
                continue
            if out_of_time(deadline):
                log.append("deadline at master child")
                return None
            child_url = urllib.parse.urljoin(url, inherit_query(child, url))
            cstatus, _, cbody = fetch(child_url, referer=referer, origin=ref_origin, accept="*/*", xhr=True,
                                      timeout=hop_timeout(deadline, PROBE_TIMEOUT), attempts=1)
            if cstatus != 200:
                log.append("master child %d %s" % (cstatus, url))
                continue
            ctext = cbody.decode("utf-8", "replace")
            if "#EXTINF" not in ctext:
                log.append("master child no segments %s" % url)
                continue
            secs = duration(ctext)
            if secs < MIN_SECONDS_MASTER:
                log.append("master short %.0fs %s" % (secs, url))
                continue
            log.append("master %dp %.0fs %s" % (pick["height"] or 0, secs, url))
            return {
                "url": url,
                "secs": secs,
                "referer": referer,
                "meta": extract_stream_meta(text, url),
            }

        secs = duration(text)
        log.append("media %.0fs %s" % (secs, url))
        if secs >= MIN_SECONDS:
            return {"url": url, "secs": secs, "referer": referer, "meta": {"cam": is_cam(url)}}
    return None


def probe_mp4(url, referer, log, deadline=None):
    status, headers, body = fetch(
        url, referer=referer, origin=_origin_of(referer), accept="*/*",
        rng="bytes=0-1", xhr=True, timeout=hop_timeout(deadline, PROBE_TIMEOUT), attempts=1,
    )
    ctype = (headers.get("Content-Type") or "").lower()
    if status in (200, 206) and (body or "video" in ctype or "octet" in ctype):
        log.append("mp4 %d %s" % (status, url[:70]))
        return True
    if status == 429:
        log.append("mp4 429 (throttled, keeping) %s" % url[:70])
        return True
    log.append("mp4 dead %d %s" % (status, url[:70]))
    return False


def enc_get(path, deadline, **params):
    query = urllib.parse.urlencode(params)
    status, payload = get_json("%s/%s?%s" % (ENC_API, path, query),
                               timeout=hop_timeout(deadline, SUBS_TIMEOUT))
    if status != 200 or not isinstance(payload, dict):
        return None
    if str(payload.get("status")) != "200":
        return None
    return payload.get("result")


def enc_post(path, deadline, **body):
    for field in ("text", "result", "data"):
        if field not in body:
            continue
        status, payload = get_json(
            "%s/%s" % (ENC_API, path), data=json.dumps(dict(body)).encode(),
            timeout=hop_timeout(deadline, SUBS_TIMEOUT),
        )
        if status == 200 and isinstance(payload, dict) and str(payload.get("status")) == "200":
            return payload.get("result")
    return None


def imdb_id(tmdb, key, log, deadline=None):
    if not key:
        log.append("tmdb no key")
        return None
    headers = {"User-Agent": UA, "Accept": "application/json", "Authorization": "Bearer " + key}
    for path in ("/movie/%s/external_ids" % tmdb, "/movie/%s" % tmdb):
        if out_of_time(deadline):
            log.append("tmdb deadline")
            break
        req = urllib.request.Request("https://api.themoviedb.org/3" + path, headers=headers)
        try:
            with opener().open(req, timeout=hop_timeout(deadline)) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            log.append("tmdb 200 " + path)
            if payload.get("imdb_id"):
                return payload["imdb_id"]
        except Exception as exc:
            log.append("tmdb err " + str(exc))
    return None


def tmdb_meta(tmdb, deadline=None):
    key = tmdb_key()
    if not key:
        return None
    headers = {"User-Agent": UA, "Accept": "application/json", "Authorization": "Bearer " + key}
    req = urllib.request.Request("https://api.themoviedb.org/3/movie/%s" % tmdb, headers=headers)
    try:
        with opener().open(req, timeout=hop_timeout(deadline)) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return {
        "title": payload.get("title") or payload.get("original_title") or "",
        "year": (payload.get("release_date") or "")[:4],
        "runtime": to_int(payload.get("runtime")),
    }


def quoted(value):
    return urllib.parse.quote(value, safe="")


def vidsrc_session(tmdb, deadline=None):
    sh = "https://vidsrc.sh"
    referer = sh + "/embed/movie/%s/" % tmdb
    status, src = get_json(sh + "/vs_src.php?type=movie&id=" + tmdb, referer=referer,
                           timeout=hop_timeout(deadline))
    landing = (src or {}).get("src") if isinstance(src, dict) else None
    if not landing:
        return None
    if out_of_time(deadline):
        return None
    status, page = get_text(landing, referer=referer, timeout=hop_timeout(deadline))
    player = js_field(page, "playerUrl")
    if not player:
        return None
    if not player.startswith("http"):
        player = "https://stellarconductornexus.com" + player
    if out_of_time(deadline):
        return None
    status, body = get_text(player, referer=landing, timeout=hop_timeout(deadline))
    if not body:
        return None

    token = js_field(body, "apiToken")

    pool = None
    meta = js_field(body, "metaApi")
    if meta:
        result = {}
        done = threading.Event()

        def lookup():
            try:
                st, meta_json = get_json(meta, referer=player, xhr=True, timeout=META_TIMEOUT)
                if isinstance(meta_json, dict):
                    result["pool"] = (meta_json.get("data") or {}).get("stream_urls_api_host")
            except Exception:
                pass
            done.set()

        threading.Thread(target=lookup, daemon=True).start()
        done.wait(META_TIMEOUT + 1)
        pool = result.get("pool")

    return {
        "player": player,
        "landing": landing,
        "body": body,
        "api": js_field(body, "api"),
        "apiToken": token,
        "token": token,
        "pool": with_scheme(pool) or None,
    }


def vidsrc_url(session, use_pool=True, header=None):
    api = session["api"] or ""
    if api and not api.startswith("http"):
        api = urllib.parse.urljoin(session["player"], api)
    if use_pool and session["pool"]:
        api = re.sub(r"^https?://[^/]+", session["pool"], api)
    token = session["token"]
    if not api or not token:
        return None, {}
    url = api + ("&" if "?" in api else "?") + "api_token=" + urllib.parse.quote(token)
    extra = {}
    if header == "bearer":
        extra["Authorization"] = "Bearer " + token
    elif header == "cookie":
        extra["Cookie"] = "api_token=" + token
    return url, extra


# ----------------------------------------------------------------- providers

def p_vidsrc(tmdb, get_imdb, log, deadline):
    session = vidsrc_session(tmdb, deadline)
    if not session:
        log.append("no session")
        return None
    player = session["player"]
    pool = session["pool"]
    api_token = session["apiToken"]
    if not pool:
        log.append("no pool")
        return None
    if not api_token:
        log.append("no apiToken")
        return None
    if out_of_time(deadline):
        return None
    log.append("pool %s" % pool)

    try:
        return _vidsrc_flow(session, player, pool, api_token, log, deadline)
    except Exception as exc:
        log.append("exc %s" % exc)
        return None


def _vidsrc_flow(session, player, pool, api_token, log, deadline):
    api = session["api"] or ""
    if not api:
        log.append("no api")
        return None
    if not api.startswith("http"):
        api = urllib.parse.urljoin(player, api)
    api = re.sub(r"^https?://[^/]+", pool, api)
    if "stream_urls" not in api:
        api += "&stream_urls"
    url = api + ("&" if "?" in api else "?") + "api_token=" + urllib.parse.quote(api_token)

    status, body = bare_get(url, player, deadline)
    log.append("api %d len=%d" % (status, len(body)))
    if status != 200 or not body.strip():
        return None

    try:
        plain = json.loads(body)
    except Exception:
        log.append("no json")
        return None

    data = plain.get("data") or {}
    raw = data.get("stream_urls")
    masters = []

    if isinstance(raw, list):
        masters = [m for m in raw if isinstance(m, str) and m.startswith("http")]
    elif isinstance(raw, str) and raw:
        vs = plain.get("vs") or {}
        wasm_url = vs.get("wasm_url")
        text = None
        if wasm_url:
            text = vs_wasm_decrypt(raw, wasm_url, log, deadline)
        if not text:
            hit = vs_decrypt(raw.strip(), vidsrc_keys(api_token))
            text = hit[0] if hit else None
            if hit:
                log.append("rc4 %s" % hit[1])
        if text:
            masters = [m.strip() for m in text.split("\n") if m.strip().startswith("http")]

    if not masters:
        log.append("no masters")
        return None
    log.append("masters %d" % len(masters))

    gstatus, gtok = bare_get(pool + "/generate.php?api_token=" + urllib.parse.quote(api_token),
                             player, deadline)
    gtok = (gtok or "").strip()
    log.append("gen %d len=%d" % (gstatus, len(gtok)))
    if gstatus != 200 or len(gtok) < 40:
        return None

    hits = []
    for master in masters[:2]:
        if out_of_time(deadline):
            break
        master_url = stamp_token(master, gtok)
        mstatus, mtext = bare_get(master_url, player, deadline)
        log.append("master %d" % mstatus)
        if mstatus != 200 or "#EXTM3U" not in mtext:
            continue

        pick = best_variant(mtext)
        if not pick:
            log.append("no variant")
            continue

        # the token lives in the master's query, and urljoin() drops it: put it back on the variant
        variant_url = stamp_token(urllib.parse.urljoin(master_url, pick["uri"]), gtok)
        vstatus, vtext = bare_get(variant_url, player, deadline)
        if vstatus != 200 or "#EXTINF" not in vtext:
            log.append("variant %d" % vstatus)
            continue

        secs = duration(vtext)
        if secs < MIN_SECONDS:
            log.append("short %.0fs" % secs)
            continue

        hits.append({
            "url": variant_url,
            "secs": secs,
            "referer": player,
            "kind": "hls",
            "bare": True,
            "trick": master_url,
            "meta": {
                "height": pick["height"] or None,
                "tags": ["%dP" % pick["height"]] if pick["height"] else [],
                "cam": is_cam(master_url),
            },
        })
        log.append("hit %dp %.0fs" % (pick["height"] or 0, secs))
        if len(hits) >= 2:
            break

    return hits or None


def p_vidsrc_me(tmdb, get_imdb, log, deadline):
    ident = get_imdb() or tmdb
    hosts = ("https://vidsrc.xyz", "https://vidsrc.me", "https://vidsrc.in", "https://vidsrc.pm")
    for host in hosts:
        if out_of_time(deadline):
            break
        embed_url = "%s/embed/movie/%s" % (host, ident)
        st, page = get_text(embed_url, referer=host + "/", timeout=hop_timeout(deadline))
        log.append("embed %s %d len=%d" % (host, st, len(page)))
        if st != 200 or not page:
            continue

        direct = playlists(page)
        if direct:
            hit = first_valid(direct, embed_url, log, deadline)
            if hit:
                return hit

        iframes = [u for u in IFRAME_RE.findall(page) if not AD_HOST_RE.search(u)]
        for raw_rcp in iframes[:2]:
            if out_of_time(deadline):
                break
            rcp_url = urllib.parse.urljoin(embed_url, unescape(raw_rcp))
            rst, rcp_page = get_text(rcp_url, referer=embed_url, timeout=hop_timeout(deadline))
            log.append("rcp %d len=%d" % (rst, len(rcp_page)))
            if rst != 200 or not rcp_page:
                continue

            found = playlists(rcp_page)
            sub_paths = re.findall(r"['\"](/(?:pro|src)rcp/[^'\"]+)['\"]", rcp_page, re.I)
            sub_paths += [u for u in IFRAME_RE.findall(rcp_page) if not AD_HOST_RE.search(u)]
            for raw_sub in list(dict.fromkeys(sub_paths))[:3]:
                if out_of_time(deadline):
                    break
                sub_url = urllib.parse.urljoin(rcp_url, unescape(raw_sub))
                sst, sub_page = get_text(sub_url, referer=rcp_url, timeout=hop_timeout(deadline))
                log.append("prorcp %d len=%d" % (sst, len(sub_page)))
                if sst == 200 and sub_page:
                    found += playlists(sub_page)
                    found += [u for u in all_urls(sub_page) if ".m3u8" in u or "/hls/" in u]

            hit = first_valid(found, rcp_url, log, deadline)
            if hit:
                return hit
    return None


def scrape_embed(page_url, referer, log, deadline, depth=2):
    visited = set()

    def walk(url, ref, level):
        if url in visited or out_of_time(deadline):
            return []
        visited.add(url)
        status, page = get_text(url, referer=ref, timeout=hop_timeout(deadline))
        log.append("scrape[d%d] %d len=%d" % (level, status, len(page)))
        if status != 200 or not page:
            return []

        found = playlists(page)
        found += [u for u in all_urls(page) if any(k in u for k in (".m3u8", "/hls/", "playlist", "master"))]

        for path in list(dict.fromkeys(API_PATH_RE.findall(page)))[:3]:
            if out_of_time(deadline):
                break
            api_url = path if path.startswith("http") else urllib.parse.urljoin(url, path)
            st, payload = get_json(api_url, referer=url, xhr=True, timeout=hop_timeout(deadline))
            log.append("api %d %s" % (st, path))
            if payload is not None:
                blob = json.dumps(payload)
                found += playlists(blob)
                found += [u for u in all_urls(blob) if any(k in u for k in (".m3u8", "/hls/", "playlist", "master"))]

        if not found and level < depth:
            iframes = [u for u in IFRAME_RE.findall(page) if not AD_HOST_RE.search(u)]
            for raw_iframe in list(dict.fromkeys(iframes))[:2]:
                if out_of_time(deadline):
                    break
                next_url = urllib.parse.urljoin(url, unescape(raw_iframe))
                found += walk(next_url, url, level + 1)

        return found

    return walk(page_url, referer, 0)


def p_autoembed(tmdb, get_imdb, log, deadline):
    for page in (
        "https://player.autoembed.cc/embed/movie/" + tmdb,
        "https://autoembed.co/movie/tmdb/" + tmdb,
    ):
        if out_of_time(deadline):
            break
        hit = first_valid(scrape_embed(page, "https://player.autoembed.cc/", log, deadline), page, log, deadline)
        if hit:
            return hit
    return None


def p_multiembed(tmdb, get_imdb, log, deadline):
    page = "https://multiembed.mov/?video_id=%s&tmdb=1" % tmdb
    return first_valid(scrape_embed(page, "https://multiembed.mov/", log, deadline), page, log, deadline)


def p_vidsrcto(tmdb, get_imdb, log, deadline):
    page = "https://vidsrc.to/embed/movie/" + tmdb
    return first_valid(scrape_embed(page, "https://vidsrc.to/", log, deadline), page, log, deadline)


def p_2embed(tmdb, get_imdb, log, deadline):
    page = "https://www.2embed.cc/embed/" + tmdb
    return first_valid(scrape_embed(page, "https://www.2embed.cc/", log, deadline), page, log, deadline)


def p_111movies(tmdb, get_imdb, log, deadline):
    page = "https://111movies.com/movie/" + tmdb
    return first_valid(scrape_embed(page, "https://111movies.com/", log, deadline), page, log, deadline)


def p_moviesapi(tmdb, get_imdb, log, deadline):
    page = "https://moviesapi.club/movie/" + tmdb
    return first_valid(scrape_embed(page, "https://moviesapi.club/", log, deadline), page, log, deadline)


def p_embedsu(tmdb, get_imdb, log, deadline):
    page = "https://embed.su/embed/movie/" + tmdb
    return first_valid(scrape_embed(page, "https://embed.su/", log, deadline), page, log, deadline)


def caption_lang(name):
    raw = name or ""
    if ARABIC_RE.search(raw):
        return "ar"
    cleaned = raw.lower().strip()
    if cleaned in SUB_LANG_NAMES:
        return SUB_LANG_NAMES[cleaned]
    if re.fullmatch(r"[a-z]{2,3}(-[a-z]{2})?", cleaned):
        return cleaned
    return "und"


def vidlink_expired(url):
    match = re.search(r"[?&]t=(\d{9,12})", url or "")
    return bool(match) and to_int(match.group(1)) < time.time()


def p_vidlink(tmdb, get_imdb, log, deadline):
    referer = "https://vidlink.pro/movie/" + tmdb
    enc_id = enc_get("enc-vidlink", deadline, text=tmdb)
    if not enc_id or not isinstance(enc_id, str):
        log.append("enc fail")
        return None

    api = "https://vidlink.pro/api/b/movie/%s?multiLang=0" % urllib.parse.quote(enc_id, safe="")
    status, _, body = fetch(api, referer=referer, origin="https://vidlink.pro", accept="*/*",
                            xhr=True, timeout=hop_timeout(deadline))
    log.append("api %d len=%d" % (status, len(body)))
    if status != 200 or not body:
        return None

    text = body.decode("utf-8", "replace")
    try:
        data = json.loads(text)
    except Exception:
        data = enc_post("dec-vidlink", deadline, result=text) or enc_post("dec-vidlink", deadline, text=text)
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                data = None
    if not isinstance(data, dict):
        log.append("no json head=%s" % text.strip()[:60])
        return None

    stream = data.get("stream") or {}
    qualities = stream.get("qualities") or {}
    if not isinstance(qualities, dict) or not qualities:
        log.append("no qualities")
        return None

    captions = []
    for cap in (stream.get("captions") or data.get("captions") or [])[:40]:
        if not isinstance(cap, dict) or not cap.get("url"):
            continue
        captions.append({
            "lang": caption_lang(cap.get("language")),
            "label": cap.get("language") or "Track",
            "url": cap["url"],
        })

    ordered = sorted(
        ((to_int(height), info) for height, info in qualities.items() if isinstance(info, dict) and info.get("url")),
        key=lambda pair: -pair[0],
    )

    hits = []
    expired = 0
    for height, info in ordered[:3]:
        if out_of_time(deadline):
            break
        if vidlink_expired(info["url"]):
            expired += 1
            continue
        if not probe_mp4(info["url"], referer, log, deadline):
            continue
        hits.append({
            "url": info["url"],
            "secs": 0,
            "referer": referer,
            "kind": "mp4",
            "subtitles": captions,
            "meta": {"height": height or None, "tags": ["%dP" % height] if height else [], "kind": "mp4"},
        })
        if len(hits) >= 2:
            break

    if not hits:
        log.append("stale x%d" % expired if expired else "no playable mp4")
        return None
    return hits


def vs_post(url, headers, deadline, referer="https://vidfast.vc/"):
    status, _, body = fetch(url, referer=referer, origin=_origin_of(referer), accept="*/*",
                            extra=headers, data=b"", xhr=True,
                            timeout=hop_timeout(deadline), attempts=1)
    return status, body.decode("utf-8", "replace")


def p_vidfast(tmdb, get_imdb, log, deadline):
    for host in ("https://vidfast.vc", "https://vidfast.pro"):
        if out_of_time(deadline):
            break
        page_url = "%s/movie/%s/" % (host, tmdb)
        status, page = get_text(page_url, referer=host + "/", timeout=hop_timeout(deadline))
        log.append("page %s %d len=%d" % (host, status, len(page)))
        if status != 200 or not page:
            continue

        match = re.search(r'\\"(?:en|token)\\":"(.*?)\\"', page) or re.search(r'"(?:en|token)":"(.*?)"', page)
        if not match:
            log.append("no token")
            continue

        stage1 = enc_get("enc-vidfast", deadline, text=match.group(1), stage="1")
        if not isinstance(stage1, dict) or not stage1.get("stage1"):
            log.append("stage1 fail")
            continue

        headers = {"X-CSRF-Token": stage1.get("token") or "", "X-Requested-With": "XMLHttpRequest"}
        st, servers_blob = vs_post(stage1["stage1"], headers, deadline, referer=host + "/")
        log.append("stage1 post %d" % st)
        if st != 200 or not servers_blob:
            continue

        stage2 = enc_get("enc-vidfast", deadline, text=servers_blob, stage="2")
        if not isinstance(stage2, dict) or not stage2.get("servers"):
            log.append("stage2 fail")
            continue

        headers["X-CSRF-Token"] = stage2.get("token") or ""
        st, servers_enc = vs_post(stage2["servers"], headers, deadline, referer=host + "/")
        servers = enc_post("dec-vidfast", deadline, text=servers_enc) if st == 200 else None
        if isinstance(servers, str):
            try:
                servers = json.loads(servers)
            except Exception:
                servers = None
        if not isinstance(servers, list) or not servers:
            log.append("servers fail")
            continue

        found = []
        for server in servers[:2]:
            if out_of_time(deadline) or not isinstance(server, dict) or not server.get("data"):
                continue
            st, stream_enc = vs_post("%s/%s" % (stage2.get("stream") or "", server["data"]),
                                     headers, deadline, referer=host + "/")
            if st != 200 or not stream_enc:
                continue
            stream = enc_post("dec-vidfast", deadline, text=stream_enc)
            if isinstance(stream, str):
                try:
                    stream = json.loads(stream)
                except Exception:
                    stream = None
            if stream is None:
                continue
            blob = json.dumps(stream)
            found += playlists(blob)
            found += [u for u in all_urls(blob) if ".m3u8" in u or "/hls/" in u or ".mp4" in u]

        if found:
            hit = first_valid(found, page_url, log, deadline)
            if hit:
                return hit
    return None


def p_videasy(tmdb, get_imdb, log, deadline):
    meta = tmdb_meta(tmdb, deadline)
    if not meta or not meta.get("title"):
        log.append("no meta")
        return None
    imdb = get_imdb() or ""
    referer = "https://vidy.st/"
    headers = {"Origin": referer, "Referer": referer, "Accept": "*/*"}
    title = urllib.parse.quote(urllib.parse.quote(meta["title"], safe=""), safe="")

    status, seed_json = get_json("https://api.wecollege.net/seed?mediaId=" + tmdb,
                                 referer=referer, origin=referer, extra=headers, xhr=True,
                                 timeout=hop_timeout(deadline))
    seed = (seed_json or {}).get("seed") if isinstance(seed_json, dict) else None
    log.append("seed %d" % status)
    if not seed:
        return None

    found = []
    for server in ("miami", "boise", "vegas"):
        if out_of_time(deadline):
            break
        url = ("https://api.wecollege.net/%s/sources?title=%s&mediaType=movie&year=%s"
               "&tmdbId=%s&imdbId=%s&enc=2&seed=%s" % (server, title, meta["year"], tmdb, imdb, seed))
        st, _, body = fetch(url, referer=referer, origin=referer, accept="*/*", extra=headers,
                            xhr=True, timeout=hop_timeout(deadline), attempts=1)
        log.append("src %s %d len=%d" % (server, st, len(body)))
        if st != 200 or not body:
            continue
        plain = enc_post("dec-videasy", deadline, text=body.decode("utf-8", "replace"),
                         id=tmdb, seed=seed)
        if plain is None:
            continue
        blob = plain if isinstance(plain, str) else json.dumps(plain)
        found += playlists(blob)
        found += [u for u in all_urls(blob) if ".m3u8" in u or "/hls/" in u]
        if found:
            break

    return first_valid(found, referer, log, deadline)


def vixsrc_candidates(page):
    raws = js_fields(page, "url")
    if not raws:
        return []
    token = js_field(page, "token")
    expires = js_field(page, "expires")

    out = []
    for raw in raws:
        url = raw if raw.startswith("http") else urllib.parse.urljoin("https://vixsrc.to/", raw)
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        names = {k for k, _ in query}
        if token and "token" not in names:
            query.append(("token", token))
        if expires and "expires" not in names:
            query.append(("expires", expires))
        if "h" not in names:
            query.append(("h", "1"))
        if "lang" not in names:
            query.append(("lang", "en"))
        if "ub" not in names:
            query.append(("ub", "1"))
        out.append(urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), "")))
    return list(dict.fromkeys(out))


def p_vixsrc(tmdb, get_imdb, log, deadline):
    referer = "https://vixsrc.to/movie/" + tmdb
    status, payload = get_json("https://vixsrc.to/api/movie/%s?lang=en" % tmdb, referer=referer,
                               timeout=hop_timeout(deadline))
    src = payload.get("src") if isinstance(payload, dict) else None
    if not isinstance(src, str):
        log.append("no src")
        return None
    player = src if src.startswith("http") else urllib.parse.urljoin("https://vixsrc.to/", src)
    status, page = get_text(player, referer=referer, timeout=hop_timeout(deadline))
    log.append("player %d len=%d" % (status, len(page)))

    found = vixsrc_candidates(page)
    if not found:
        log.append("no url field")
        return None

    return first_valid(found + playlists(page), player, log, deadline)


def p_videm(tmdb, get_imdb, log, deadline):
    imdb = get_imdb()
    if not imdb:
        log.append("no imdb")
        return None
    found = []
    for host in ("https://videm.cc", "https://videm.buzz"):
        if out_of_time(deadline):
            log.append("deadline at %s" % host)
            break
        endpoint = "%s/embed/movie/%s?autoplay=true" % (host, imdb)
        status, page = get_text(endpoint, referer="https://movieuniverse.skin/",
                                timeout=hop_timeout(deadline))
        log.append("embed %s %d len=%d" % (host, status, len(page)))
        found += playlists(page)
        found += [u for u in all_urls(page) if ".m3u8" in u or "/hls/" in u]

        for path in list(dict.fromkeys(API_PATH_RE.findall(page)))[:4]:
            if out_of_time(deadline):
                break
            url = path if path.startswith("http") else urllib.parse.urljoin(host + "/", path)
            status, payload = get_json(url, referer=endpoint, xhr=True, timeout=hop_timeout(deadline))
            log.append("api %d %s" % (status, path))
            if payload is not None:
                blob = json.dumps(payload)
                found += playlists(blob)
                found += [u for u in all_urls(blob) if ".m3u8" in u or "/hls/" in u]

    return first_valid(found, "https://movieuniverse.skin/", log, deadline)


PROVIDERS = [
    ("vixsrc", p_vixsrc),
    ("vidsrc", p_vidsrc),
    ("vidlink", p_vidlink),
    ("vidsrc_me", p_vidsrc_me),
    ("vidfast", p_vidfast),
    ("autoembed", p_autoembed),
    ("2embed", p_2embed),
    ("vidsrcto", p_vidsrcto),
    ("multiembed", p_multiembed),
    ("videm", p_videm),
    ("videasy", p_videasy),
    ("111movies", p_111movies),
    ("moviesapi", p_moviesapi),
    ("embedsu", p_embedsu),
]


def _provider_referer(name, tmdb):
    if name == "vixsrc":
        return "https://vixsrc.to/movie/" + tmdb
    if name == "vidlink":
        return "https://vidlink.pro/movie/" + tmdb
    if name == "vidsrc_me":
        return "https://vidsrc.xyz/"
    if name == "autoembed":
        return "https://player.autoembed.cc/embed/movie/" + tmdb
    if name == "multiembed":
        return "https://multiembed.mov/"
    if name == "vidsrc":
        return "https://vidsrc.sh/embed/movie/%s/" % tmdb
    if name == "vidsrcto":
        return "https://vidsrc.to/embed/movie/" + tmdb
    if name == "2embed":
        return "https://www.2embed.cc/embed/" + tmdb
    if name == "vidfast":
        return "https://vidfast.vc/movie/" + tmdb + "/"
    if name == "111movies":
        return "https://111movies.com/movie/" + tmdb
    if name == "videasy":
        return "https://vidy.st/"
    if name == "moviesapi":
        return "https://moviesapi.club/movie/" + tmdb
    if name == "embedsu":
        return "https://embed.su/embed/movie/" + tmdb
    return "https://movieuniverse.skin/"


# --------------------------------------------------------------------- jobs

class Job:
    def __init__(self, tmdb, imdb_hint=None):
        self.tmdb = tmdb
        self.lock = threading.Lock()
        self.sources = []
        self.tried = []
        self.started = time.time()
        self.finished = False
        self.pending = len(PROVIDERS)
        self.changed = threading.Event()
        self.imdb = imdb_hint if (imdb_hint and imdb_hint.startswith("tt")) else None
        self.imdb_done = bool(self.imdb)
        self.imdb_lock = threading.Lock()
        # set by job_for from TMDB release data: the film is in cinemas and has no home release yet
        self.cinema_only = False

    def seed_imdb(self, imdb_hint):
        if imdb_hint and imdb_hint.startswith("tt"):
            with self.imdb_lock:
                self.imdb = imdb_hint
                self.imdb_done = True

    def get_imdb(self, deadline):
        with self.imdb_lock:
            if not self.imdb_done:
                self.imdb_done = True
                self.imdb = imdb_id(self.tmdb, tmdb_key(), [], deadline)
            return self.imdb

    def snapshot(self, since=0, base_url=None):
        prefix = (base_url or ("http://127.0.0.1:%d" % PORT)).rstrip("/")
        with self.lock:
            out = []
            for src in self.sources[since:]:
                copy = dict(src)
                copy["url"] = prefix + src["_path"]
                if isinstance(src.get("meta"), dict):
                    meta = dict(src["meta"])
                    if meta.get("_refSubPath"):
                        meta["refSubProxied"] = prefix + meta["_refSubPath"]
                    copy["meta"] = meta
                if src.get("subtitles"):
                    copy["subtitles"] = [
                        dict(track, url=prefix + "/sub?u=%s&lang=%s" % (quoted(track["url"]), quoted(track["lang"])))
                        for track in src["subtitles"]
                    ]
                out.append(copy)
            return out, len(self.sources), self.finished

    def view(self):
        with self.lock:
            return list(self.sources), list(self.tried), self.finished

    def imdb_value(self):
        with self.imdb_lock:
            return self.imdb

    def add(self, name, index, hit):
        direct = hit["url"]
        ref = hit.get("referer") or _provider_referer(name, self.tmdb)
        meta = dict(hit.get("meta") or {})
        blob = "%s %s" % (direct, " ".join(meta.get("tags") or []))
        lowered = blob.lower()
        # Flag a cinema recording here, once, so both the label and the ordering see the same answer.
        if not meta.get("cam") and is_cam(blob):
            meta["cam"] = True
        # An opaque provider URL (vidsrc, vidfast) carries no release name at all, so a cam rip is byte-for-byte
        # identical to a WEB-DL. If the film has no home release yet, the honest reading is a recording -- but only
        # as a GUESS: quality_rank treats it softly, so a source that does carry a digital token still wins.
        elif self.cinema_only and not any(token in lowered for token in DIGITAL_TOKENS):
            meta["cam"] = True
            meta["cam_guess"] = True
        # what the viewer already told us about this host on this film outranks any guess
        if is_marked_cam(self.tmdb, name):
            meta["cam"] = True
            meta["cam_mark"] = True
        path = "/hls?u=%s&ref=%s" % (quoted(direct), quoted(ref))
        if hit.get("bare"):
            path += "&bare=1"
        with self.lock:
            if any(existing["direct"] == direct for existing in self.sources):
                return None
            label = PROVIDER_LABELS.get(name, name.upper())
            same = sum(1 for existing in self.sources if existing.get("provider") == name)
            if same:
                label = "%s %d" % (label, same + 1)
            entry = {
                "label": label,
                "provider": name,
                "seconds": int(hit.get("secs") or 0),
                "kind": hit.get("kind") or "hls",
                "subtitles": list(hit.get("subtitles") or []),
                "bare": bool(hit.get("bare")),
                "_path": path,
                "_referer": ref,
                "url": "http://127.0.0.1:%d%s" % (PORT, path),
                "direct": direct,
                "meta": meta,
            }
            if hit.get("trick"):
                entry["_trickUrl"] = hit["trick"]
                entry["_trickPath"] = ("/hls?u=%s&ref=%s" % (quoted(hit["trick"]), quoted(ref))
                                       + ("&bare=1" if hit.get("bare") else ""))
            self.sources.append(entry)
        self.changed.set()
        return entry


def start_job(job):
    bg_deadline = job.started + BG_DEADLINE_S

    def worker(name, index, provider):
        slice_deadline = min(bg_deadline, time.time() + PER_PROVIDER_S)
        steps = []
        hit = None
        try:
            hit = provider(job.tmdb, lambda: job.get_imdb(slice_deadline), steps, slice_deadline)
        except Exception as exc:
            steps.append("exc " + str(exc))
        if hit:
            for item in (hit if isinstance(hit, list) else [hit]):
                if item:
                    job.add(name, index, item)
        with job.lock:
            job.pending -= 1
            if not hit:
                job.tried.append({"provider": name, "steps": steps})
            if job.pending <= 0 or len(job.sources) >= MAX_SOURCES:
                job.finished = True
        job.changed.set()
        if hit:
            say("job %s %s hit %d" % (job.tmdb, name, len(hit) if isinstance(hit, list) else 1))

    for index, (name, provider) in enumerate(PROVIDERS):
        threading.Thread(target=worker, args=(name, index, provider), daemon=True).start()


def job_for(tmdb, imdb_hint=None):
    now = time.time()
    with JOBS_LOCK:
        for key in [k for k, v in JOBS.items() if now - v.started > JOBS_TTL]:
            JOBS.pop(key, None)
        job = JOBS.get(tmdb)
        if job is not None:
            job.seed_imdb(imdb_hint)
            return job, False
        if len(JOBS) >= 40:
            for key in sorted(JOBS, key=lambda k: JOBS[k].started)[:10]:
                JOBS.pop(key, None)
        job = Job(tmdb, imdb_hint=imdb_hint)
        JOBS[tmdb] = job
    # outside the lock: this is a network call, and it has to be known before any worker adds a source
    job.cinema_only = cinema_only(tmdb) is True
    start_job(job)
    return job, True


# ----------------------------------------------------------------- subtitles

def decode_sub_bytes(body, lang=""):
    if not body:
        return ""
    if body.startswith(b"\xef\xbb\xbf"):
        text = body[3:].decode("utf-8", "replace")
    elif body.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = body.decode("utf-16", "replace")
    else:
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            if lang.lower().startswith("ar"):
                text = body.decode("cp1256", "replace")
            else:
                cp1256_text = body.decode("cp1256", "replace")
                if len(ARABIC_RE.findall(cp1256_text)) >= 10:
                    text = cp1256_text
                else:
                    text = body.decode("cp1252", "replace")
    return WYZIE_PROMO_RE.sub("", text)


SRT_INDEX_RE = re.compile(r"(?m)^\d+[ \t]*\n(?=\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->)")
SRT_COMMA_RE = re.compile(r"(\d{2}:\d{2}:\d{2}),(\d{3})")


def srt_to_vtt(text):
    if not text:
        return ""
    clean = text.replace("\ufeff", "").replace("\r", "")
    if clean.lstrip().upper().startswith("WEBVTT"):
        return clean
    body = SRT_INDEX_RE.sub("", clean)
    body = SRT_COMMA_RE.sub(r"\1.\2", body)
    return "WEBVTT\n\n" + body.strip() + "\n"


NOISE_TOKENS = frozenset({
    "www", "com", "http", "https", "m3u8", "mp4", "index", "hls",
    "localhost", "127", "8787", "vixsrc", "vidsrc", "vidlink", "playlist",
    "token", "expires", "rendition", "type", "video", "audio", "lang",
})


def release_tokens(*blobs):
    text = " ".join(b for b in blobs if b).lower()
    out = set()
    for token in re.split(r"[^a-z0-9]+", text):
        if len(token) < 3 or token in NOISE_TOKENS or token.isdigit():
            continue
        out.add(token)
    return out


def sub_download(url):
    if "sub.wyzie.io" not in url:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + "to=vtt&plain=1&lines=42&mindur=1&maxlines=2"


CUE_TIME_RE = re.compile(
    r"(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})"
)


def parse_vtt_cues(text):
    cues = []
    for m in CUE_TIME_RE.finditer(text):
        s = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000.0
        e = int(m.group(5) or 0) * 3600 + int(m.group(6)) * 60 + int(m.group(7)) + int(m.group(8)) / 1000.0
        cues.append((s, max(s, e)))
    cues.sort(key=lambda x: x[0])
    return cues


def arabic_naturalness_score(text, plain):
    bonus = 0
    lines = [ln.strip() for ln in plain.splitlines() if ln.strip()]
    if not lines:
        return 0

    edge_sample = "\n".join(lines[:12] + lines[-12:])
    if AR_CREDIT_RE.search(edge_sample):
        bonus += 30

    ar_punct = plain.count("؟") + plain.count("،")
    ascii_punct = len(re.findall(r"[\u0600-\u06FF]\s*[?,]", plain))
    if ar_punct >= 15 and ascii_punct <= 3:
        bonus += 12
    elif ascii_punct > ar_punct and ascii_punct >= 10:
        bonus -= 18

    calque_hits = len(AR_CALQUE_RE.findall(plain))
    if calque_hits:
        bonus -= min(45, calque_hits * 12)

    ar_lines = [ln for ln in lines if ARABIC_RE.search(ln)]
    if len(ar_lines) >= 40:
        pronoun_starts = sum(1 for ln in ar_lines if AR_PRONOUN_START_RE.match(ln))
        ratio = pronoun_starts / len(ar_lines)
        if ratio > 0.14:
            bonus -= 22
        elif ratio < 0.05:
            bonus += 8

    return bonus


def sub_verify(url, lang, runtime, deadline=None):
    status, _, body = fetch(sub_download(url), accept="*/*", attempts=1,
                            timeout=hop_timeout(deadline, SUB_VERIFY_TIMEOUT))
    if status != 200 or not body:
        return None
    text = decode_sub_bytes(body, lang)
    cues = parse_vtt_cues(text)
    if len(cues) < 25:
        return None

    span = cues[-1][1] - cues[0][0]
    if runtime > 0:
        wanted = max(50.0, (runtime / 60.0) * SUB_MIN_CUES_PER_MIN)
        if len(cues) < wanted:
            return None
        if cues[-1][1] < runtime * 0.60:
            return None
    elif span < 1800:
        return None

    max_gap = max((cues[i][0] - cues[i - 1][1] for i in range(1, len(cues))), default=0.0)
    if max_gap > 720.0:
        return None

    plain = CUE_TIME_RE.sub(" ", text)
    plain = re.sub(r"^\s*\d+\s*$", "", plain, flags=re.M)
    plain = re.sub(r"<[^>]+>", " ", plain)

    if lang.lower().startswith("ar"):
        arabic_chars = len(ARABIC_RE.findall(plain))
        if arabic_chars < 25:
            return None
        letters = len(re.findall(r"[^\W\d_]", plain, re.U))
        if letters > 0 and (arabic_chars / letters) < 0.35:
            return None
        richness = min(22, int(len(cues) / 65) + int(arabic_chars / 2800))
        return richness + arabic_naturalness_score(text, plain)

    return min(16, int(len(cues) / 75))


def is_machine_candidate(item):
    src = str(item.get("source") or "").lower()
    if item.get("ai") or src in ("ai", "quebec"):
        return True
    name = "%s %s %s" % (
        item.get("release") or "", item.get("fileName") or "", item.get("display") or ""
    )
    if any(token in name.lower() for token in SUB_BAD_TOKENS):
        return True
    quality = item.get("quality")
    if isinstance(quality, dict):
        flags = set(quality.get("flags") or [])
        if "machine_translated" in flags or "wrong_language" in flags:
            return True
    return False


def sub_score(item, tokens, is_pal_25fps, is_extended, allow_mtl=False):
    if not item.get("url"):
        return None

    name = "%s %s %s %s" % (
        item.get("release") or "", item.get("fileName") or "",
        item.get("display") or "", item.get("media") or "",
    )
    lowered = name.lower()

    if item.get("isForced") or SUB_FORCED_RE.search(lowered):
        return None

    if is_machine_candidate(item):
        if not allow_mtl:
            return None
        score = -80
    else:
        score = SUB_SOURCE_BONUS.get(str(item.get("source") or "").lower(), 12)

    quality = item.get("quality")
    if isinstance(quality, dict):
        score += (to_int(quality.get("score"), 50) - 50) * 0.4
        for flag in quality.get("flags") or []:
            score += SUB_FLAG_PENALTY.get(flag, 0)

    if item.get("isHearingImpaired") or re.search(r"\b(sdh|full|complete)\b", lowered):
        score += 10
    if any(token in lowered for token in SUB_PARTIAL_TOKENS):
        score -= 18

    lang_code = str(item.get("language") or "").lower()
    if lang_code and not lang_code.startswith("en"):
        if re.search(r"[-_.]en(g)?\b", lowered):
            score -= 28
        if re.search(r"\byify\b", lowered):
            score -= 14

    if re.search(r"\b(WEB[-_. ]?DL|WEBRip|BluRay|BDRip|BRRip|NF|AMZN|DSNP|ATVP|HMAX)\b", name, re.I):
        score += 45
    if re.search(r"\b(1080p|720p|2160p)\b", name, re.I):
        score += 15
    if re.search(r"\b(x264|x265|HEVC|H\.?264|H\.?265|AAC|DDP)\b", name, re.I):
        score += 10
    if re.search(r"\b(CAM|HDCAM|TS|TELESYNC|TC|TELECINE|DVDSCR|SCR|R5|WORKPRINT)\b", name, re.I):
        score -= 120
    score += SUB_ORIGIN_BONUS.get(str(item.get("origin") or "").upper(), 0)

    has_alt_cut = bool(re.search(r"\b(EXTENDED|DIRECTOR'?S?\.?CUT|UNRATED|IMAX|THEATRICAL)\b", name, re.I))
    if is_extended:
        score += 55 if has_alt_cut else -40
    elif re.search(r"\bTHEATRICAL\b", name, re.I):
        score += 25
    elif has_alt_cut:
        score -= 75

    has_25fps = bool(re.search(r"\b(25\s?fps|PAL)\b", name, re.I))
    if is_pal_25fps:
        score += 65 if has_25fps else -35
    elif has_25fps:
        score -= 85

    downloads = to_int(item.get("downloadCount"))
    if downloads > 0:
        score += min(30, int(downloads ** 0.5))

    if item.get("matchedRelease"):
        score += 16
    if tokens:
        release_blob = (str(item.get("release") or "") + " " +
                        " ".join(str(x) for x in (item.get("releases") or []))).lower()
        score += min(sum(1 for token in tokens if token in release_blob) * 6, 24)

    if str(item.get("format") or "").lower() in ("srt", "vtt", "ass"):
        score += 3
    return score


def subdl_search(lookup, langs, key, deadline):
    if not key or out_of_time(deadline):
        return []
    param_key = "imdb_id" if lookup.startswith("tt") else "tmdb_id"
    query = urllib.parse.urlencode({
        "api_key": key,
        param_key: lookup,
        "type": "movie",
        "languages": ",".join(l.upper() for l in langs[:20]),
        "subs_per_page": "30",
    })
    status, payload = get_json("https://api.subdl.com/api/v1/subtitles?%s" % query,
                               timeout=hop_timeout(deadline, SUBS_TIMEOUT))
    if status != 200 or not isinstance(payload, dict) or not payload.get("status"):
        return []
    out = []
    for sub in payload.get("subtitles") or []:
        if not isinstance(sub, dict) or not sub.get("url"):
            continue
        raw_path = str(sub["url"])
        full_url = raw_path if raw_path.startswith("http") else ("https://dl.subdl.com" + raw_path)
        releases = sub.get("releases") or []
        rel_name = sub.get("release_name") or (releases[0] if releases else "") or sub.get("name") or ""
        out.append({
            "url": full_url,
            "language": str(sub.get("language") or "en").lower()[:5],
            "release": rel_name,
            "releases": releases,
            "display": rel_name or "SubDL",
            "source": "subdl",
            "isHearingImpaired": bool(sub.get("hi")),
            "downloadCount": to_int(sub.get("downloads")),
            "format": "srt",
        })
    return out


def wyzie_search(lookup, langs, key, deadline):
    found = []
    lock = threading.Lock()
    problem = {"value": None}

    def ask(chunk, source):
        query = urllib.parse.urlencode({
            "id": lookup,
            "language": ",".join(chunk),
            "format": "srt",
            "source": source,
            "sort": "downloads",
            "limit": "200",
            "key": key,
        })
        status, items = get_json("https://sub.wyzie.io/search?%s" % query,
                                 timeout=hop_timeout(deadline, SUBS_TIMEOUT))
        if status in (401, 403):
            with lock:
                if not problem["value"]:
                    problem["value"] = "denied"
            return
        if status == 429:
            with lock:
                if not problem["value"]:
                    problem["value"] = "quota"
            return
        if status == 404:
            return
        if status != 200 or not isinstance(items, list):
            if source != "all":
                ask(chunk, "all")
            return
        with lock:
            found.extend(item for item in items if isinstance(item, dict))

    chunks = [langs[i:i + SUB_CHUNK] for i in range(0, len(langs), SUB_CHUNK)]
    with ThreadPoolExecutor(max_workers=SUBS_WORKERS) as pool:
        futures = [pool.submit(ask, chunk, SUB_SOURCE_ORDER) for chunk in chunks]
        for future in futures:
            try:
                future.result()
            except Exception:
                pass
    return found, problem["value"]


def rank_subs(candidates, tokens, runtime, is_pal_25fps, is_extended, single_lang, deadline):
    def collect(allow_mtl):
        out = []
        for item in candidates:
            lang = str(item.get("language") or "").lower()
            if not lang:
                continue
            score = sub_score(item, tokens, is_pal_25fps, is_extended, allow_mtl=allow_mtl)
            if score is None:
                continue
            out.append((score, lang, item))
        return out

    scored = collect(allow_mtl=False)
    if not scored:
        scored = collect(allow_mtl=True)

    scored.sort(key=lambda entry: -entry[0])

    if single_lang:
        seen_urls = set()
        unique = []
        for score, lang, item in scored:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            unique.append((score, lang, item))
        shortlist = unique[:SUB_MAX_VERIFY]
        extras = unique[SUB_MAX_VERIFY:25]
    else:
        best_by_lang = {}
        for score, lang, item in scored:
            if lang not in best_by_lang:
                best_by_lang[lang] = (score, lang, item)
        shortlist = sorted(best_by_lang.values(), key=lambda entry: -entry[0])[:SUB_MAX_VERIFY]
        extras = []

    verified = []
    lock = threading.Lock()

    def check(entry):
        score, lang, item = entry
        if out_of_time(deadline):
            return
        bonus = sub_verify(item["url"], lang, runtime, deadline)
        if bonus is None:
            return
        item["matchScore"] = score + bonus
        with lock:
            verified.append(item)

    with ThreadPoolExecutor(max_workers=SUBS_WORKERS) as pool:
        futures = [pool.submit(check, entry) for entry in shortlist]
        for future in futures:
            try:
                future.result()
            except Exception:
                pass

    verified.sort(key=lambda item: -item["matchScore"])

    if single_lang:
        for score, _, item in extras:
            item["matchScore"] = score
            verified.append(item)

    deduped = {}
    for item in verified:
        deduped.setdefault(item["url"], item)
    items = list(deduped.values())
    if items:
        items[0]["bestMatch"] = True
    return items


# --------------------------------------------------------------------- dumps

def walk_strings_safe(text):
    try:
        payload = json.loads(text)
    except Exception:
        return []
    return list(walk_strings(payload))


def dump_vidsrc(tmdb):
    out = {"variants": {}}
    session = vidsrc_session(tmdb)
    if not session:
        return {"error": "no session"}
    out["pool"] = session["pool"]
    out["player"] = session["player"]
    keys = vidsrc_keys(session["token"])
    out["keys"] = [k[:24] for k in keys]
    for label, use_pool, header in (("pool+query", True, None),
                                    ("pool+bearer", True, "bearer"),
                                    ("default+query", False, None)):
        url, extra = vidsrc_url(session, use_pool=use_pool, header=header)
        if not url:
            out["variants"][label] = {"error": "no url"}
            continue
        status, _, body = fetch(url, referer=session["player"], extra=extra, xhr=True)
        text = body.decode("utf-8", "replace")
        decoded = []
        for path, value in walk_strings_safe(text):
            if len(decoded) >= 6:
                break
            hit = vs_decrypt(value, keys)
            if hit:
                decoded.append({"at": path, "key": hit[1], "text": hit[0][:200]})
        out["variants"][label] = {
            "url": url,
            "status": status,
            "body": text[:20000],
            "decoded": decoded,
        }
    return out


def dump_vidlink(tmdb):
    referer = "https://vidlink.pro/movie/" + tmdb
    enc_id = enc_get("enc-vidlink", None, text=tmdb)
    if not enc_id:
        return {"error": "enc failed"}
    api = "https://vidlink.pro/api/b/movie/%s?multiLang=0" % urllib.parse.quote(enc_id, safe="")
    status, _, body = fetch(api, referer=referer, origin="https://vidlink.pro", accept="*/*", xhr=True)
    return {"enc_id": enc_id, "api": api, "status": status,
            "body": body.decode("utf-8", "replace")[:1600]}


def dump_vixsrc(tmdb):
    referer = "https://vixsrc.to/movie/" + tmdb
    status, payload = get_json("https://vixsrc.to/api/movie/%s?lang=en" % tmdb, referer=referer)
    src = payload.get("src") if isinstance(payload, dict) else None
    if not isinstance(src, str):
        return {"error": "no src"}
    player = src if src.startswith("http") else urllib.parse.urljoin("https://vixsrc.to/", src)
    status, page = get_text(player, referer=referer)

    results = []
    for url in vixsrc_candidates(page):
        status, headers, body = fetch(url, referer=player, accept="*/*", xhr=True,
                                      origin="https://vixsrc.to")
        results.append({"url": url, "status": status,
                        "ctype": headers.get("Content-Type"),
                        "head": body.decode("utf-8", "replace")[:300]})
    return {"candidates": results}


def dump_videm(tmdb, imdb):
    if not imdb:
        return {"error": "no imdb"}
    endpoint = "https://videm.buzz/embed/movie/%s?autoplay=true" % imdb
    status, page = get_text(endpoint, referer="https://movieuniverse.skin/")
    return {"status": status, "len": len(page),
            "paths": list(dict.fromkeys(API_PATH_RE.findall(page)))[:12],
            "tail": page[-1500:]}


# --------------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 60
    headers_sent = False

    def log_message(self, fmt, *args):
        pass

    def _relay_base(self):
        host = (self.headers.get("Host") or "").strip().split("/")[0]
        scheme = "https" if (self.headers.get("X-Forwarded-Proto") or "").lower() == "https" else "http"
        if host:
            if ":" not in host:
                host = "%s:%d" % (host, PORT)
            return "%s://%s" % (scheme, host)
        return "%s://127.0.0.1:%d" % (scheme, PORT)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _write(self, data):
        """A client seeking or closing the tab aborts mid-write. That is normal, not a 500."""
        try:
            self.wfile.write(data)
        except (ConnectionError, socket.timeout, TimeoutError):
            self.close_connection = True

    def _send(self, status, payload, quiet=False):
        body = payload.encode() if isinstance(payload, str) else payload
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.headers_sent = True
        self._write(body)
        if not quiet:
            say("%d %s" % (status, urllib.parse.urlsplit(self.path).path))

    def _text(self, body, ctype="text/plain; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.headers_sent = True
        self._write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()
        self.headers_sent = True

    def do_GET(self):
        self.headers_sent = False
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/health":
                self._send(200, json.dumps({"ok": True}))
            elif parsed.path == "/favicon.ico":
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                self.headers_sent = True
            elif parsed.path == "/resolve":
                self._resolve(params)
            elif parsed.path == "/more":
                self._more(params)
            elif parsed.path == "/status":
                self._status(params)
            elif parsed.path == "/mark":
                self._mark(params)
            elif parsed.path == "/subs":
                self._subs(params)
            elif parsed.path == "/sub":
                self._sub(params)
            elif parsed.path == "/dump":
                self._dump(params)
            elif parsed.path == "/grep":
                self._grep(params)
            elif parsed.path == "/grep2":
                self._grep2(params)
            elif parsed.path == "/hls":
                self._hls(params)
            elif parsed.path == "/trick":
                self._trick(params)
            elif parsed.path == "/tricklog":
                self._tricklog(params)
            elif parsed.path.startswith("/trick/"):
                self._trick_file(parsed.path)
            else:
                self._send(404, json.dumps({"error": "not found"}))
        except (ConnectionError, socket.timeout, TimeoutError):
            return
        except Exception as exc:
            say("500 %s %s" % (parsed.path, exc))
            if not self.headers_sent:
                try:
                    self._send(500, json.dumps({"error": str(exc)}))
                except Exception:
                    pass

    # ---------------------------------------------------------------- resolve

    def _resolve(self, params):
        tmdb = (params.get("id") or params.get("tmdb") or [""])[0]
        imdb_hint = (params.get("imdb") or [""])[0].strip()
        if not tmdb.isdigit():
            self._send(400, json.dumps({"error": "bad id"}))
            return

        base = self._relay_base()
        started = time.time()
        job, _ = job_for(tmdb, imdb_hint=imdb_hint)

        earliest = started + FAST_S
        hard_stop = started + SLOW_S
        while True:
            sources, count, finished = job.snapshot(0, base)
            now = time.time()
            if finished or now >= hard_stop:
                break
            if count and now >= earliest:
                break
            job.changed.clear()
            job.changed.wait(0.1)

        sources, count, finished = job.snapshot(0, base)
        if not sources:
            _, tried, _ = job.view()
            self._send(502, json.dumps({
                "error": "no working source",
                "imdb": job.imdb_value(),
                "tried": tried,
                "sources": [],
            }))
            return

        # Best copy first: the client autoplays index 0, so a digital file must never sit behind a cam recording.
        sources = by_quality(sources)
        say("resolve %s -> %d source(s) in %.1fs" % (tmdb, count, time.time() - started))
        self._send(200, json.dumps({
            "provider": sources[0]["label"],
            "imdb": job.imdb_value(),
            "url": sources[0]["url"],
            "source": sources[0]["url"],
            "sources": sources,
            "next": len(sources),
            "more": not finished,
            "tried": job.tried,
        }))

    def _more(self, params):
        tmdb = (params.get("id") or params.get("tmdb") or [""])[0]
        since = to_int((params.get("since") or ["0"])[0])
        if not tmdb.isdigit():
            self._send(400, json.dumps({"error": "bad id"}))
            return
        with JOBS_LOCK:
            job = JOBS.get(tmdb)
        if job is None:
            self._send(200, json.dumps({"sources": [], "next": since, "more": False, "done": True, "total": 0}))
            return

        base = self._relay_base()
        stop = time.time() + 6
        while True:
            sources, total, finished = job.snapshot(since, base)
            if sources or finished or time.time() >= stop:
                break
            job.changed.clear()
            job.changed.wait(0.15)

        sources, total, finished = job.snapshot(since, base)
        sources = by_quality(sources)
        self._send(200, json.dumps({
            "sources": sources,
            "next": since + len(sources),
            "more": not finished,
            "done": bool(finished),
            "total": total,
        }))

    def _mark(self, params):
        tmdb = (params.get("id") or [""])[0]
        provider = (params.get("p") or [""])[0]
        cam = (params.get("cam") or ["1"])[0] != "0"
        if not tmdb.isdigit() or not provider:
            self._send(400, json.dumps({"error": "bad id or p"}))
            return

        save_cam_mark(tmdb, provider, cam)
        with JOBS_LOCK:
            job = JOBS.get(tmdb)
        if job is not None:
            with job.lock:
                for src in job.sources:
                    if src.get("provider") != provider:
                        continue
                    meta = src.setdefault("meta", {})
                    if cam:
                        meta["cam"] = True
                        meta["cam_mark"] = True
                    else:
                        meta.pop("cam_mark", None)
                        blob = "%s %s" % (src.get("direct") or "", " ".join(meta.get("tags") or []))
                        if not is_cam(blob):
                            meta.pop("cam", None)
            job.changed.set()
        say("mark %s %s cam=%d" % (tmdb, provider, 1 if cam else 0))
        self._send(200, json.dumps({"ok": True, "provider": provider, "cam": cam}))

    def _status(self, params):
        tmdb = (params.get("id") or params.get("tmdb") or [""])[0]
        with JOBS_LOCK:
            job = JOBS.get(tmdb)
        if job is None:
            self._send(404, json.dumps({"error": "no job"}))
            return
        sources, tried, finished = job.view()
        self._send(200, json.dumps({
            "tmdb": tmdb,
            "imdb": job.imdb_value(),
            "finished": finished,
            "pending": job.pending,
            "cinema_only": bool(job.cinema_only),
            "sources": [{"label": s["label"], "provider": s["provider"], "seconds": s["seconds"],
                         "kind": s.get("kind"), "cam": bool((s.get("meta") or {}).get("cam")),
                         "cam_guess": bool((s.get("meta") or {}).get("cam_guess")),
                         "cam_mark": bool((s.get("meta") or {}).get("cam_mark")),
                         "height": (s.get("meta") or {}).get("height"),
                         "rank": round(quality_rank(s), 2)}
                        for s in sources],
            "tried": tried,
        }, indent=2))

    # ---------------------------------------------------------------- trickplay

    def _trick(self, params):
        tmdb = (params.get("id") or [""])[0]
        if not tmdb.isdigit():
            self._send(400, json.dumps({"error": "bad id"}))
            return

        force = (params.get("force") or [""])[0] == "1"
        entry = trick_live(tmdb, force=force)
        if entry is None:
            if not ffmpeg_bin():
                self._send(200, json.dumps({"state": "failed", "error": "ffmpeg not found"}))
                return
            with JOBS_LOCK:
                job = JOBS.get(tmdb)
            if job is None or not job.sources:
                self._send(409, json.dumps({"state": "pending", "error": "no source yet"}), quiet=True)
                return

            index = max(0, min(to_int((params.get("i") or ["0"])[0]), len(job.sources) - 1))
            src = job.sources[index]
            duration = to_int((params.get("secs") or ["0"])[0]) or src.get("seconds") or 0

            url, referer, bare = trick_source_url(src)
            if not url:
                self._send(200, json.dumps({"state": "failed", "error": "no source url"}))
                return
            say("trick %s cutting from %s" % (tmdb, url[:120]))
            entry = trick_start(tmdb, url, referer, bare, duration)

        is_pending = entry["state"] == "pending"
        self._send(200, json.dumps({
            "state": entry["state"],
            "building": bool(entry.get("building")),
            "vtt": ("/trick/%s/thumbs.vtt" % tmdb) if entry["state"] == "ready" else "",
            "interval": entry["interval"], "cols": entry["cols"], "rows": entry["rows"],
            "w": entry["w"], "h": entry["h"], "frames": entry["frames"],
            "done": entry.get("done", 0),
            "tries": entry.get("tries", 0),
            "error": entry.get("error", ""),
        }), quiet=is_pending)

    def _tricklog(self, params):
        count = max(10, min(2000, to_int((params.get("n") or ["200"])[0], 200)))
        try:
            with open(LOG_PATH, encoding="utf-8", errors="replace") as handle:
                tail = handle.readlines()[-count:]
        except OSError as exc:
            self._text("relay.log unavailable: %s\n" % exc)
            return
        self._text("".join(tail) or "(log is empty)\n")

    def _trick_file(self, path):
        parts = path.strip("/").split("/")
        if len(parts) != 3:
            self._send(404, json.dumps({"error": "not found"}))
            return
        _, tmdb, name = parts
        entry = trick_live(tmdb)
        if not entry or entry["state"] != "ready":
            self._send(404, json.dumps({"error": "not ready"}))
            return

        if name == "thumbs.vtt":
            data = entry["vtt"].encode()
            ctype = "text/vtt; charset=utf-8"
        else:
            data = entry["sheets"].get(name)
            ctype = "image/webp" if name.endswith(".webp") else "image/jpeg"
            if not data and name.startswith("s") and name.endswith(".webp"):
                idx = to_int(name[1:-5], -1)
                sheet_ids = entry.get("sheet_ids") or []
                if 0 <= idx < len(sheet_ids):
                    st, _, blob = fetch("https://lh3.googleusercontent.com/d/%s=s0" % sheet_ids[idx],
                                        accept="image/webp,*/*", attempts=1, timeout=15)
                    if st == 200 and blob:
                        data = blob
        if not data:
            self._send(404, json.dumps({"error": "no file"}))
            return

        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        if name == "thumbs.vtt" and entry.get("building"):
            self.send_header("Cache-Control", "no-store")
        else:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.headers_sent = True
        self._write(data)

    # ---------------------------------------------------------------- subtitles

    def _subs(self, params):
        tmdb = (params.get("id") or [""])[0].strip()
        imdb = (params.get("imdb") or [""])[0].strip()
        key = (params.get("key") or [""])[0].strip() or wyzie_key()
        if not imdb.startswith("tt") and tmdb.isdigit():
            with JOBS_LOCK:
                job = JOBS.get(tmdb)
            imdb = (job.imdb_value() if job else None) or imdb_id(tmdb, tmdb_key(), []) or ""
        lookup = imdb if imdb.startswith("tt") else tmdb
        if not (lookup.startswith("tt") or lookup.isdigit()):
            self._send(400, json.dumps({"error": "bad id"}))
            return
        if not key:
            self._send(400, json.dumps({"error": "no WYZIE_KEY (env, .env or config.json)"}))
            return

        raw_lang = (params.get("lang") or [""])[0].strip().lower()
        raw_langs = (params.get("langs") or [""])[0].strip().lower()
        if raw_lang == "all" or raw_langs == "all":
            langs = list(ALL_LANGS)
        elif raw_langs:
            langs = [l for l in dict.fromkeys(x.strip() for x in raw_langs.split(",")) if LANG_RE.match(l)]
        elif raw_lang and LANG_RE.match(raw_lang):
            langs = [raw_lang]
        else:
            langs = ["en"]
        langs = langs[:MAX_SUB_LANGS] or ["en"]
        single_lang = len(langs) == 1

        stream_secs = to_int((params.get("secs") or ["0"])[0])
        runtime_secs = to_int((params.get("runtime") or ["0"])[0])

        is_pal_25fps = False
        is_extended = False
        if stream_secs > 0 and runtime_secs > 0:
            ratio = stream_secs / runtime_secs
            is_pal_25fps = 0.94 <= ratio <= 0.975
            is_extended = (stream_secs - runtime_secs) > 240

        cache_key = "%s|%s|%s%s" % (
            lookup, ",".join(sorted(langs)),
            "p" if is_pal_25fps else "", "e" if is_extended else "",
        )
        base = self._relay_base()

        def attach_proxy_urls(rows):
            out = []
            for row in rows:
                copy = dict(row)
                raw_url = copy.get("directUrl") or copy.get("url") or ""
                if raw_url:
                    copy["directUrl"] = raw_url
                    lang_code = str(copy.get("language") or (langs[0] if single_lang else "en"))
                    copy["url"] = "%s/sub?u=%s&lang=%s" % (base, quoted(raw_url), quoted(lang_code))
                out.append(copy)
            return out

        now = time.time()
        with SUBS_LOCK:
            hit = SUBS_CACHE.get(cache_key)
            if hit and hit[0] > now:
                self._send(200, json.dumps(attach_proxy_urls(hit[1])))
                return

        tokens = release_tokens((params.get("rel") or [""])[0])
        deadline = time.time() + max(20, 6 * len(langs) // SUB_CHUNK + SUB_VERIFY_TIMEOUT + 8)

        candidates, problem = wyzie_search(lookup, langs, key, deadline)
        if not candidates and tmdb.isdigit() and lookup != tmdb:
            candidates, problem = wyzie_search(tmdb, langs, key, deadline)

        sdl_key = subdl_key()
        if sdl_key:
            candidates += subdl_search(lookup, langs, sdl_key, deadline)

        if problem == "denied" and not candidates:
            self._send(401, json.dumps({"error": "subtitle key refused"}))
            return
        if problem == "quota" and not candidates:
            self._send(429, json.dumps({"error": "subtitle quota spent"}))
            return
        if not candidates:
            self._send(200, json.dumps([]))
            return

        items = rank_subs(candidates, tokens, runtime_secs, is_pal_25fps, is_extended, single_lang, deadline)

        with SUBS_LOCK:
            if len(SUBS_CACHE) > 300:
                for stale in [k for k, v in SUBS_CACHE.items() if v[0] <= now]:
                    SUBS_CACHE.pop(stale, None)
            SUBS_CACHE[cache_key] = (now + SUBS_TTL, items)

        self._send(200, json.dumps(attach_proxy_urls(items)))

    def _sub(self, params):
        url = (params.get("u") or [""])[0].strip()
        lang = (params.get("lang") or [""])[0].strip().lower()
        if not url.startswith("http"):
            self._send(400, json.dumps({"error": "bad u"}))
            return
        if is_private(url):
            self._send(400, json.dumps({"error": "private host"}))
            return

        target = sub_download(url)
        status, _, body = fetch(target, accept="*/*", attempts=2, timeout=SUBS_TIMEOUT)
        if status != 200 or not body:
            status, _, body = fetch(url, accept="*/*", attempts=1, timeout=SUBS_TIMEOUT)
        if status == 0:
            status = 502
        if status != 200:
            self._send(status, json.dumps({"error": "subtitle fetch failed (%d)" % status}))
            return

        text = srt_to_vtt(decode_sub_bytes(body, lang))
        data = text.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/vtt; charset=utf-8")
        self._cors()
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.headers_sent = True
        self._write(data)
        say("200 /sub (%d bytes)" % len(data))

    # ---------------------------------------------------------------- debug

    def _dump(self, params):
        which = (params.get("p") or [""])[0]
        tmdb = (params.get("id") or params.get("tmdb") or ["49018"])[0]
        imdb = (params.get("imdb") or [""])[0] or imdb_id(tmdb, tmdb_key(), [])
        if which == "vidsrc":
            payload = dump_vidsrc(tmdb)
        elif which == "vixsrc":
            payload = dump_vixsrc(tmdb)
        elif which == "videm":
            payload = dump_videm(tmdb, imdb)
        elif which == "vidlink":
            payload = dump_vidlink(tmdb)
        else:
            payload = {"error": "p must be vidsrc, vixsrc, videm or vidlink"}
        self._send(200, json.dumps(payload, indent=2))

    def _grep(self, params):
        which = (params.get("p") or [""])[0]
        tmdb = (params.get("id") or ["49018"])[0]
        pattern = (params.get("q") or ["m3u8"])[0]
        imdb = (params.get("imdb") or [""])[0] or imdb_id(tmdb, tmdb_key(), [])

        if which == "vidsrc":
            session = vidsrc_session(tmdb)
            if not session:
                self._send(502, json.dumps({"error": "no player"}))
                return
            url, body = session["player"], session["body"]
        elif which == "videm":
            url = "https://videm.buzz/embed/movie/%s?autoplay=true" % imdb
            status, body = get_text(url, referer="https://movieuniverse.skin/")
        else:
            self._send(400, json.dumps({"error": "p must be vidsrc or videm"}))
            return

        self._send(200, json.dumps({"url": url, "len": len(body), "hits": grep(body, pattern)},
                                   indent=2))

    def _grep2(self, params):
        url = (params.get("u") or [""])[0]
        referer = (params.get("ref") or [None])[0]
        pattern = (params.get("q") or ["m3u8"])[0]
        if not url.startswith("http"):
            self._send(400, json.dumps({"error": "bad u"}))
            return
        status, body = get_text(url, referer=referer)
        self._send(200, json.dumps({"url": url, "status": status, "len": len(body),
                                    "hits": grep(body, pattern)}, indent=2))

    # ---------------------------------------------------------------- proxy

    def _hls(self, params):
        url = (params.get("u") or [""])[0]
        if not url.startswith("http"):
            self._send(400, json.dumps({"error": "bad u"}))
            return
        if is_private(url):
            self._send(400, json.dumps({"error": "private host"}))
            return

        parsed = urllib.parse.urlparse(url)
        origin = "%s://%s" % (parsed.scheme, parsed.netloc)
        base = self._relay_base()

        given = (params.get("ref") or [""])[0]
        bare = (params.get("bare") or [""])[0] == "1"
        sent = self.headers.get("Referer") or ""
        if given.startswith("http"):
            referer = given
        elif sent and "ruintv.to" not in sent and not is_private(sent):
            referer = sent
        else:
            referer = origin + "/"

        # Several hosts check that Origin belongs to the PLAYER that minted the token, not to the segment host.
        # Sending the segment's own origin is what makes them answer 403 to every request, even though the
        # playlist fetched fine: the manifest carries the token, the segments then reject it.
        fetch_origin = _origin_of(referer) or origin

        rng = self.headers.get("Range")

        cache_key = (url, rng or "")
        cached = seg_cache_get(cache_key)
        if cached is not None:
            status, headers, body = 200, {"Content-Type": cached[0]}, cached[1]
        else:
            status, headers, body = 0, {}, b""
            for attempt in range(THROTTLE_RETRIES):
                if bare:
                    status, headers, body = bare_fetch(url, referer, rng=rng)
                else:
                    status, headers, body = fetch(url, referer=referer, origin=fetch_origin,
                                                  accept="*/*", rng=rng, xhr=True, attempts=1)
                if status != 429:
                    break
                time.sleep(0.5 * (attempt + 1))

            if status == 403:
                if bare:
                    status, headers, body = fetch(url, referer=referer, origin=fetch_origin,
                                                  accept="*/*", rng=rng, xhr=True, attempts=1)
                else:
                    status, headers, body = bare_fetch(url, referer, rng=rng)
                if status == 200:
                    bare = not bare
            if status == 0:
                status = 502

        path = parsed.path.lower()
        sniff = body[3:] if body.startswith(b"\xef\xbb\xbf") else body
        is_playlist = sniff.lstrip()[:7] == b"#EXTM3U"

        if cached is None and status == 200 and body and not is_playlist:
            seg_cache_put(cache_key, headers.get("Content-Type") or "application/octet-stream", body)

        def proxied(target):
            out = "%s/hls?u=%s" % (base, quoted(target))
            if given.startswith("http"):
                out += "&ref=" + quoted(given)
            if bare:
                out += "&bare=1"
            return out

        self.send_response(status)
        self._cors()
        self.send_header(
            "Access-Control-Expose-Headers",
            "content-length,content-range,accept-ranges")

        if is_playlist:
            lines = []
            for line in sniff.decode("utf-8", "replace").splitlines():
                stripped = line.strip()
                if not stripped:
                    lines.append(line)
                elif stripped.startswith("#"):
                    # #EXT-X-KEY / #EXT-X-MAP / #EXT-X-MEDIA carry URIs that need the same token treatment
                    lines.append(re.sub(
                        r'URI="([^"]+)"',
                        lambda m: 'URI="%s"' % proxied(
                            urllib.parse.urljoin(url, inherit_query(m.group(1), url))),
                        line))
                else:
                    lines.append(proxied(urllib.parse.urljoin(url, inherit_query(stripped, url))))
            data = "\n".join(lines).encode()
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.headers_sent = True
            self._write(data)
            return

        self.send_header("Cache-Control", "public, max-age=3600, immutable")

        if path.endswith(".key"):
            seg_type = "application/octet-stream"
        elif path.endswith((".ts", ".html", ".m4s")):
            seg_type = "video/mp2t"
        elif path.endswith((".mp4", ".m4a")):
            seg_type = "video/mp4"
        elif path.endswith(".aac"):
            seg_type = "audio/aac"
        elif path.endswith(".vtt"):
            seg_type = "text/vtt; charset=utf-8"
        else:
            seg_type = headers.get("Content-Type") or "application/octet-stream"
        if seg_type:
            self.send_header("Content-Type", seg_type)
        for key in ("Content-Range", "Accept-Ranges"):
            if headers.get(key):
                self.send_header(key, headers[key])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.headers_sent = True
        self._write(body)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


if __name__ == "__main__":
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as log_handle:
            log_handle.write("")
    except OSError:
        pass
    load_cam_marks()
    print("relay listening on http://0.0.0.0:%d" % PORT)
    say("relay up on port %d, log at %s" % (PORT, LOG_PATH))
    server = Server(("0.0.0.0", PORT), Handler)
    server.serve_forever()
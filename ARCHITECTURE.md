# ARCHITECTURE

## Topology

    Browser
      |
      +-- :80   server.py         static HTML/CSS/JS, range-capable, CSP
      +-- :8788 library.py        local files, index, remux, sidecar subs, sprites
      +-- :8789 grab.py           YTS resolve + handoff + staging watcher
      +-- :8787 relay.py          provider scrape + HLS proxy + subtitle ranker
             |
             +-- TMDB API
             +-- 14 embed providers (scraped)
             +-- Wyzie / SubDL subtitle APIs

Cloudflare Worker (`worker.js`) is a deployable alternative to `relay.py` with
5 providers and a 40-subrequest budget.

## Frontend (`movie site/`)

Static pages, one `<div id="app">` each, rendered by `components.js` and
`script.js`. `watch.html` loads hls.js, Supabase client, `components.js`,
`script.js`, `player-ui.js`.

Source resolution order in `script.js`, by design:

1. `librarySources(id)` against :8788 — local file wins outright
2. on miss, `beginFetch()` → POST :8789 `/grab`, poll `/queue` every 2 s
3. provider buttons / `/resolve` against :8787

Guards: `STALL_MS 20000`, `MAX_RETRIES 2`, `RESOLVE_TIMEOUT_MS 40000`,
`SOURCE_TTL_MS 150000`, `resolveSession` + AbortController, `playToken`
staleness check. `pollMoreSources` auto-switches off a CAM source unless the
user picked manually.

Progress persisted to Supabase `watch_progress` every 10 s, on pause, on
`visibilitychange`, and on `beforeunload` via keepalive.

## Backend — `library.py`

Scan: `rglob` over the root, `match_file()` resolves a TMDB id by, in order,
`[tmdb-<id>]` tag → IMDb id lookup → TMDB title+year search. Search demands an
exact lowercase title equality *and* a matching year, else no match. Failures
go to `/probe` as unmatched.

Serving: browser-safe files (mp4/webm + h264/vp8/vp9/av1 + aac/mp3/opus/vorbis)
are byte-streamed with Range. Everything else is remuxed once to fMP4 HLS in a
cache dir keyed by `sha1(path|mtime|size)`.

Remux command maps `0:v:0` and `0:a:0?` only, `-c:a aac -ac 2`.

Sprites: ffmpeg `-skip_frame nokey`, 10 s interval, 10x10 tiles, uploaded to a
Drive pool and indexed in Supabase `trickplay`. Absent config degrades to local.

## Backend — `grab.py`

`/grab` → TMDB `external_ids` → IMDb id → YTS `list_movies` → rank by quality
then seeds → hand magnet to FDM (or aria2/drop). Watcher files new videos into
the library as `<Title> (Year) [tmdb-<id>].ext`, then POSTs :8788 `/scan`.

## Backend — `relay.py`

Per-provider threads with `PER_PROVIDER_S 18` / `BG_DEADLINE_S 35`, results
probed for a valid playlist and minimum duration (`MIN_SECONDS 480`), capped at
`MAX_SOURCES 12`. `/hls` rewrites every playlist URI (including `EXT-X-KEY`,
`EXT-X-MAP`, `EXT-X-MEDIA`) back through itself. 64 MB segment LRU, 429 retries,
403 bare/headed fallback.

## Security posture

`server.py` sends a CSP, `nosniff`, `SAMEORIGIN`, `same-origin` referrer, blocks
dot/underscore paths and a list of extensions, and blocks traversal. CSP
whitelists `192.168.1.2` explicitly in `media-src` and `connect-src`. Library
and grab daemons send `Access-Control-Allow-Origin: *` with no auth — LAN-trust
model only.

## Known structural weaknesses

- One audio track survives a remux.
- Hardcoded absolute Windows path and LAN IP.
- Committed credentials.
- `library.json` and `*.log` are runtime output but tracked in git.
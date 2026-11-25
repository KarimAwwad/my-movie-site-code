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

Cloudflare Worker (\`worker.js\`) is a deployable alternative to \`relay.py\` with
5 providers and a 40-subrequest budget.

## Frontend (\`movie site/\`)

Static pages, one \`<div id="app">\` each, rendered by \`components.js\` and
\`script.js\`. \`watch.html\` loads hls.js, Supabase client, \`components.js\`,
\`script.js\`, and \`player-ui.js\`.

Source resolution order in \`script.js\`, by design:

1. \`librarySources(id)\` against :8788 — local file wins outright
2. on miss, \`beginFetch()\` → POST :8789 \`/grab\`, poll \`/queue\` every 2 s
3. provider buttons / \`/resolve\` against :8787

Guards: \`STALL_MS 20000\`, \`MAX_RETRIES 2\`, \`RESOLVE_TIMEOUT_MS 40000\`,
\`SOURCE_TTL_MS 150000\`, \`resolveSession\` + AbortController, and \`playToken\`
staleness check. \`pollMoreSources\` can switch away from a CAM source unless the
user selected it manually.

Progress is persisted to Supabase \`watch_progress\` every 10 seconds, on pause,
on \`visibilitychange\`, and on \`beforeunload\` via keepalive.

### Subtitle ownership and offset state

\`player-ui.js\` owns the visible subtitle menu (\`buildSubtitleMenu\`) and its
actual external-subtitle offset/scale state, persistence, and synchronization
controls. \`script.js\` owns native subtitle injection (\`addNativeSubs\`) and
external-track cleanup (\`clearExternalTrack\`), invokes the menu builder when
subtitle/manifest state changes, and publishes
\`window.ruinPlayer.getOffsetSec\` as a separate constant-zero accessor.

No caller of \`getOffsetSec\` was found in the shared frontend JavaScript files
inspected (\`script.js\`, \`player-ui.js\`, and \`components.js\`). The complete
consumer set has not been established, so the accessor's practical impact
remains unresolved. See \`KNOWN_ISSUES.md\` #4.

## Backend — \`library.py\`

Scan: \`rglob\` over the configured root. \`match_file()\` resolves a TMDB id by,
in order, \`[tmdb-<id>]\` tag → IMDb id lookup → TMDB title-and-year search.
The title search requires exact lowercase title equality and, when a year is
present, a matching year. Failures are reported as unmatched through
\`/probe\`.

Serving: browser-safe files (MP4/WebM plus supported video/audio codecs) are
byte-streamed with Range requests. Other files are remuxed once to fMP4 HLS in
a cache directory keyed by \`sha1(path|mtime|size)\`.

The current remux command maps \`0:v:0\` and \`0:a:0?\` only, then encodes AAC and
uses \`-ac 2\`. Additional audio streams are therefore not preserved by this
remux path, and the selected audio is downmixed to stereo.

Sprites: FFmpeg \`-skip_frame nokey\`, 10-second interval, 10x10 tiles, uploaded
to a Drive pool and indexed in Supabase \`trickplay\`. Without configuration,
the service degrades to local sprites.

## Backend — \`grab.py\`

\`/grab\` → TMDB \`external_ids\` → IMDb id → YTS \`list_movies\` → rank by quality
then seeds → hand magnet to FDM (or aria2/drop). The watcher files new videos
into the library as \`<Title> (Year) [tmdb-<id>].ext\`, then POSTs :8788 \`/scan\`.

Adoption is two-stage: \`adoptable()\` first checks title-token containment. If
that does not match, a size-based fallback can associate a file when the file
is at least 90% of the expected size and within 35% of the expected size.
See \`KNOWN_ISSUES.md\` #1 for the historical incident and current mechanism,
which are distinct.

## Backend — \`relay.py\`

Per-provider threads use \`PER_PROVIDER_S 18\` / \`BG_DEADLINE_S 35\`. Results
are probed for a valid playlist and minimum duration (\`MIN_SECONDS 480\`), and
are capped at \`MAX_SOURCES 12\`. \`/hls\` rewrites playlist URIs (including
\`EXT-X-KEY\`, \`EXT-X-MAP\`, and \`EXT-X-MEDIA\`) back through itself. The relay
uses a 64 MB segment LRU, 429 retries, and 403 bare/headed fallback.

## Security posture

\`server.py\` sends a CSP, \`nosniff\`, \`SAMEORIGIN\`, and a same-origin referrer
policy; it blocks dot/underscore paths, a list of extensions, and traversal.
The CSP explicitly lists \`192.168.1.2\` in \`media-src\` and \`connect-src\`.
Library and grab daemons send \`Access-Control-Allow-Origin: *\` without
authentication, reflecting a LAN-trust model.

## Known structural weaknesses

- One audio track survives the current HLS remux path.
- The subtitle UI state and the shared \`getOffsetSec\` accessor are separate;
  the accessor's callers and impact remain unverified.
- Hardcoded absolute Windows path and LAN IP.
- Private credentials are committed; the Supabase publishable key requires
  correct RLS policies rather than secrecy.
- \`library.json\` and log files are runtime output but are tracked in Git.

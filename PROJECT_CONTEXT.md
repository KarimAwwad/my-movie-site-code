# PROJECT_CONTEXT

Read this first in any new session. It replaces re-explaining the application.

## What RUIN TV is

A self-hosted movie streaming platform. Local media library, TMDB metadata,
browser playback with HLS remuxing, provider scraping as a fallback when a film
is not on disk.

## Current state (as of 2026-11-25)

Status: **functional, single-operator, undocumented.** No automated tests exist.
No documentation existed before this file. Verification has been manual and
ad-hoc.

Live evidence from `ruintv server/server.log` and `library.log`:

- Static server served `/`, `/search`, `/watch` successfully.
- Library daemon scanned 12 files, 0 unmatched, in ~5 seconds.
- `library.log` reports `no TMDB_KEY` on every start — only files carrying a
  `[tmdb-<id>]` tag can match. All 12 current library entries are tagged.
- Supabase trickplay index and Drive sprite pool are **not configured** on the
  operator machine; sprites stay local.

## Where it runs

| Component | Port | Entry point |
|---|---|---|
| Static site | 80 (falls back 8080) | `ruintv server/server.py` |
| Provider relay | 8787 | `ruin-stream/relay.py` |
| Library daemon | 8788 | `ruintv server/library.py` |
| Grab daemon | 8789 | `ruintv server/grab.py` |
| Worker (optional, Cloudflare) | n/a | `ruin-stream/worker.js` |

Windows host. Site root is hardcoded in `server.py` to
`D:\my development work\unfinished and finished development projects\movie site`.

## Config files and where they live

| File | Holds | Notes |
|---|---|---|
| `ruintv server/grab.json` | library/staging roots, client mode, TMDB key | **TMDB key committed in plaintext** |
| `ruin-stream/.env` | Supabase URL + publishable key | Committed |
| `ruin-stream/wrangler.toml` | TMDB JWT in `[vars]` | Committed |
| `ruin-stream/gdrive_accounts.json` | Drive refresh tokens | Committed |
| `ruintv server/library_overrides.json` | manual `path -> tmdb` pins | **Does not exist yet**; read by `library.py`, absent is fine |

`library.py` reads `TMDB_KEY` from env, `.env`, or `config.json` — **not** from
`grab.json`. That is why the key is missing at runtime. `grab.py` reads
`grab.json` only.

## Component versions

- `library.py` 1.2.5
- `grab.py` 1.3.5
- `relay.py` / `worker.js` — unversioned

## Ownership rules

- The GitHub repository is the source of truth.
- Only the operator decides when a phase is accepted.
- Nothing is deleted or overwritten without approval.
# PROJECT_CONTEXT

Read this first in any new session. It replaces re-explaining the application.

## What RUIN TV is

A self-hosted movie streaming platform. It combines a local media library,
TMDB metadata, browser playback with HLS remuxing, and separate source-resolution
services.

## Phase status

Phase 0 (documentation baseline) — **AWAITING OPERATOR REVIEW**. The project
documents are present on the repository's default branch. No application source
file has been modified by Phase 0.

## State immediately before Phase 0 (observed 2026-11-25)

Undocumented. No automated tests. Verification was manual and ad-hoc. This is
the pre-documentation baseline, not a description of the repository after the
Phase 0 documents were added.

Evidence from `ruintv server/server.log` and `library.log`:

- Static server served `/`, `/search`, and `/watch` successfully.
- Library daemon scanned 12 files, with 0 unmatched, in approximately 5 seconds.
- `library.log` reports `no TMDB_KEY` on every start. Without a key, files
  relying on IMDb lookup or title-and-year lookup cannot be matched; tagged
  files can still match. All 12 current library entries are tagged.
- Supabase trickplay indexing and the Drive sprite pool are not configured on
  the operator machine; sprites stay local.

## Current documented state

Seven core project documents plus `PATCH_NOTES.md` are maintained at the
repository root. `KNOWN_ISSUES.md` records 13 issues, including one S1 issue
and one unverified candidate. No application runtime behaviour changed during
Phase 0.

## Where it runs

| Component | Port | Entry point |
|---|---:|---|
| Static site | 80 (falls back to 8080) | `ruintv server/server.py` |
| Provider relay | 8787 | `ruin-stream/relay.py` |
| Library daemon | 8788 | `ruintv server/library.py` |
| Grab daemon | 8789 | `ruintv server/grab.py` |
| Worker (optional, Cloudflare) | n/a | `ruin-stream/worker.js` |

Windows host. Site root is hardcoded in `server.py` to
`D:\my development work\unfinished and finished development projects\movie site`.

## Config files and where they live

| File | Holds | Notes |
|---|---|---|
| `ruintv server/grab.json` | library/staging roots, client mode, TMDB key | TMDB key is committed in plaintext |
| `ruin-stream/.env` | Supabase URL and publishable key | Publishable key is intended for client use; verify database RLS policies |
| `ruin-stream/wrangler.toml` | TMDB credential in `[vars]` | Treat private credentials as exposed |
| `ruin-stream/gdrive_accounts.json` | Drive refresh tokens | Private credentials committed to the repository |
| `ruintv server/library_overrides.json` | manual `path -> tmdb` pins | Does not exist yet; absence is allowed |

`library.py` reads `TMDB_KEY` from its process environment, a `.env` file
beside `library.py`, or `config.json` beside `library.py`. It does not read
`grab.json` or `ruin-stream/.env`. This explains the repeated missing-key
warning with the current configuration layout. `grab.py` reads its settings
from `grab.json`.

## Component versions

- `library.py` 1.2.5
- `grab.py` 1.3.5
- `relay.py` / `worker.js` — unversioned

## Security note

The repository is public. Treat committed TMDB credentials and Google Drive
refresh tokens as exposed: revoke or rotate private credentials and remove
them from tracked files. A Supabase publishable key is not a secret by design;
confirm that Row Level Security (RLS) and table policies prevent unauthorized
access. Do not copy credential values into documentation or issue reports.

## Ownership rules

- The GitHub repository is the source of truth.
- Only the operator decides when a phase is accepted.
- Nothing is deleted or overwritten without approval.

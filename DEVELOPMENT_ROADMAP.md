# RUIN TV — Development Roadmap

## Phase 0 — Documentation Baseline (Completed)
- [x] Established repository documentation (`PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, `DEVELOPMENT_RULES.md`, `KNOWN_ISSUES.md`, `TEST_RESULTS.md`, `CHANGELOG.md`, `DEVELOPMENT_ROADMAP.md`, `PATCH_NOTES.md`).
- [x] Audited existing codebase and cataloged open bugs, security gaps, and architectural debt.

## Phase 1 — Hardening `grab.py` Movie Acquisition & Full-Cut Verification (Completed — `v1.5.0`)
**Goal:** Guarantee zero wrong-movie misfiles in `D:\movies\library`, protect bandwidth and data caps on Egyptian internet connections, and ensure full-length original-language releases.

- [x] **Pre-download IMDb & title/year lock:** Query TMDB (`external_ids`, `alternative_titles`) as ground truth; enforce IMDb equality when indexed on YTS, with token/connector-normalized title + exact release year + YTS `runtime` validation when TMDB carries an alternate IMDb ID.
- [x] **YTS mirror chain:** Prioritize active API endpoints (`movies-api.accel.li`, `yts.pw`, `yts.gg`) ahead of legacy mirrors.
- [x] **Hard `1080p` quality ceiling & dead-torrent floor:** Strictly cap selection at `max_quality` (`1080p`), removing upward fallback to `2160p` (4K) while retaining `720p` fallback, and enforce a hard `min_seeds` (`3`) floor so `0`-seed torrents fail before FDM opens.
- [x] **Full-length / uncut release priority:** Boost `Unrated`, `Extended`, `Uncut`, and `Director's Cut` torrents when multiple releases exist, and widen post-download runtime tolerance asymmetrically (`-10 min` short / `+20 min` long) so extended editions pass without relaxing short-clip rejection.
- [x] **Original audio language gate:** Enforce TMDB `original_language` (English, Korean, Spanish, Japanese, Hindi, etc., with subtitles handling translation). Allow multi-audio files that include the original track (preserving embedded dubs for Phases 2–3) and reject dub-only releases.
- [x] **Duplicate & already-in-library guard:** Reject `/grab` calls for movies already present in `D:\movies\library` or active in `/queue`, while permitting clean retries on `failed` or `cancelled` jobs.
- [x] **Queue persistence (`D:\movies\staging\jobs.json`):** Persist active jobs to disk so restarting `grab.py` mid-download still verifies and files completed FDM downloads.
- [x] **Multi-file torrent & Windows lock resilience:**
  - Ignore standalone sample/trailer/featurette clips under 50% of expected torrent size while `.temp` holds active downloads.
  - Treat transient Windows/FDM `WinError 32` file locks on completion as a retry on the next watcher scan rather than a permanent failure.
  - Subtract expected sizes of active queued jobs from available disk space when checking `min_free_gb`.
- [x] **Phase 1 sign-off verification:**
  - `24/24` offline unit tests passing (`phase1_tests.py`).
  - Live end-to-end grab and playback verified on *Knock at the Cabin (2023)* (`tmdb=631842`) plus live duplicate-library guard (`409` conflict).
  - Read-only 500-movie `/dry` sweep (`dry_sweep_500.py`) achieved **494/500 (98.80%)** match coverage (`>= 95.0%` gate), with all 6 misses audited and confirmed legitimate.

## Phase 2 — Multi-Audio Track Preservation (Current)
- [ ] Preserve all embedded audio streams (original language plus secondary dubbed tracks) during ingestion, indexing, and streaming so multi-audio releases remain intact.

## Phase 3 — Player Audio Switcher & Seekbar Fix
- [ ] **Audio track selector:** Add an audio track menu to the web player (mirroring the subtitle selector) to switch between original audio and embedded dub tracks on the fly.
- [ ] **Seekbar hover vs. playback timestamp fix:** Fix the timeline scrub offset where hovering/clicking a timestamp on the progress bar (e.g., `38:54`) seeks to an earlier playback time (`38:44`).

## Phase 4 — Configuration Decoupling
- [ ] Centralize hardcoded ports, hosts, mirror URLs, and filesystem paths across services into shared configuration.

## Post-Phase 4 Backlog
- [ ] **Secondary public torrent indexers (`1337x` / `EXT`):** Query broader public torrent indexers strictly as a fallback when YTS returns no eligible match (covering older classics, regional titles, and newer non-YTS releases), gated by the same `1080p` ceiling, `min_seeds`, size sanity, `ffprobe` runtime/resolution/language checks, and auto-deletion rules.
- [ ] **Series playback wiring:** Extend metadata resolution, episode mapping, and indexing to TV series.
- [ ] **Provider parity & test catalogue:** Reconcile playback behavior across sources and establish a repeatable end-to-end test catalogue.
- [ ] **Non-YTS media sources:** Add YouTube fallback (for short films and AI-generated titles) and embed providers (for Cam and early Web-DL releases unavailable on YTS).
- [ ] **Production readiness (future/optional):** Dedicated cloud/CDN hosting, database-backed catalog (replacing flat JSON indexes), user authentication, and licensed content sourcing if deployed publicly.
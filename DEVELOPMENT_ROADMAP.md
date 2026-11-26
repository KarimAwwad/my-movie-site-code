# RUIN TV — Development Roadmap

## Phase 0 — Documentation Baseline (Completed)
- [x] Established repository documentation (`PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, `DEVELOPMENT_RULES.md`, `KNOWN_ISSUES.md`, `TEST_RESULTS.md`, `CHANGELOG.md`, `DEVELOPMENT_ROADMAP.md`, `PATCH_NOTES.md`).
- [x] Audited existing codebase and cataloged open bugs, security gaps, and architectural debt.

## Phase 1 — Hardening `grab.py` Movie Acquisition & Full-Cut Verification (Completed — `v1.5.0`)
- [x] Pre-download IMDb & title/year lock, YTS mirror chain, hard `1080p` ceiling, `min_seeds` (`3`) floor, `Unrated`/`Extended`/`Uncut`/`Director's Cut` priority (`-10`/`+20 min`), original audio language gate, duplicate-library `409` guard, `jobs.json` persistence, and Windows/FDM lock resilience.
- [x] Verified with `24/24` unit tests (`phase1_tests.py`), live end-to-end playback (*Knock at the Cabin (2023)*), and `494/500 (98.80%)` match coverage (`dry_sweep_500.py`).

## Phase 2 — Multi-Source Dub & Original-Language Acquisition + Preservation (In Progress)
**Goal:** Acquire the original language track plus **every available dub and regional variant** across YTS, 1337x, EXT, and YouTube (`yt-dlp`), bundle them into a single multi-audio file with explicit language/regional tags, and expose all streams via HLS rendition groups for the player.

### 2A — `library.py` Multi-Audio Indexing & HLS Rendition Packaging (Completed — `v1.3.0`)
- [x] Full audio stream cataloging (`probe_details()` & `/index.json`) with regional variant labels and duplicate-label collision disambiguation.
- [x] All-track HLS packaging (`#EXT-X-MEDIA:TYPE=AUDIO`) for `2+` audio tracks with `-c:v copy` optimization and direct byte-streaming preserved for single-track files.
- [x] Verified with `6/6` unit/HTTP tests (`phase2a_tests.py`) and live daemon checks (`/health`, `/probe`, `/index.json`).

### 2B — YouTube Original + All Auto-Dubs Acquisition (`grab.py` `v1.6.0` — Implemented, Pending Live & Dry Verification)
- [x] **Enumerate all YouTube audio tracks:** Query `yt-dlp -J` on YouTube-sourced movies (or `?yt=<url>`) to detect the original audio stream plus **every** available auto-dubbed / multi-language audio stream while filtering out trailers, clips, and duration outliers.
- [x] **Download & mux all tracks:** Download `<=1080p` video + original audio + all unique auto-dub/regional streams, mux via `ffmpeg` into one `.mp4` with ISO 639-2 codes and regional track titles, file into `D:\movies\library`, delete staging files, and trigger `/scan`.

### 2C — Multi-Indexer Discovery (`YTS` + `1337x` + `EXT`) & Missing-Dub Muxing
- [ ] **Unified multi-source discovery:** Query **YTS**, **1337x**, and **EXT** together within the hard `1080p` ceiling, `min_seeds` floor, runtime/size sanity checks, and strict video-file safety filters.
- [ ] **Rank by total distinct audio/regional track count:** Score releases by the number of distinct languages and regional variants they bundle.
- [ ] **Supplemental dub extraction & muxing:** Use the highest-quality verified `1080p` original-language video as the base, pull additional dubbed releases from 1337x/EXT matching within tight sync tolerance, extract only their missing audio streams with `ffmpeg`, mux them into the master file with explicit ISO codes and regional labels, and delete temporary staging folders.

## Phase 3 — Player Audio Switcher & Seekbar Fix
- [ ] **Audio track selector:** Add an audio track menu to the web player (mirroring the subtitle selector) to switch between original audio and all embedded/regional dub tracks on the fly.
- [ ] **Seekbar hover vs. playback timestamp fix:** Fix the timeline scrub offset where hovering/clicking a timestamp on the progress bar (e.g., `38:54`) seeks to an earlier playback time (`38:44`).

## Phase 4 — Configuration Decoupling
- [ ] Centralize hardcoded ports, hosts, mirror URLs, and filesystem paths across services into shared configuration.

## Post-Phase 4 Backlog
- [ ] Series playback wiring, provider parity & test catalogue, embed/cam fallback providers, and production readiness.
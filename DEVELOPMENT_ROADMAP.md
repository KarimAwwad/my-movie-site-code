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

## Phase 2 — Multi-Source Dub & Original-Language Acquisition + Preservation (Current)
**Goal:** Acquire the original language track plus **every available dub and regional variant** across YTS, 1337x, EXT, and YouTube (`yt-dlp`), bundle them into a single multi-audio file with explicit language/regional tags, and expose all streams via HLS rendition groups for the player.

### 2A — `library.py` Multi-Audio Indexing & HLS Rendition Packaging
- [ ] **Full audio stream cataloging (`probe()` & `/index.json`):** Inspect and record every embedded audio stream (`index`, `lang`, `label`, `codec`, `channels`), preserving regional stream titles (e.g., `French (France)` vs. `French (Canada)`, `Spanish (Latin America)` vs. `Spanish (Spain)`) so identical ISO language codes never collide.
- [ ] **All-track HLS packaging (`#EXT-X-MEDIA:TYPE=AUDIO`):** Route any library file containing `2+` audio tracks through `/stream/<tmdb>/<i>` (HLS) with `-map 0:v:0 -map 0:a` and separate `#EXT-X-MEDIA:TYPE=AUDIO` renditions (`LANGUAGE="..."`, `NAME="..."`) in `master.m3u8` so `hls.js` exposes every language track cleanly, while keeping fast direct byte-streaming for single-track `.mp4` files.

### 2B — YouTube Original + All Auto-Dubs Acquisition (`yt-dlp`)
- [ ] **Enumerate all YouTube audio tracks:** Query `yt-dlp -J` on YouTube-sourced movies (such as *Remain Calm*) to detect the original audio stream plus **every** available auto-dubbed / multi-language audio stream.
- [ ] **Download & mux all tracks:** Download the `<=1080p` video stream alongside the original audio and all unique auto-dub streams, muxing them via `ffmpeg` into a single file with ISO 639-2 language codes and regional track titles embedded on each audio stream.

### 2C — Multi-Indexer Discovery (`YTS` + `1337x` + `EXT`) & Missing-Dub Muxing
- [ ] **Unified multi-source discovery:** Query **YTS**, **1337x**, and **EXT** together within the hard `1080p` ceiling, `min_seeds` floor, runtime/size sanity checks, and strict video-file safety filters.
- [ ] **Rank by total distinct audio/regional track count:** Score releases by the number of distinct languages and regional variants they bundle so full multi-language releases (e.g., English, Italian, French (France), French (Canada), German, Hindi, Spanish (Latin America), Polish, Arabic, etc.) beat 2-track dual-audio releases, which beat single-track releases.
- [ ] **Supplemental dub extraction & muxing:** When no single release carries every available dub, use the highest-quality verified `1080p` original-language video as the base, pull additional dubbed releases from 1337x/EXT matching within tight sync tolerance, extract only their missing audio streams with `ffmpeg`, mux them into the master file with explicit ISO codes and regional labels, and immediately delete temporary staging folders.

## Phase 3 — Player Audio Switcher & Seekbar Fix
- [ ] **Audio track selector:** Add an audio track menu to the web player (mirroring the subtitle selector) to switch between original audio and all embedded/regional dub tracks on the fly.
- [ ] **Seekbar hover vs. playback timestamp fix:** Fix the timeline scrub offset where hovering/clicking a timestamp on the progress bar (e.g., `38:54`) seeks to an earlier playback time (`38:44`).

## Phase 4 — Configuration Decoupling
- [ ] Centralize hardcoded ports, hosts, mirror URLs, and filesystem paths across services into shared configuration.

## Post-Phase 4 Backlog
- [ ] **Series playback wiring:** Extend metadata resolution, episode mapping, and indexing to TV series.
- [ ] **Provider parity & test catalogue:** Reconcile playback behavior across sources and establish a repeatable end-to-end test catalogue.
- [ ] **Embed/Cam fallback providers:** Support embed providers only as a last resort for Cam/early releases unavailable across YTS, 1337x, EXT, and YouTube (noting embed players only serve a single baked-in audio track).
- [ ] **Production readiness (future/optional):** Dedicated cloud/CDN hosting, database-backed catalog (replacing flat JSON indexes), user authentication, and licensed content sourcing if deployed publicly.
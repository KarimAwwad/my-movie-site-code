# Changelog

## [Unreleased]
- Phase 2A: Upgrade `library.py` `probe()`, `/index.json`, and FFmpeg HLS remuxing to preserve all embedded audio tracks and regional labels via `#EXT-X-MEDIA:TYPE=AUDIO` rendition groups.
- Phase 2B: Add YouTube (`yt-dlp`) original + all auto-dubbed multi-language audio extraction and muxing.
- Phase 2C: Add unified `YTS` + `1337x` + `EXT` multi-language/regional dub discovery, track-count ranking, and supplemental missing-dub extraction/muxing.

## [1.5.0] — 2026-11-25
### Added
- Hard `1080p` quality ceiling (`max_quality`) removing upward fallback to `2160p` (4K) while retaining `720p` fallback.
- Priority boost for `Unrated`, `Extended`, `Uncut`, and `Director's Cut` releases alongside an asymmetric runtime window (`-10 min` short / `+20 min` long).
- Original audio language verification (`verify_audio_language`) preserving multi-audio releases containing the original track while rejecting dub-only replacements.
- Duplicate and already-in-library `/grab` guard (`409` conflict when active in queue or present in `D:\movies\library`, while allowing retries on `failed`/`cancelled` jobs).
- Restart queue persistence via `D:\movies\staging\jobs.json`.
- Bonus-clip `.temp` size guard (`<50%` expected size), transient Windows/FDM `WinError 32` move retry logic, hard `min_seeds` (`3`) floor, and concurrent queued disk-space accounting.
- Expanded `phase1_tests.py` to 24 offline unit tests (`U1`–`U24`) and added `dry_sweep_500.py` (`494/500 = 98.80%` verified).

## [1.4.3] — 2026-11-25
- Added `movies-api.accel.li` as primary YTS API endpoint ahead of `yts.pw` and legacy mirrors.
- Added exact title + exact release year fallback in `yts_candidates()` when TMDB's IMDb ID is absent on YTS (fixing *Knock at the Cabin (2023)* `tt8272064` vs `tt15679400`).
- Added unit test `U14` in `phase1_tests.py`.

## [1.4.2] — 2026-11-25
- Added `yts.pw` to `YTS_HOSTS` and made `yts_hosts` configurable in `grab.json`.

## [1.4.1] — 2026-11-24
- Replaced size-only fallback with pre-download IMDb/year/MB-per-minute gates and post-download `ffprobe` runtime, widescreen resolution, and identity verification.
- Added `staging/_review` isolation (`needs_review`) with `POST /queue/approve` and `POST /queue/reject`, plus automatic deletion of rejected downloads.
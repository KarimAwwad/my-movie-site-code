# Known Issues

## Active / Open Issues

### [MEDIUM] Media Pipeline — Multi-Indexer Discovery & Supplemental Dub Muxing (Phase 2C)
- **Status:** Open (Phase 2A completed in `library.py` v1.3.0; Phase 2B implemented in `grab.py` v1.6.0; Phase 2C remaining)
- **Details:**
  1. `grab.py` now supports YTS + YouTube (`yt-dlp`) multi-audio acquisition, and still needs unified `1337x` + `EXT` discovery, track-count ranking, and supplemental missing-dub extraction/muxing (Phase 2C).
  2. External embed providers (`vixsrc`, `vidsrc`) do not expose switchable audio tracks (single baked-in audio only), making local multi-source acquisition and muxing essential for audio variety.

### [MEDIUM] Player UI — Audio Switcher & Seekbar Hover Preview vs. Playback Time Offset
- **Status:** Open (Queued for Phase 3)
- **Observed:**
  1. Web player needs an audio selection panel matching the existing subtitle menu so users can switch between original and all embedded/regional dubbed audio streams exposed by `library.py` v1.3.0 (`#EXT-X-MEDIA:TYPE=AUDIO`).
  2. Clicking/hovering at `38:54` on the timeline progress bar seeks playback to `38:44` (a ~10-second discrepancy between the preview tooltip/thumb position and bottom-left playback clock).
- **Suspected Cause (Seekbar):** Offset/padding mismatch in timeline click coordinate calculation or `<video>` keyframe seek snapping.

### [LOW] Architecture — Hardcoded Configuration & Flat JSON Storage
- **Status:** Open (Queued for Phase 4 & Backlog)
- **Details:** Ports, hosts, and paths are duplicated across scripts; flat JSON files will need database migration before any multi-user public deployment.

---

## Mitigated / Resolved Issues

### [MEDIUM -> MITIGATED] `grab.py` (`v1.6.0`) — YouTube (`yt-dlp`) Original + All Auto-Dubs Acquisition & Muxing (Phase 2B)
- **Mitigation (`v1.6.0`):**
  1. Added YouTube search and direct `?yt=<url>` fallback in `resolve()` with trailer/clip/reaction filtering and runtime / `yt_min_unknown_secs` gating.
  2. Enumerated original audio plus all unique auto-dubbed and regional tracks from `yt-dlp -J`, muxing `<=1080p` video + all audio tracks via `ffmpeg` with ISO 639-2 codes and regional titles, then auto-filing and cleaning staging folders.
- **Verification:** Offline unit & HTTP suite (`phase2b_tests.py`) authored; awaiting local unit execution, read-only `/dry` sweep (`dry_sweep_yt.py`), and live multi-dub YouTube grab + HLS playback verification.

### [MEDIUM -> RESOLVED] `library.py` (`v1.3.0`) — Multi-Audio Stream Cataloging & HLS `#EXT-X-MEDIA:TYPE=AUDIO` Rendition Packaging (Phase 2A)
- **Resolution (`v1.3.0`):** Cataloged all embedded audio streams with regional variant labels (`French (France)` vs. `French (Canada)`, `Spanish (Latin America)` vs. `Spanish (Spain)`) and routed `2+` audio files through `#EXT-X-MEDIA:TYPE=AUDIO` HLS renditions while keeping direct byte-streaming for single-track files.
- **Verification:** `6/6` tests passing in `phase2a_tests.py` and live daemon verified on `:8788` (`7` matched, `0` unmatched).

### [HIGH -> RESOLVED] `grab.py` (`v1.5.0`) — Quality Ceiling, Uncut Priority, Audio Gate & Edge-Case Hardening
- **Resolution (`v1.5.0`):** Enforced hard `1080p` ceiling, `min_seeds: 3` floor, `Unrated`/`Extended`/`Uncut`/`Director's Cut` priority (`-10`/`+20 min`), original audio language verification, duplicate-library `409` guard, `jobs.json` persistence, and Windows/FDM lock/bonus-clip guards.
- **Verification:** `24/24` unit tests passing and `494/500` (`98.80%`) match coverage on `dry_sweep_500.py`.

### [CRITICAL -> MITIGATED] Issue #1 — Wrong Movie Misfiled Into Library (`grab.py`)
- **Mitigation (`v1.4.1`–`v1.5.0`):** Pre-download IMDb + normalized title/year/runtime locks, MB/min size floors, post-download `ffprobe` runtime/resolution/language/identity gates, `_review` isolation, and auto-deletion of rejected downloads.
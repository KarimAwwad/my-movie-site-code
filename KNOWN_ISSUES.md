# Known Issues

## Active / Open Issues

### [MEDIUM] Media Pipeline — Multi-Audio Track Preservation
- **Status:** Open (Current — Phase 2)
- **Details:** Embedded secondary audio tracks preserved by `grab.py` `v1.5.0` need to remain intact through indexing/streaming without being dropped or downmixed to a single track.

### [MEDIUM] Player UI — Audio Switcher & Seekbar Hover Preview vs. Playback Time Offset
- **Status:** Open (Queued for Phase 3)
- **Observed:**
  1. Web player needs an audio selection panel matching the existing subtitle menu so users can switch between original and embedded dubbed audio streams.
  2. Clicking/hovering at `38:54` on the timeline progress bar seeks playback to `38:44` (a ~10-second discrepancy between the preview tooltip/thumb position and bottom-left playback clock).
- **Suspected Cause (Seekbar):** Offset/padding mismatch in timeline click coordinate calculation or `<video>` keyframe seek snapping.

### [LOW] Architecture — Hardcoded Configuration & Flat JSON Storage
- **Status:** Open (Queued for Phase 4 & Backlog)
- **Details:** Ports, hosts, and paths are duplicated across scripts; flat JSON files will need database migration before any multi-user public deployment.

---

## Mitigated / Resolved Issues

### [HIGH -> RESOLVED] `grab.py` (`v1.5.0`) — Quality Ceiling, Uncut Priority, Audio Gate & Edge-Case Hardening
- **Resolution (`v1.5.0`):**
  1. Enforced hard `1080p` quality ceiling (removed `2160p` fallback) and hard `min_seeds` (`3`) floor.
  2. Added `Unrated`/`Extended`/`Uncut`/`Director's Cut` priority with asymmetric runtime tolerance (`-10 min` / `+20 min`).
  3. Added original audio language verification while preserving multi-audio tracks for Phases 2–3.
  4. Added duplicate/already-in-library `/grab` guard, `D:\movies\staging\jobs.json` restart persistence, bonus-clip `.temp` size guard (`<50%`), transient Windows/FDM `WinError 32` move retries, and concurrent queued disk-space accounting.
- **Verification:** `24/24` unit tests passing and `494/500` (`98.80%`) match coverage on the 500-movie `/dry` sweep.

### [CRITICAL -> MITIGATED] Issue #1 — Wrong Movie Misfiled Into Library (`grab.py`)
- **Mitigation (`v1.4.1`–`v1.5.0`):** Removed blind size-only fallback; added pre-download IMDb + normalized title/year/runtime locks, MB/min size floors, widescreen `ffprobe` resolution bands (`1920x800` / `1920x804`), post-download duration/language/identity verification, `_review` parking, and automatic deletion of mismatched downloads.
- **Cleanup:** Audited `D:\movies\library` with `ffprobe` and purged 6 misfiled 2026 titles from an earlier scrapped build.
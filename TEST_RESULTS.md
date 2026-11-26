# Test Results

## 2026-11-26 — `grab.py` v1.6.0 Phase 2B Implementation (Pending Local Execution)

### Verification Checklist
1. **Regression + Phase 2B Offline Suites:**
   - `python phase1_tests.py` -> expected `24/24 PASS`
   - `python phase2b_tests.py` -> expected `5/5 PASS`
2. **Read-Only `/dry` Verification (`dry_sweep_yt.py`):**
   - Restart `grab.py` (`v1.6.0`), verify `GET /health` reports `"version": "1.6.0"`, `"ytdlp": true`, `"ffmpeg": true`, and run `python dry_sweep_yt.py` to inspect read-only YTS + YouTube fallback resolution and detected audio tracks without downloading.
3. **Live End-to-End YouTube Multi-Dub Grab & `library.py` HLS Verification:**
   - Trigger `POST /grab?tmdb=<id>` (or `&yt=<url>`) on a multi-dub YouTube film -> verify muxed `.mp4` lands in `D:\movies\library`, staging folder is deleted, `library.py` `/probe` lists all embedded regional/dub tracks, and `GET /stream/<tmdb>/0` serves `#EXT-X-MEDIA:TYPE=AUDIO` renditions for every track.

---

## 2026-11-26 — `library.py` v1.3.0 Phase 2A Final Verification

### 1. Offline Unit & HTTP Suite (`python phase2a_tests.py`)
- **Result:** `6/6 PASS` (`test_u01`–`test_u06` in `0.636s`).

### 2. Live Daemon Integration (`:8788`)
- `GET /health`: Returned `{"ok": true, "version": "1.3.0", "files": 7, "ffmpeg": true, "multi_audio": true}`.
- `GET /probe` & `GET /index.json?tmdb=631842`: Verified all 7 library files matched (`0` unmatched) with accurate `audio_tracks` metadata (`1 audio (English)` on tagged files, `1 audio (Track 1)` on untagged YTS files, `direct: true` preserved for single-track `.mp4`).

---

## 2026-11-25 — `grab.py` v1.5.0 Phase 1 Final Verification & 500-Movie Sweep

### 1. Offline Unit Suite (`python phase1_tests.py`)
- **Result:** `24/24 PASS` (`U1`–`U24`).

### 2. Live `/health` & Duplicate-Library Guard Verification
- `GET /health`: Returned `{"ok": true, "version": "1.5.0", "mode": "fdm", "max_quality": "1080p", "min_seeds": 3, "ffprobe": true, "tmdb_key": true}`.
- `POST /grab?tmdb=631842`: Returned `409` conflict (`"already in library: Knock at the Cabin (2023) [tmdb-631842].mp4"`).

### 3. Read-Only 500-Movie `/dry` Sweep (`python dry_sweep_500.py`)
- **Result:** `494/500 matched (98.80%)` — **PASS**.
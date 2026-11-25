# Test Results

## 2026-11-25 — `grab.py` v1.5.0 Phase 1 Final Verification & 500-Movie Sweep

### 1. Offline Unit Suite (`python phase1_tests.py`)
- **Result:** `24/24 PASS`
  - `U1`–`U14`: Core runtime, widescreen resolution, identity, container title, IMDb mismatch, size sanity, and stale-IMDb title+year fallback gates.
  - `U15`: Hard `1080p` ceiling blocks `2160p`-only releases -> `PASS`
  - `U16`: `Unrated` / `Extended` release prioritized over standard `1080p` -> `PASS`
  - `U17`: Hard `min_seeds` (`3`) floor blocks `0`-seed dead torrents -> `PASS`
  - `U18`: Normalized punctuation fallback + pre-download YTS runtime gate -> `PASS`
  - `U19`: Duplicate active job guard allows retries on `failed` jobs & tracks `reserved_bytes()` -> `PASS`
  - `U20`: Extended cut (`+15 min`) passes asymmetric runtime tolerance (`-10` / `+20 min`) -> `PASS`
  - `U21`: Dub-only audio language mismatch rejects -> `PASS`
  - `U22`: Untagged (`und`) YTS audio stream passes -> `PASS`
  - `U23`: Dual-audio release containing original language passes -> `PASS`
  - `U24`: Standalone bonus clip (`<50%` expected size) deferred while `.temp` is active -> `PASS`

### 2. Live `/health` & Duplicate-Library Guard Verification
- `GET /health`: Returned `{"ok": true, "version": "1.5.0", "mode": "fdm", "max_quality": "1080p", "min_seeds": 3, "ffprobe": true, "tmdb_key": true}`.
- `POST /grab?tmdb=631842`: Immediately returned `409` conflict (`"already in library: Knock at the Cabin (2023) [tmdb-631842].mp4"`) without launching FDM.

### 3. Read-Only 500-Movie `/dry` Sweep (`python dry_sweep_500.py`)
- **Result:** `494/500 matched (98.80%)` — **PASS** (exceeds `>= 95.0%` sign-off gate; report saved in `dry_sweep_500_report.json`).
- **Audit of all 6 misses (0 false positives):**
  - *Chainsaw Man - The Movie: Reze Arc* (`2025`, `tmdb=1218925`): Only `2160p` (4K) exists on YTS — accurately blocked by hard `1080p` ceiling.
  - *Digger* (`2026`, `tmdb=1248832`): Unreleased 2026 film — accurately rejected.
  - *The Imitation Game* (`2014`, `tmdb=205596`): `1080p` and `720p` torrents report `0` seeds / `0` peers on YTS API (`2160p` has 100 seeds) — accurately blocked by hard `1080p` ceiling + `min_seeds: 3`.
  - *The Mask* (`1994`, `tmdb=854`), *Pixels* (`2015`, `tmdb=257344`), *Hunting Season* (`2025`, `tmdb=1387382`): Confirmed unindexed on YTS mirrors via direct API and `/dry` checks.

---

## 2026-11-25 — `grab.py` v1.4.3 Phase 1 Baseline & Live Integration

### 1. Offline Unit Suite (`python phase1_tests.py`)
- **Result:** `14/14 PASS` (`U1`–`U14`).

### 2. Local Library Audit (`ffprobe` across `D:\movies\library`)
- Audited 12 existing `.mp4` files: kept 6 verified titles (*Insidious (2010)*, *Insidious: Chapter 3 (2015)*, *Insidious: The Last Key (2018)*, *Insidious: The Red Door (2023)*, *Michael Jackson's Thriller (1983)*, *Migration (2023)*), purged 6 misfiled 2026 titles from an earlier scrapped build, and resynced `library.py` via `POST /scan`.

### 3. Live End-to-End Grab & Playback (`tmdb=631842` — *Knock at the Cabin (2023)*)
- `GET /dry?tmdb=631842` -> `POST /grab?tmdb=631842` -> FDM download -> passed `100 min` (`1:40:06`), widescreen resolution, and identity gates -> auto-filed to `D:\movies\library\Knock at the Cabin (2023) [tmdb-631842].mp4` -> staging folder deleted -> verified playback with Arabic subtitles in web player.
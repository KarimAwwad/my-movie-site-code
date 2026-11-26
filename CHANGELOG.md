# Changelog

## [Unreleased]
- Phase 2C: Add unified `YTS` + `1337x` + `EXT` multi-language/regional dub discovery, track-count ranking, and supplemental missing-dub extraction/muxing.

## [1.7.0] — 2026-11-26
### Added (Phase 2B — `grab.py` v1.6.0)
- Added YouTube (`yt-dlp`) acquisition fallback (`yt_candidates`, `yt_probe_video`, `select_yt_streams`, `run_yt_job`) when YTS has no valid torrent or `?yt=<url>` is passed to `/dry` or `/grab`.
- Filtered out YouTube trailers, teasers, clips, reviews, reactions, and low-overlap uploads (`yt_title_acceptable`), while enforcing TMDB runtime or `yt_min_unknown_secs` (`90s`) when TMDB runtime is `0`.
- Enumerated original audio (`language_preference > 0` / `"original"` / TMDB `original_language`) plus **every** unique auto-dubbed and regional audio track (`French (France)` vs. `French (Canada)`, `Spanish (Latin America)` vs. `Spanish (Spain)`, etc.), deduplicating alternate bitrates per `(language, original)` bucket.
- Muxed `<=1080p` video + all selected audio tracks via `ffmpeg` (`build_yt_mux_cmd`) into a single `.mp4` with ISO 639-2 language codes, regional stream titles, and `default` disposition on the original track, then filed into `D:\movies\library` and deleted temporary staging folders.
- Added `phase2b_tests.py` offline unit/HTTP suite and `dry_sweep_yt.py` read-only `/dry` sweep script.

## [1.6.0] — 2026-11-26
### Added (Phase 2A — `library.py` v1.3.0)
- Full embedded audio stream cataloging in `probe_details()`, `/index.json`, `library.json`, and `/probe` (`index`, `lang`, `raw_lang`, `label`, `codec`, `channels`, `default`), preserving regional variants (`French (France)` vs. `French (Canada)`, `Spanish (Latin America)` vs. `Spanish (Spain)`, `Portuguese (Brazil)` vs. `Portuguese (Portugal)`) and disambiguating identical language codes.
- Multi-audio HLS rendition packaging (`#EXT-X-MEDIA:TYPE=AUDIO`) for any file with `2+` audio tracks (`direct: false`, `kind: "hls"`), using FFmpeg `-var_stream_map` with `-c:v copy` for 8-bit H.264 sources and `libx264` fallback for non-H.264 sources, while retaining direct byte-streaming for single-track `.mp4`/`.m4v`/`.webm` files.
- Fixed `.lang` sidecar subtitle matching in `sidecar_subs()` (e.g. `<stem>.ar.srt`) and added `phase2a_tests.py` offline unit/HTTP suite (`6/6 PASS`).

## [1.5.0] — 2026-11-25
### Added
- Hard `1080p` quality ceiling (`max_quality`) removing upward fallback to `2160p` (4K) while retaining `720p` fallback.
- Priority boost for `Unrated`, `Extended`, `Uncut`, and `Director's Cut` releases alongside an asymmetric runtime window (`-10 min` short / `+20 min` long).
- Original audio language verification (`verify_audio_language`) preserving multi-audio releases containing the original track while rejecting dub-only replacements.
- Duplicate and already-in-library `/grab` guard (`409` conflict when active in queue or present in `D:\movies\library`, while allowing retries on `failed`/`cancelled` jobs).
- Restart queue persistence via `D:\movies\staging\jobs.json`.
- Bonus-clip `.temp` size guard (`<50%` expected size), transient Windows/FDM `WinError 32` move retry logic, hard `min_seeds` (`3`) floor, and concurrent queued disk-space accounting.
- Expanded `phase1_tests.py` to 24 offline unit tests (`U1`–`U24`) and added `dry_sweep_500.py` (`494/500 = 98.80%` verified).
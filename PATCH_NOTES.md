# PATCH_NOTES — Phase 2B (`grab.py` v1.6.0)
YouTube (`yt-dlp`) original + all auto-dubbed multi-language audio acquisition and muxing.

## Files replaced / added

| File | Change |
|---|---|
| `ruintv server/grab.py` | 1.5.0 → 1.6.0, YouTube (`yt-dlp`) search/URL fallback, original + all regional/auto-dub stream enumeration, FFmpeg multi-audio MP4 muxing |
| `ruintv server/phase2b_tests.py` | Offline unit & HTTP test suite (`U01`–`U05`) |
| `ruintv server/dry_sweep_yt.py` | Read-only `/dry` verification sweep script |
| `CHANGELOG.md` | Added `[1.7.0]` Phase 2B entry |
| `DEVELOPMENT_ROADMAP.md` | Marked Phase 2A completed and Phase 2B implemented |
| `KNOWN_ISSUES.md` | Updated Phase 2A to Resolved and Phase 2B to Mitigated |
| `TEST_RESULTS.md` | Added Phase 2A pass results and Phase 2B verification checklist |
| `PATCH_NOTES.md` | This file |

## Testing Steps

1. **Offline Regression & Phase 2B Unit Suite:**
   ```powershell
   cd "D:\my development work\unfinished and finished development projects\ruintv server"
   python phase1_tests.py
   python phase2b_tests.py
# PATCH_NOTES — Phase 1
Issue #1 only. No audio, subtitle or unrelated change.

## Files replaced / added

| File | Change |
|---|---|
| `ruintv server/grab.py` | 1.3.5 → 1.4.1, verification gates + audit fixes |
| `ruintv server/grab.json` | three verification keys added, `fdm` retained |
| `ruintv server/phase1_tests.py` | offline unit test harness calling `grab.evaluate()` |
| `KNOWN_ISSUES.md` | #1 closed, #14 added, #12 updated |
| `CHANGELOG.md` | Phase 1 entry |
| `TEST_RESULTS.md` | Phase 1 entry |
| `PATCH_NOTES.md` | this file |

## Packaging (PowerShell)

```powershell
cd "path\to\my-movie-site-code"
Compress-Archive -Path "ruintv server\grab.py","ruintv server\grab.json","ruintv server\phase1_tests.py",KNOWN_ISSUES.md,CHANGELOG.md,TEST_RESULTS.md,PATCH_NOTES.md -DestinationPath phase1.zip -Force
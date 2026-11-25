# PATCH_NOTES — Phase 0 documentation revision r2

Status: **AWAITING OPERATOR REVIEW**.

## Scope

Documentation only. No application source files changed. No runtime behaviour
changed.

## Files updated

| File | Change |
|---|---|
| \`PROJECT_CONTEXT.md\` | Phase status, pre-Phase-0 baseline, configuration and security notes |
| \`ARCHITECTURE.md\` | Subtitle state/accessor ownership and current adoption stages |
| \`KNOWN_ISSUES.md\` | Corrected subtitle-offset description; separated historical/current adoption behavior; dead-code candidates; credential exposure |
| \`TEST_RESULTS.md\` | Revision log and verified repository/documentation state |
| \`CHANGELOG.md\` | Phase 0 review revision and status |
| \`DEVELOPMENT_ROADMAP.md\` | Review status and revised sequencing |
| \`PATCH_NOTES.md\` | This revision record and PowerShell verification/rollback steps |

\`DEVELOPMENT_RULES.md\` was not changed.

## Files deleted

None.

## Packaging

From the repository root in PowerShell:

    Compress-Archive -Path PROJECT_CONTEXT.md,ARCHITECTURE.md,DEVELOPMENT_RULES.md,KNOWN_ISSUES.md,TEST_RESULTS.md,CHANGELOG.md,DEVELOPMENT_ROADMAP.md,PATCH_NOTES.md -DestinationPath phase0-docs-r2.zip -Force

## Verification

Run in PowerShell from the repository root:

1. Confirm the documentation files exist:

       Get-ChildItem -File -Filter *.md | Select-Object -ExpandProperty Name

   Expect \`README.md\` plus the eight Phase 0 documentation files.

2. Confirm only the seven documentation files listed above changed in the
   Phase 0 r2 commit:

       git show --name-only --format="" HEAD

   No application source files should appear.

3. Confirm the subtitle accessor and implementation locations:

       Select-String -Path "movie site\script.js" -Pattern "getOffsetSec"
       Select-String -Path "movie site\player-ui.js" -Pattern "setSubOffset|subOffset|autoSync"

4. Confirm the media remux mapping:

       Select-String -Path "ruintv server\library.py" -Pattern "0:a:0"

5. Confirm current adoption logic markers:

       Select-String -Path "ruintv server\grab.py" -Pattern "def adoptable|MIN_SIZE_RATIO|0.35"

6. Confirm the working tree is clean after the commit:

       git status --short

   Expect no output unless the operator has unrelated local changes.

These checks validate documentation/source references only. They do not
reproduce runtime bugs or certify browser playback.

## Rollback

This revision changes documentation only. To reverse the single documentation
revision commit:

    git revert <phase-0-r2-commit-sha>

Do not use a broad reset or force-push. If later commits depend on these files,
review the revert before applying it.

## Known limitations

- The complete consumer set for \`window.ruinPlayer.getOffsetSec\` remains
  unverified. No call site was found in the shared frontend JS files inspected.
- \`components.js\`, \`style.css\`, the complete relay internals, and the HLS path
  were not exhaustively audited during Phase 0.
- The active LAN address has not been confirmed by the operator.
- No application issue was reproduced during this documentation-only revision.

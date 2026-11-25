# CHANGELOG

Newest first. One entry per accepted phase or documentation revision.

## [Phase 0] 2026-11-25 — documentation baseline — AWAITING OPERATOR REVIEW

Added at repository root: \`PROJECT_CONTEXT.md\`, \`ARCHITECTURE.md\`,
\`DEVELOPMENT_RULES.md\`, \`KNOWN_ISSUES.md\`, \`TEST_RESULTS.md\`,
\`CHANGELOG.md\`, \`DEVELOPMENT_ROADMAP.md\`, and \`PATCH_NOTES.md\`.

Seeded from a read-only inspection of \`movie site/\`, \`ruin-stream/\`, and
\`ruintv server/\`. No application source file changed. Thirteen issues are
recorded: one S1 known wrong-association/security issue, and one S4 candidate.

### Observed baseline before this phase

Undocumented, no automated tests found, and manually verified only. Library:
12 files, all 12 tagged, 0 unmatched. TMDB key absent at library runtime.
Supabase and Drive sprite configuration absent. Playback success and association
accuracy have not been measured.

### Revision r2 — operator review

- Corrected the subtitle-offset issue: the UI implements offset/persistence/
  auto-sync; the separate shared accessor returns zero, and its consumers are
  not yet established.
- Separated the historical Valorant/Insidious incident from the current
  size-based fallback.
- Reclassified suspected dead code as a candidate pending caller/runtime review.
- Changed Phase 0 status to AWAITING OPERATOR REVIEW.
- Converted documentation verification commands to PowerShell.
- Split the pre-Phase-0 baseline from the current documented state.
- Clarified credential exposure and the different role of the Supabase
  publishable key.

### State after Phase 0 documentation

The application runtime is unchanged. The architecture, known issues, test
baseline, and roadmap are now documented. No issue was fixed by documentation.

## [pre-Phase 0] — undocumented baseline

\`library.py\` 1.2.5, \`grab.py\` 1.3.5, \`relay.py\`, \`worker.js\`, and static
frontend. No project changelog existed before Phase 0.

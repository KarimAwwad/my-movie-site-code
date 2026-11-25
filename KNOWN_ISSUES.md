# KNOWN_ISSUES

Severity: **S1** wrong data, data loss, or exposed private credentials ·
**S2** broken feature · **S3** degraded quality / unresolved API contract ·
**S4** hygiene. Status: OPEN / MITIGATED / CLOSED / CANDIDATE (reported, callers
or runtime use not yet inspected).

| # | Sev | Area | Issue | Status |
|---|---|---|---|---|
| 1 | S1 | grab.py | After title-token matching fails, \`adoptable()\` can fall back to file-size matching. Current fallback requires at least 90% of expected size and a difference within 35%; renamed, translated, or unrelated similarly-sized files remain a risk. | OPEN |
| 2 | S2 | library.py | HLS remux maps \`0:v:0\` / \`0:a:0?\` and uses \`-ac 2\`. Additional audio streams are discarded and the selected audio is downmixed to stereo. | OPEN |
| 3 | S2 | frontend | No dedicated audio-track selector was found in the player UI. The quality menu handles audio-only renditions, which is a different feature. | OPEN |
| 4 | S3 | frontend/API | \`player-ui.js\` implements subtitle offset adjustment, persistence, and automatic synchronization. Separately, \`script.js\` publishes \`window.ruinPlayer.getOffsetSec\` as \`() => 0\`. No caller was found in the shared frontend JavaScript files inspected; the full consumer set and practical impact remain unverified. | OPEN |
| 5 | S2 | config | \`library.py\` reads \`TMDB_KEY\` from its environment, its adjacent \`.env\`, or adjacent \`config.json\`; it does not read \`grab.json\` or \`ruin-stream/.env\`. Runtime logs report \`no TMDB_KEY\`, so untagged files cannot use IMDb/title-and-year lookup. | OPEN |
| 6 | S2 | frontend | Series playback is not wired: \`series-play\` displays an unavailable message and \`ruin:episode\` is a stub. | OPEN |
| 7 | S2 | consistency | \`worker.js\` exposes 5 providers; the frontend copy and \`relay.py\` describe 14. | OPEN |
| 8 | S3 | server.py | \`SITE_DIR\` is hardcoded to an absolute Windows path; moving the folder or running on another machine requires configuration changes. | OPEN |
| 9 | S3 | server.py | CSP explicitly lists \`192.168.1.2\`. Confirm whether that is the active host; other LAN addresses are not explicitly listed. | OPEN |
| 10 | S1 | security | TMDB credentials and Google Drive refresh tokens are committed in the public repository. Treat private credentials as exposed and rotate/revoke them. The Supabase publishable key is designed for client use; verify RLS and table policies. | OPEN |
| 11 | S4 | repo | \`library.json\` and five log files are runtime output but are tracked in Git. | OPEN |
| 12 | S4 | repo | No automated tests were found in the repository during the Phase 0 inspection. | OPEN |
| 13 | S4 | frontend | Suspected dead or duplicate code: \`bindPlayerControls()\` fallback, \`embedMode()\` / \`player-fallback\` iframe path, and empty \`LABEL_OVERRIDES\` / \`BLOCKED_MOVIE_IDS\`. Callers and runtime usage have not been fully inspected. | CANDIDATE |

## Detail

### #1 — historical cause versus current mechanism

These are different and must not be conflated.

**Historical.** The incident recorded in \`grab.py\`'s docstring — a 3-minute
Valorant clip filed as *Insidious Chapter 3*, the job then closed, and the real
film orphaned — was attributed to an older "only one job, take it" rule. That
rule is not the current implementation. The incident demonstrates the failure
class; it is not a reproduction of today's code.

**Current.** The current implementation checks title-token containment first.
Only when that does not match does it try a size-based fallback. The candidate
must be at least 90% of the expected size and within 35% of that expected size.
This is narrower than the old rule, but a renamed/translated file or an
unrelated file of coincidentally similar size may still be associated
incorrectly. The current fallback has not been reproduced as a wrong match in
the Phase 0 inspection.

### #4 — subtitle offset state and the accessor

\`player-ui.js\` holds the offset the user actually sets, persists it, and
applies external-subtitle synchronization. \`script.js\` publishes a separate
\`window.ruinPlayer.getOffsetSec\` accessor that currently returns zero.

A search of the shared frontend JavaScript files inspected found the accessor
definition but no call site in \`script.js\`, \`player-ui.js\`, or
\`components.js\`. That does not prove no caller exists elsewhere. Before
changing either file, establish the complete consumer set (including any
external integration that may use the public \`window.ruinPlayer\` object).

- If the accessor has no consumers, the zero-valued function is an inert API
  stub and should be treated as cleanup, not as a broken user-facing subtitle
  offset feature.
- If a consumer exists, determine what it expects and whether the separate
  accessor causes a real offset mismatch before proposing a fix.

No behaviour change is proposed in Phase 0.

## Notes

Issue #1 is the known wrong-association risk. Its historical incident and
current fallback must remain distinct in future reports.

Issue #5 is a configuration mismatch between the library daemon and the
location of the TMDB key; it should be addressed as a separate configuration
task, not silently worked around.

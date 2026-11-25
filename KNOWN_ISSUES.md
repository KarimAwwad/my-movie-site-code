# KNOWN_ISSUES

Severity: **S1** wrong data or data loss · **S2** broken feature ·
**S3** degraded quality · **S4** hygiene. Status: OPEN / MITIGATED / CLOSED.

| # | Sev | Area | Issue | Status |
|---|---|---|---|---|
| 1 | S1 | grab.py | `adoptable()` falls back to size tolerance (35%) when no title token set matches. Documented live incident: a 3-minute Valorant clip filed as *Insidious Chapter 3*, job closed, real film orphaned. | OPEN |
| 2 | S2 | library.py | Remux maps `0:v:0` / `0:a:0?` and `-ac 2`. Every additional audio track is discarded and all audio is downmixed to stereo. | OPEN |
| 3 | S2 | frontend | No audio track selector. Quality menu only filters audio-only renditions. | OPEN |
| 4 | S2 | frontend | `window.ruinPlayer.getOffsetSec` is a `() => 0` stub. Subtitle offset adjustment does not work. | OPEN |
| 5 | S2 | config | `library.py` cannot see `TMDB_KEY` (reads env/.env/config.json; key lives in `grab.json`). Runtime log: `no TMDB_KEY` on every start. Only tagged files match. | OPEN |
| 6 | S2 | frontend | Series playback unwired: `series-play` → `Episode playback is not available yet.` `ruin:episode` is a stub. | OPEN |
| 7 | S2 | consistency | `worker.js` exposes 5 providers; `script.js` copy and `relay.py` say 14. | OPEN |
| 8 | S3 | server.py | `SITE_DIR` hardcoded to an absolute Windows path; moving the folder breaks startup. | OPEN |
| 9 | S3 | server.py | CSP hardcodes `192.168.1.2`; any other LAN address loses playback and API access. | OPEN |
| 10 | S4 | security | TMDB key in `grab.json` and `wrangler.toml`, Supabase key in `.env`, Drive refresh tokens in `gdrive_accounts.json` — all committed. | OPEN |
| 11 | S4 | repo | `library.json` and five `*.log` files are runtime output but tracked. | OPEN |
| 12 | S4 | repo | No tests of any kind. `TEST_RESULTS.md` has no baseline. | OPEN |
| 13 | S4 | frontend | Dead/duplicate code: `bindPlayerControls()` fallback superseded by `player-ui.js`, `embedMode()`/`player-fallback` iframe path, empty `LABEL_OVERRIDES` / `BLOCKED_MOVIE_IDS`. | OPEN |

## Notes

Issue 1 is the highest-value target: it is the only known path to a *wrong*
association rather than a missing one.

Issue 5 is a one-line config fix but also a structural smell — two daemons,
two config files, one key.
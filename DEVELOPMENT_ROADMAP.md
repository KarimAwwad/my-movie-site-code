# DEVELOPMENT_ROADMAP

Ordered by risk reduction per unit of work. One phase at a time. Order may be
revised; scope within an accepted phase may not grow.

## Phase 0 — documentation baseline (ACCEPTED, in progress)

Seven docs, findings recorded, baselines declared absent. No functional change.

## Phase 1 — harden `grab.py` adoption (NEXT)

Goal: eliminate the wrong-file class of association.
- Title-token match becomes mandatory, size becomes corroboration only.
- ffprobe duration check against TMDB runtime; reject outside ±25%.
- A heuristic hit no longer closes the job — it parks the file for review.
- `/queue` surfaces parked candidates.
Exit: replay the Valorant/Insidious incident and confirm it parks instead of
filing.

## Phase 2 — audio track preservation

Goal: stop discarding audio. Remux all audio streams, keep language/codec/title
metadata, default to original language. Verify on a multi-track MKV.

## Phase 3 — audio track selection in the player

Goal: expose tracks from the manifest/API, label language and codec, switch
live, remember the choice per profile.

## Phase 4 — subtitle offset

Goal: real `getOffsetSec`, ±10 s nudge, persisted per film.

## Phase 5 — configuration decoupling

Goal: one shared config for the TMDB key; `SITE_DIR` and CSP hosts from config
or detection.

## Phase 6 — series playback

Goal: wire `ruin:episode` to season/episode resolution and playback.

## Phase 7 — provider parity

Goal: reconcile the 5 vs 14 discrepancy; decide whether the Worker stays.

## Phase 8 — test catalogue and measurement

Goal: define the eligible catalogue, measure playback success and association
accuracy against the 95% / zero targets.

## Deferred

Quality upgrades without destroying existing files, corrupted-file detection,
duplicate prevention, repo hygiene (issue 11/13).
# DEVELOPMENT_ROADMAP

Ordered by risk reduction per unit of work. One phase at a time. Order may be
revised; scope within an accepted phase may not grow.

## Phase 0 — documentation baseline (AWAITING OPERATOR REVIEW)

Seven core documents plus \`PATCH_NOTES.md\` are present at repository root.
Findings and baselines are recorded. No application source file changed.

## Phase 1 — harden local-file adoption (NEXT)

Goal: reduce the risk of associating a discovered local video file with the
wrong pending library item.
- Require meaningful title evidence before automatic association; file size is
  corroboration, not identity.
- Use media duration and other independent metadata as additional checks.
- Ambiguous candidates must remain pending for review rather than being
  automatically finalized.
- Keep the existing library item intact when a candidate is uncertain.
Exit: the known historical failure case is represented in a test, and current
candidate handling is verified without claiming that the old incident has
been reproduced by the current code.

## Phase 2 — resolve the \`getOffsetSec\` API question

Goal: establish all consumers of the shared accessor, then decide whether the
zero-valued stub is inert or causes a real integration mismatch. Do not change
the player UI's working offset controls before the consumer set is known.

## Phase 3 — audio track preservation

Goal: preserve available audio streams through the local media playback path,
including language/codec/title metadata where present. Verify using a
multi-audio test file that the operator is authorized to use.

## Phase 4 — audio track selection in the player

Goal: expose available tracks in the player, label language and codec, support
selection where the playback format permits it, and test browser compatibility.

## Phase 5 — subtitle verification and synchronization

Goal: verify external subtitle matching, timing transformations, persistence,
manual offset controls, and automatic synchronization using authorized test
media.

## Phase 6 — configuration decoupling

Goal: establish one clear configuration source for shared settings; make
\`SITE_DIR\` and CSP host configuration portable and explicit.

## Phase 7 — series-library foundations

Goal: define series, season, and episode metadata and library organization.
Playback wiring is a separate milestone and depends on available storage and
test media.

## Phase 8 — test catalogue and measurement

Goal: define an eligible test catalogue and measure local metadata association,
playback, audio-track selection, subtitle behavior, and recovery against
explicit pass/fail criteria.

## Deferred

Quality upgrades without losing an existing working file, corrupted-file
detection, duplicate prevention, repository hygiene (runtime logs/manifests),
and cleanup of unverified dead-code candidates.

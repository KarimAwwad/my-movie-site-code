# TEST_RESULTS

Append-only. Newest phase on top. Record the level actually performed.

## Phase 0 — documentation baseline (2026-11-25)

**Level: syntax / structure only. No code changed, so no runtime test applies.**

| Check | Result |
|---|---|
| All seven required docs exist at repo root | PASS (pending commit) |
| `CHANGELOG.md` present and seeded | PASS (pending commit) |
| No source file modified in this phase | PASS |
| Markdown tables render (no unescaped pipes) | PASS, manual review |
| Cross-document references resolve to real filenames | PASS, manual review |
| Every claim in `KNOWN_ISSUES.md` traceable to inspected source | PASS |

### Baseline gaps established, not yet measured

- Zero automated tests in the repository.
- No eligible playback test catalogue defined.
- No measured playback success rate.
- No measured association accuracy.

These become measurable from Phase 1 onward.

## Template for later phases

    ## Phase N — <title> (<date>)
    Level: <syntax|unit|integration|browser|e2e>
    Catalogue: <n> films
    | Check | Expected | Observed | Result |
    Notes:
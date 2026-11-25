# TEST_RESULTS

Append-only. Newest phase on top. Record the level actually performed.

## Phase 0 — documentation baseline (2026-11-25)

**Level: syntax / structure only. No application code changed, so no runtime
test applies.**

| Check | Result |
|---|---|
| Seven core documents and `PATCH_NOTES.md` exist at repository root | PASS — verified on `main` |
| `CHANGELOG.md` is present and seeded | PASS — verified on `main` |
| No application source file modified in Phase 0 | PASS — documentation-only change |
| Markdown tables and code spans render | PASS — manual review |
| Cross-document references resolve to repository files | PASS — manual review |
| Claims in `KNOWN_ISSUES.md` are tied to inspected source or explicitly marked unverified | PASS |

### Revision log

- **r1** — initial documentation draft.
- **r2** — operator review corrections: subtitle offset issue rewritten around
  the split between the player UI state and the shared accessor; historical
  adoption incident separated from the current fallback; dead-code findings
  reclassified as candidates; PowerShell checks added; pre-Phase-0 and current
  documented states separated.

### Baseline, before Phase 0

- No automated tests found in the repository.
- No eligible playback test catalogue defined.
- No measured playback success rate.
- No measured association accuracy.

These remain unmeasured; documentation does not change them.

## Template for later phases

    ## Phase N — <title> (<date>)
    Level: <syntax|unit|integration|browser|e2e>
    Catalogue: <n> test items
    | Check | Expected | Observed | Result |
    Notes:

# DEVELOPMENT_RULES

## The core loop

ONE PHASE → ONE GOAL → IMPLEMENTATION → TESTING → VERIFICATION → DOCUMENTATION.

A phase is not done until it is verified. Documentation is updated in the same
phase as the code, not after.

## Before touching code

1. Inspect the existing implementation.
2. Understand dependencies and callers.
3. Identify the actual problem, not a symptom.
4. State the proposed solution.
5. State the side effects.
6. Implement.
7. Test.

## Hard rules

- Never rewrite a working component because another approach looks cleaner.
- Never remove functionality without approval.
- Never assume something is broken without investigating it first.
- Never claim something works because the code reads correctly.
- Only one phase is in flight at a time. Phase 0 is the only exception to
  "docs land with code" — it *is* docs.

## Delivery format

- Complete replacement files. No "replace lines 40-58" instructions.
- Existing folder structure preserved.
- Only changed files included.
- Changes packaged per project folder, with `PATCH_NOTES.md`.
- `PATCH_NOTES.md` carries testing steps and rollback steps.
- No file overwritten or deleted without approval.

## Testing vocabulary — keep these distinct

| Level | Means |
|---|---|
| Syntax validation | parses / compiles |
| Unit test | one function, isolated |
| Integration test | daemons talking to each other |
| Browser playback | a real video plays, seeks, switches |
| End-to-end | full path from card click to credits |

State which level was actually performed. Never promote a lower level to a
higher one in prose.

## Targets (measure, do not claim)

- Zero incorrect movie associations.
- ≥ 95% successful playback across a defined eligible test catalogue.

## Documentation duty

Every phase updates `CHANGELOG.md`, `TEST_RESULTS.md`, `KNOWN_ISSUES.md`, and
`DEVELOPMENT_ROADMAP.md` as applicable. New sessions begin by reading
`PROJECT_CONTEXT.md` and `KNOWN_ISSUES.md`.
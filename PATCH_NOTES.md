# PATCH_NOTES — Phase 0

## Scope

Documentation only. Zero source files touched. Zero runtime behaviour change.

## Files added (all repository root)

| File | Purpose |
|---|---|
| `PROJECT_CONTEXT.md` | state, ports, config locations, ownership |
| `ARCHITECTURE.md` | topology, data flow, security posture |
| `DEVELOPMENT_RULES.md` | the phase loop and delivery rules |
| `KNOWN_ISSUES.md` | 13 recorded issues, severity-ranked |
| `TEST_RESULTS.md` | baseline + result template |
| `CHANGELOG.md` | seeded history |
| `DEVELOPMENT_ROADMAP.md` | ordered phases |
| `PATCH_NOTES.md` | this file |

## Files changed

None.

## Files deleted

None.

## Packaging

From the repository root:

    cd "path/to/my-movie-site-code"
    powershell Compress-Archive -Path PROJECT_CONTEXT.md,ARCHITECTURE.md,DEVELOPMENT_RULES.md,KNOWN_ISSUES.md,TEST_RESULTS.md,CHANGELOG.md,DEVELOPMENT_ROADMAP.md,PATCH_NOTES.md -DestinationPath phase0-docs.zip

Docs sit at the root, so no folder nesting is needed this phase.

## Testing

1. `ls` the root — eight files present, no `*.md` beyond `README.md` and these.
2. Open each in a renderer — tables draw, no literal `|` escaping errors.
3. `grep -rn "TODO" *.md` — only intentional ones.
4. Confirm `git status` shows additions only:

       git status --porcelain | grep -v '^??'   # expect empty
       git status --porcelain | grep '^??'      # expect the eight files

5. Spot-check three claims against source, e.g. `grep -n "0:a:0" "ruintv server/library.py"`
   and `grep -n "getOffsetSec" "movie site/script.js"`.

## Verification gate

Phase 0 is accepted when all five checks pass and the operator confirms the
issue list is accurate and the roadmap order is acceptable.

## Rollback

Docs only, nothing depends on them:

    git rm PROJECT_CONTEXT.md ARCHITECTURE.md DEVELOPMENT_RULES.md KNOWN_ISSUES.md TEST_RESULTS.md CHANGELOG.md DEVELOPMENT_ROADMAP.md PATCH_NOTES.md
    git commit -m "revert phase 0 docs"

Or discard before committing:

    rm PROJECT_CONTEXT.md ARCHITECTURE.md DEVELOPMENT_RULES.md KNOWN_ISSUES.md TEST_RESULTS.md CHANGELOG.md DEVELOPMENT_ROADMAP.md PATCH_NOTES.md

## Known limitations of this phase

- `player-ui.js`, `components.js`, `style.css`, `relay.py` internals, and the
  HLS path in `library.py` were not read line by line. Claims about them are
  marked as such or held back.
- `watch.html` and `index.html` were retrieved base64-encoded only; both are
  thin shells and nothing in the docs depends on their markup.
- No issue has been reproduced. All 13 are read from source, and issue 1 also
  from a recorded incident in `grab.py`'s own docstring.
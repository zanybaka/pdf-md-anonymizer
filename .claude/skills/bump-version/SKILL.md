---
name: bump-version
description: Bump project version in all canonical version locations of pdf-md-anonymizer. Use when the user asks to set/raise/change the version, "поставь версию X.Y.Z", "bump version", or "версию подними".
---

# Bump project version

Update the project version in every canonical location at once. The version
must stay in sync across `pyproject.toml` and the package `__version__`,
otherwise Briefcase bundles, `importlib.metadata`, and the UI title (UI-019)
disagree.

## Canonical locations

Three places, all required:

1. `pyproject.toml` — `[project] version = "X.Y.Z"` (line ~7).
2. `pyproject.toml` — `[tool.briefcase] version = "X.Y.Z"` (line ~197).
3. `src/anonymizer/__init__.py` — `__version__ = "X.Y.Z"`.

There is no `[tool.briefcase.app.*] version` override — Briefcase inherits
from `[tool.briefcase]`, so do not add one.

## Do NOT touch

- `DEPLOYMENT.md`, `CHANGELOG.md`, `BACKLOG.md` — `0.1.0` etc. appearing
  there are historical examples / past entries, not the current version.
- `build/`, `dist/` — generated artifacts.
- Test fixtures.

## Steps

1. Confirm the target version (`X.Y.Z`, semver). If the user just said
   "подними" without a number, propose the next patch bump from the
   current `[project] version` and ask.
2. Read the three files above to capture the current version string.
3. Edit all three locations to the new version.
4. Sanity-check with:
   ```
   grep -nE '^version\s*=|__version__' pyproject.toml src/anonymizer/__init__.py
   ```
   All three lines must show the new version.
5. Report changed file:line locations. Do **not** commit, tag, or push —
   that is the user's call (`commit-current-changes` skill handles
   commits separately).

## Constraints

- Never bump version as part of an unrelated change — version bumps are
  their own commit.
- Do not edit `uv.lock` by hand; if it drifts, run `uv lock` separately.
- Do not create a git tag (`v0.1.1` etc.) unless explicitly asked.

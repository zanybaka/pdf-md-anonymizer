# Development

How to run, debug, and package `pdf-md-anonymizer` from source.

The project is src-layout (`src/anonymizer`, `src/anonymizer_ui`) and requires
Python 3.11+. `pytest` is configured with `pythonpath = ["src"]`, so tests run
without installing anything.

## Setup

Create the venv outside the repo, then install editable from the repo root:

```bash
python -m venv ~/.venvs/pdf-md-anonymizer
~/.venvs/pdf-md-anonymizer/bin/pip install -e ".[dev,ui,pdf]"
source ~/.venvs/pdf-md-anonymizer/bin/activate
```

`[dev,ui,pdf]` pulls `pytest`, `toga`, and the `pdf2md` converter; drop any of
them for a leaner setup (`pdf` pulls heavier docling/ML dependencies). The
install is editable — source edits apply live. The `pdf2md` from `[pdf]` lands
in this venv, and `convert.py` prefers that env-local executable over any
system-wide `pdf2md`.

- IDE: point the interpreter at `~/.venvs/pdf-md-anonymizer/bin/python`.

## Run

After:

```bash
anon doc.md -o out.md --map out.map.json     # CLI
anon restore out.md --map out.map.json
python -m anonymizer_ui                       # desktop UI from source
python -m pytest -q                           # tests
```

## Quick reference

| Need | Command |
|---|---|
| `anon` CLI, live edits | venv outside the repo + `pip install -e .` |
| One-off CLI run | `PYTHONPATH=src python -m anonymizer.cli …` |
| UI from source | `uvx briefcase dev` or `python -m anonymizer_ui` |
| Tests | `python -m pytest` |

## Packaging the desktop app

Wrappers around `uvx briefcase` live in `scripts/`. They handle the
quirks (numpy `.so` codesign race, build/dist symlinks out of iCloud, DMG
contents) so the day-to-day flow stays short:

```bash
bash scripts/build_app.sh   # briefcase create (once) + briefcase build
bash scripts/build_dmg.sh   # build_app.sh + ad-hoc sign + hdiutil → dist/*.dmg
bash scripts/run_app.sh     # open the built .app (builds it if missing)
```

The `[pdf]` extra is **not** bundled in the `.app` (ADR-0008); pdf2md installs
itself into the bundle on first PDF use. The `docopt` wheel needed at bundle
build time is referenced directly from `vendor/` via `pyproject.toml`, so no
`PIP_FIND_LINKS` is required.

Release procedure (tag → CI builds DMG → GitHub Release) is documented in
[DEPLOYMENT.md](DEPLOYMENT.md). Equivalent VS Code tasks are in
`.vscode/tasks.json`.

## Code quality maintenance

Periodic audits via Claude Code slash commands (skills from
`l-mb/python-refactoring-skills`). Order matters:
`py-quality-setup → py-security → py-code-health → py-test-quality → py-git-hooks`.

| Skill | Purpose | When to run |
|---|---|---|
| `/py-security` | bandit audit for OWASP-class vulnerabilities | Each sprint or before a release. `ruff` covers most checks on every commit; bandit catches the rest. |
| `/py-code-health` | `vulture` for dead code, `pylint --enable=duplicate-code` for duplicates | Wired into pre-commit (vulture). Pylint duplicate-code by hand when refactoring. |
| `/py-test-quality` | Real coverage (`pytest-cov`) + mutation testing (`mutmut`) | Coverage: each push (CI). mutmut: quarterly on hot modules (`src/anonymizer/detect/`, `mapping.py`). |
| `/py-complexity` | Cyclomatic/cognitive complexity — primary target is the NER pipeline in `src/anonymizer/detect/ner.py` | When NER pipeline gains a new stage or a file crosses ~500 LOC. |

bandit, coverage, and mutmut are deliberately **not** in pre-commit — they are
either redundant with existing ruff rules (bandit) or too slow for a per-commit
hook (coverage, mutmut). Run via the skill or in CI.

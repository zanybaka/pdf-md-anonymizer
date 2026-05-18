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

`briefcase` is invoked via `uvx` — no install needed. `wheelhouse/` already
ships the `docopt` wheel (sdist-only; Briefcase installs bundle deps with
`--only-binary`).

```bash
# Step 1 (one-time): scaffold the .app bundle and install its dependencies
PIP_FIND_LINKS="$PWD/wheelhouse" uvx briefcase create macOS

# Step 2: compile pdf-md-anonymizer.app  (default build task: Cmd+Shift+B)
PIP_FIND_LINKS="$PWD/wheelhouse" uvx briefcase build macOS

# Step 3 (optional): produce a distributable .dmg
# Strip numpy .so signatures first — avoids a codesign race on .cstemp files:
find ~/.briefcase-out/pdf-md-anonymizer/build -name '*.so' -path '*/numpy/*' \
  -exec codesign --remove-signature {} \; 2>/dev/null; true
PIP_FIND_LINKS="$PWD/wheelhouse" uvx briefcase package macOS

# Launch the bundled app (auto-runs steps 1-2 if the bundle is missing)
uvx briefcase run macOS
```

All four steps are also available as VS Code tasks (`.vscode/tasks.json`).

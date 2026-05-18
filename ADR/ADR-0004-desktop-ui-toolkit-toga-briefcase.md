# ADR-0004: Desktop UI toolkit — Toga + Briefcase

- Status: Accepted
- Date: 2026-05-18
- Realized by: UI-001

## Context
The project needs a native macOS desktop UI that lets a user pick `.pdf`/`.md`
files, run anonymization, and view/save results. The UI must call the
`anonymizer` core in-process so the Natasha model loads once, with no daemon or
IPC bridge. The BACKLOG recorded this as an `ADR-CANDIDATE`; UI-001 realizes it.

## Decision
Build the desktop UI with **Toga** and package it with **Briefcase**. The UI
lives in a separate `anonymizer_ui` package that imports `anonymizer` directly
and drives `anonymizer.batch.process_files`. Toga/Briefcase are kept out of the
core runtime dependencies (core stays the `natasha`-only `anon` CLI); UI deps
live in the `ui` optional-dependency group and Briefcase's `requires`.

## Alternatives considered

| Option | In-process core | Native look | Packaging | Verdict |
|---|---|---|---|---|
| Toga + Briefcase | yes (direct import) | native widgets | `.app`/`.dmg` built-in | **chosen** |
| NiceGUI / pywebview | yes | web-rendered | py2app/PyInstaller | rejected — non-native |
| Streamlit / Gradio | yes | browser tab | n/a | rejected — not app-like |
| PySide6 / PyQt | yes | near-native | py2app/PyInstaller | rejected — heavier |
| Swift | no — needs IPC bridge | fully native | `.app` | rejected — IPC bridge |

## Consequences
- Native macOS widgets and a built-in path to a distributable `.app`/`.dmg`.
- The core can be installed and used without Toga.
- The UI process loads the Natasha model once and runs batches off the UI
  thread, reporting per-file progress through the core's batch iterator.

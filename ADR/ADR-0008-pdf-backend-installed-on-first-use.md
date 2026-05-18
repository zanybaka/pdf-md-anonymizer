# ADR-0008: The desktop `.app` installs the PDF backend on first use, not at build time

- Status: Accepted
- Date: 2026-05-18
- Realized by: UI-002
- Revises: ADR-0005

## Context
ADR-0005 mirrored the docling-backed `pdf-to-markdown` git dependency into
`[tool.briefcase.app.…].requires` so the desktop `.app` would ship `pdf2md`
inside the bundle. In practice `briefcase create` fails: Briefcase installs
bundle dependencies cross-target with `pip --only-binary :all: --platform
macosx_11_0_arm64` for the bundled Python 3.12. The docling stack's native
dependencies — `docling-parse`, `deepsearch-glm` — publish no wheels matching
that target, so resolution is impossible. Even if it resolved, bundling
docling + torch + ML models would make the distributable `.app` very large.

A normal `uv tool install "pdf-md-anonymizer[pdf]"` succeeds because it
installs on the *real* machine: it targets the actual macOS version and
running Python, and can use current wheels or build from source. Briefcase's
build-time bundle install cannot.

## Decision
The desktop `.app` does **not** bundle `pdf2md`. It ships lean — the UI, the
`anonymizer` core, and `natasha` only.

The docling-backed `[pdf]` backend is installed **on first use**: when the user
opens a PDF in the app and no usable `pdf2md` is found, the app installs
`pdf-to-markdown` (same git reference as `[project.optional-dependencies].pdf`)
into a user-writable support directory, using the `.app`'s bundled Python, then
converts via it. Because that install runs at runtime on the real macOS, it
gets wheels matching the actual OS — sidestepping Briefcase's build-time
constraint. The install is one-time; later launches reuse it.

This **relaxes the "fully offline at runtime" invariant** for the PDF feature:
the `.app` needs network once, for the first-use PDF-backend install. Core
anonymization, Markdown input, and `restore` stay fully offline, and document
content is never sent anywhere. The relaxation is scoped — it is a one-time
setup-equivalent step (a `.app` has no separate install step; first launch is
its setup), not a per-document network call.

ADR-0005's `[project.optional-dependencies].pdf` for the CLI, dev venv, and
`uv tool install` is **unchanged** — that path still installs `pdf2md` at
setup time as before. Only the Briefcase-bundling half of ADR-0005 is revised.
The ADR-0002 subprocess boundary is unchanged: `pdf2md` is still only invoked
as a CLI, never imported.

## Alternatives considered
- **Bundle docling in the `.app` (ADR-0005 as-is)** — rejected: `briefcase
  create` fails (no wheels for the macОS-11.0 / cp312 / `--only-binary`
  target), and docling + torch would bloat the distributable.
- **Bundle the lighter `main`-branch backend at build time** — deferred: it
  would keep strict offline, but the lighter backend's conversion quality is
  unverified and choosing it is a separate decision; can be revisited if the
  first-use install proves unsatisfactory.
- **Ship the `.app` with no PDF support (Markdown only)** — rejected: PDF input
  is a primary use case.

## Consequences
- The distributable `.app` is small, and `briefcase build` succeeds.
- PDF input in the `.app` needs a one-time, network-dependent install on first
  use; afterwards it works offline.
- The "fully offline at runtime" invariant becomes "fully offline after the
  one-time PDF-backend setup" for the desktop app. Document content is never
  transmitted.
- First-use install logic is new code (UI-002): install location, install
  mechanism with the bundled Python, `pdf2md` resolution, and UI progress /
  offline-failure messaging.

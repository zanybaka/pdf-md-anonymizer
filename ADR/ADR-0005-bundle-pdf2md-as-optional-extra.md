# ADR-0005: Bundle `pdf2md` as an opt-in `[pdf]` extra

- Status: Accepted
- Date: 2026-05-18
- Realized by: PDF-002
- Revises: ADR-0002
- Revised by: ADR-0008 — the `.app`-bundling decision below is superseded; the
  `[pdf]` extra for the CLI / dev venv still stands.

## Context
ADR-0002 kept `pdf2md` fully external: PDF input required a separate manual
install of `pdf2md` on `PATH`. That is poor out-of-box UX, and a system-wide
`pdf2md` is shared mutable state the tool cannot control. The `pdf2md` docling
backend, however, pulls heavy ML dependencies (torch + models), so it cannot
become an unconditional core dependency.

## Decision
Ship `pdf2md` as an **opt-in** dependency installed into the anonymizer's own
isolated environment — never the system.

- `[project.optional-dependencies].pdf` declares
  `pdf-to-markdown @ git+…/pdf-to-markdown@backend/docling`. The distribution is
  named `pdf-to-markdown`; `pdf2md` is the CLI command it installs, and a direct
  reference must use the distribution name. The `backend/docling` branch is the
  docling-backed build; the repo's `main` branch carries a different, lighter
  backend. This covers the dev venv (`pip install -e ".[pdf]"`) and the
  `uv tool` env (`uv tool install "…[pdf]"`).
- `[tool.briefcase.app.pdf-md-anonymizer].requires` mirrors the same entry, because
  Briefcase does not read PEP 621 `optional-dependencies`. This ships the
  converter inside the `.app` bundle.
- The direct git reference is permanent: the project is installed only from git
  and bundled into the `.app`, never published to PyPI, so PyPI's ban on
  direct-URL dependencies does not apply. `[tool.hatch.metadata]
  allow-direct-references = true` is set so the hatchling build backend accepts
  the git reference.
- `convert.py` resolves the default `pdf2md` to the executable next to the
  running interpreter (`sys.prefix/bin/pdf2md`) before falling back to `PATH`,
  so an env-local build is always preferred over a system one. `--pdf2md-cmd`
  still overrides this explicitly.

The ADR-0002 subprocess boundary is unchanged: `pdf2md` is still only invoked
as a CLI, never imported as a package. Installation is a setup-time step, never
done at runtime, preserving the "fully offline at runtime" invariant.

## Alternatives considered
- **Keep `pdf2md` fully external (ADR-0002 as-is)** — rejected: poor out-of-box
  UX, requires a separate manual install.
- **Install `pdf2md` system-wide with a replace prompt** — rejected: fragile,
  OS/packager-specific, and mutates shared state outside the tool's control.
- **Make `pdf2md` an unconditional core dependency** — rejected: the docling
  backend's torch + ML models would bloat every core/CLI install.

## Consequences
- With `[pdf]` installed, PDF conversion works out of the box; the desktop
  `.app` converts PDFs with no separate install.
- The core install without `[pdf]` stays light — no docling/ML dependencies.
- PDF-001 behavior is preserved: without `[pdf]`, PDF input still works when a
  `pdf2md` is on `PATH`.
- The dependency is declared in two places that must be kept in sync.

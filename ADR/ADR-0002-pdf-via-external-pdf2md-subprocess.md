# ADR-0002: PDF support via the external `pdf2md` subprocess

- Status: Accepted — revised by ADR-0005
- Date: 2026-05-18
- Realized by: PDF-001

## Context
The tool accepts `.pdf` input but must convert it to Markdown before detection.
The PRD recorded an `ADR-CANDIDATE` to reuse the existing `pdf-to-markdown`
project rather than coupling to a PDF backend in code. PDF-001 realizes it.

## Decision
`convert.py` shells out to the external `pdf2md` CLI (`pdf2md <file>`, stdout
captured as Markdown). The executable name is overridable via `--pdf2md-cmd`
(default `pdf2md` on `PATH`). A missing executable or non-zero exit raises a
clear `ConversionError` naming the command. The `pdf-to-markdown` package is
**not** imported.

## Alternatives considered
- **Import `pdf-to-markdown` as a package** — rejected: couples the tool to one
  backend branch and pulls in heavy backend dependencies.

## Consequences
- PDF input requires `pdf2md` installed separately on `PATH`.
  **Revised by ADR-0005:** the opt-in `[pdf]` extra now bundles `pdf2md` into
  the tool's own environment, so a separate manual install is no longer needed.
  The subprocess boundary below still holds.
- The conversion backend can be swapped without changing this project.
- Conversion output quality depends on the installed `pdf2md` backend.

# ADR-0010: `pdf2md` batch driver — one subprocess per PDF group

- Status: Accepted
- Date: 2026-05-23
- Realized by: PDF-004
- Revises: none (extends ADR-0002 / ADR-0005)

## Context
PDF-001 / ADR-0002 reach the external `pdf2md` CLI by spawning one
subprocess per file. The docling backend (`pdf-to-markdown @ backend/docling`)
loads the Docling models and torch at process startup; on a 3-file batch the
model-init cost dominates wall-clock time. The `pdf-to-markdown` package now
exposes a `create_docling_converter()` / `convert_with_converter(path, conv)`
pair that can reuse one `DocumentConverter` across many PDFs (upstream commit
`0311a6d` on `backend/docling`), but its installed `pdf2md` CLI still accepts
only a single file per invocation.

## Decision
`src/anonymizer/convert.py` gains `pdf_batch_to_markdown(paths, command, …)`
that spawns **one** subprocess for the whole batch by:

1. Resolving the `pdf2md` Python interpreter from the script's shebang
   (a no-op if the resolved command is not a Python script — see fallback).
2. Running that interpreter with a tiny `-c` driver string that imports
   `pdf_to_markdown.cli.create_docling_converter` /
   `convert_with_converter` and reuses the resulting converter across every
   PDF passed on `argv`.
3. Streaming **one JSON manifest line per file** on stdout as each PDF
   finishes (`{"index", "path", "status", "output"|"error"}`); per-file
   Markdown is written to caller-provided `tempfile.TemporaryDirectory`,
   not stdout, so big documents do not bloat the pipe and the parent reads
   results incrementally — required for cancellation and per-file failure
   handling.

`src/anonymizer/` contains no `import pdf_to_markdown`; the import lives
inside the driver string and runs only in the child process. The
`batch.process_files` loop groups consecutive `.pdf` inputs and calls
`pdf_batch_to_markdown` once per group; a `.md` input or end-of-list flushes
the current group.

## Alternatives considered
- **Add multi-file argv support to the upstream `pdf2md` CLI** — better
  long-term, but is a separate-repo change and would not deliver in this
  task. The driver approach is forward-compatible: when upstream ships a
  proper batch CLI, the driver can be replaced with a direct CLI call.
- **In-process import of `pdf_to_markdown`** — rejected: violates the
  ADR-0002 subprocess boundary and pulls Docling + torch (≈ 1 GB) into the
  parent process unconditionally.
- **One stdout-delimited manifest with inline Markdown** — rejected: a
  multi-MB document chokes the pipe and forces the parent to buffer until
  the next delimiter, defeating the per-file streaming goal.

## Consequences
- The Docling model loads once per PDF group instead of once per file.
  A 3-file batch run completes in roughly `init + N × per_file_convert`
  wall-clock instead of `N × (init + per_file_convert)`.
- A per-file conversion failure is reported via `on_file(path, exception)`
  and does not abort the rest (CLI-001 invariant preserved).
- On `cancel()` returning True between files, the parent kills the
  subprocess; already-delivered outputs are kept on disk.
- ADR-0002's subprocess boundary is preserved (verified by
  `tests/test_convert_batch.py::test_no_pdf_to_markdown_import_in_anonymizer_source`).
- A `pdf2md` build whose script lacks a Python shebang (or an older build
  without `create_docling_converter`) falls back to the per-file path —
  callers always make progress, just without the batch speed-up.
- The single-file API `pdf_to_markdown(path, …)` keeps its public
  signature and PDF-001 / PDF-003 behaviour.

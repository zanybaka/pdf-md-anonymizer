# TECHSPEC — pdf-md-anonymizer

## Overview
A Python package `anonymizer` exposing a core library function and an `anon`
CLI. PDF input is converted to Markdown by shelling out to the external
`pdf2md` tool; everything else operates on text strings.

## Pipeline
```
.pdf  → convert.py (subprocess pdf2md) → text ┐
                                              ├→ detect → replace → (text, map)
.md / stdin ─────────────────────────────────┘
```

## Package layout
```
src/anonymizer/
  api.py          # anonymize(text, options) -> AnonResult ; core entrypoint
  detect/
    __init__.py   # run regex rules, then NER on remaining spans; dedupe
    regex_rules.py
    ner.py        # Natasha: PER, optional ORG / LOC
    llm.py        # optional local Ollama pass (later phase)
  replace.py      # assign {{CATEGORY_N}} tokens, build map
  mapping.py      # serialize / load map; restore(text, map) -> text
  convert.py      # subprocess wrapper over external pdf2md
  cli.py          # `anon` entrypoint (argparse)
tests/
```

## Core contract
- `anonymize(text: str, options: Options) -> AnonResult`
  - `AnonResult.text: str` — anonymized Markdown
  - `AnonResult.mapping: dict[str, str]` — token -> original value
- `restore(text: str, mapping: dict[str, str]) -> str`
- Detection produces spans `(start, end, category, value)`; replacement is
  applied right-to-left so offsets stay valid.

## Detection
- Categories: EMAIL, PHONE, INN, SNILS, OGRN, OGRNIP, KPP, BIK, ACCOUNT, CARD,
  DOB, POSTAL_CODE, ADDRESS, PASSPORT, IP, URL, SECRET, ORG, PERSON, LOC.
- Legal forms covered (abbreviated and full spelling): ООО, АО, ПАО, ЗАО, ОАО,
  ИП, НПО, НКО, ИЧП, ТОО, ОП.
- Order: regex/dictionary rules first (high precision), then Natasha NER over
  spans not already claimed. Overlapping matches: the earlier (regex) wins.
- NER detects PERSON, ORG, and LOC; all three are tokenized by default for
  maximum private-data removal. `--no-ner-org` / `--no-ner-loc` opt out.
- CARD additionally validated with the Luhn checksum to cut false positives.
- A brand short-name propagation pass narrows each legal-form ORG span
  (`ООО «Альфа-Бета»`, `ООО АСТРАЛ-СОФТ`) to its inner company name and adds
  every word-bounded bare repeat of that short-name as an ORG span sharing
  the same token; `--no-brand-propagation` disables it. Stoplisted inner
  names (country names, generic nouns) are not propagated.
- A consistency sweep then propagates every detected value to its other
  word-bounded occurrences, closing NER recall gaps; `--no-consistency-sweep`
  disables it.
- Legal entities matched by form keyword (`ООО`, `АО`, `ПАО`, `ИП`) plus the
  quoted name.

## Replacement
- Token: `{{CATEGORY_N}}`, `N` is a per-category 1-based counter.
- A normalized source value maps to one token; repeats reuse it.
- Map written as JSON, UTF-8, sorted keys.

## CLI
```
anon INPUT... [-o OUT] [--map MAP] [--no-ner-org] [--no-ner-loc]
              [--no-consistency-sweep] [--no-brand-propagation]
              [--llm] [--pdf2md-cmd CMD]
anon restore INPUT --map MAP [-o OUT]
```
- INPUT extension `.pdf` triggers conversion; otherwise treated as Markdown.
  Reads stdin when INPUT is `-`.
- INPUT accepts one or many files: an explicit list (`a.pdf b.md`) and/or glob
  wildcards (`docs/*.pdf`). Patterns are expanded internally too, so quoted
  patterns work even when the shell does not expand them.
- Single input: `-o`/`--map` are file paths. If omitted, output goes to
  `<stem>.anon.md` and `<stem>.anon.map.json` next to the input file; for stdin
  input (`-`) the result is written to stdout.
- Multiple inputs: `-o`/`--map` must be directories (or omitted); each input
  produces `<filename>.anon.md` and `<filename>.map.json` there, keeping the
  original extension in the name (`report.pdf` → `report.pdf.anon.md`) so
  same-stem inputs do not collide. A per-file failure is reported but does not
  abort the remaining files; error/progress output carries file paths and
  category names only, never document content.
- `--pdf2md-cmd` overrides the `pdf2md` executable (default: `pdf2md` on PATH),
  allowing different backends installed under different names.

## pdf2md integration
- `convert.py` runs `pdf2md <file>` (or configured command), captures stdout.
- Non-zero exit or missing executable raises a clear error naming the command.
- No import of the `pdf-to-markdown` package.

## Dependencies
- Runtime: `natasha` (offline NER). No deps for phase 0–2.
- Optional: local Ollama via HTTP to `127.0.0.1` (later phase).
- Dev: `pytest`.

## Constraints / NFR
- Fully offline; no network at runtime (Ollama loopback only, opt-in).
- Input text and maps never written to logs or temp files.
- Python 3.11+, MIT license.

## Risks
- Natasha NER recall on ФИО is imperfect — short forms / unusual names may slip;
  optional Ollama pass mitigates.
- `pdf2md` output quality depends on the installed backend branch.
- Token collisions if source text already contains `{{...}}` — detector must
  escape or detect pre-existing braces.

ADR-CANDIDATE: detection ordering — regex before NER, earlier match wins.
Rationale: structured identifiers are unambiguous; NER should not relabel them.

ADR-CANDIDATE: hosted / Docker deployment is a future goal. The core
(`anonymizer`) stays transport-agnostic — a pure library with thin entrypoints.
A server deployment adds, as separate layers without changing the core:
- a `serve` HTTP entrypoint over the same `anonymize()` / `restore()` functions;
- a separate web frontend (the Toga desktop app does not run in a browser — a
  hosted UI is a new component, e.g. NiceGUI / SPA, that calls the API);
- a backend container bundling `pdf2md` and, for the docling backend, the
  docling ML models baked in at image-build time (no runtime download).
Constraints to resolve before any networked mode:
- The current "fully offline, no network at runtime" invariant holds only for
  local CLI/desktop use. A networked `serve` changes the trust boundary and
  requires a deliberate security model — authentication, TLS, and an explicit
  decision on where the PII-bearing replacement map lives (returned in the
  response vs. never persisted server-side).
- Concurrency: the core is CPU-bound; a server runs a worker pool, each worker
  holding its own Natasha model copy — size RAM accordingly.
Rationale: keeping the core transport-agnostic now keeps this path open without
committing to it. Alternative (rejected): bake an HTTP server into the core —
couples the library to one transport.

ADR-CANDIDATE: bundle `pdf2md` (docling backend) as an opt-in `[pdf]` extra
installed into the anonymizer's own environment — the dev venv, the `uv tool`
venv, or the Briefcase `.app` — never the system. Realized by `PDF-002`; this
revises ADR-0002. Rationale: PDF conversion works out of the box without a
separate manual install, and an isolated install removes any need to detect or
replace a system-wide `pdf2md`. The subprocess boundary from ADR-0002 stays —
still no `import` of the package, only its CLI is called — the binary just now
ships with the tool. Constraints: the docling backend pulls heavy ML
dependencies (torch + models), so `[pdf]` stays opt-in to keep the core light;
installation is a setup-time step, never done at runtime, preserving the
`fully offline at runtime` invariant. Alternatives: keep `pdf2md` fully external
(rejected — poor out-of-box UX); install to the system with a replace prompt
(rejected — fragile, OS/packager-specific, mutates shared state).

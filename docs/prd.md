# PRD — pdf-md-anonymizer

## Problem
PDF/Markdown documents contain private data — PII, full names, legal entity
names, keys, secrets. Before such documents can be shared, analyzed, or fed to
external tools, that data must be removed. Doing this by hand is slow and
error-prone.

## Goal
A tool that takes a PDF or Markdown file and produces anonymized Markdown:
sensitive values are replaced with stable tokens, and a separate map file lets
the original values be restored.

## Users
Single primary user (developer/analyst) processing documents locally. May later
be used through a desktop UI.

## Scope (in)
- Accept `.pdf`, `.md`, or text on stdin.
- For `.pdf`: convert via the existing external `pdf2md` CLI (subprocess).
- Detected categories follow the personal-data types named in Russian Federal
  Law 152-ФЗ «О персональных данных».
- Detect, in the resulting text:
  - Regex/dictionary: email, RU phone, ИНН, СНИЛС, ОГРН, ОГРНИП, КПП, БИК,
    bank account, bank card (Luhn), date of birth, postal code, address,
    passport (серия+номер, дата выдачи, код подразделения, орган выдачи),
    IPv4/IPv6, URL.
  - Secrets: PEM key blocks, high-entropy tokens, `password=`/`api_key=` pairs.
  - Legal entities: abbreviated and full forms of ООО, АО, ПАО, ЗАО, ОАО, ИП,
    НПО, НКО, ИЧП, ТОО, ОП followed by a quoted name.
  - Names (ФИО), organizations, and locations via Natasha NER — all tokenized
    by default; organizations/locations can be opted out.
- Replace each detected value with a stable token `{{CATEGORY_N}}`.
- Write anonymized Markdown plus a JSON replacement map.
- Restore: rebuild the original text from anonymized text + map.

## Scope (out, for now)
- Desktop UI (Swift or Python) — separate later effort.
- Long-running `serve`/daemon mode — separate later effort.
- Visual redaction of the source PDF.
- Cloud LLM detection.

## Constraints
- Fully offline. No network calls at runtime.
- Detection: Natasha (offline). Optional LLM pass is local Ollama only.
- The `pdf-to-markdown` repo is reused as an external subprocess, not imported.
- Input text and replacement maps are never persisted except to the explicit
  output files the user requested.
- Python 3.11+. License: MIT.

## Success criteria
- Running `anon doc.pdf -o out.md --map out.map.json` yields Markdown with no
  raw PII and a usable map.
- Same source value always maps to the same token within one run.
- `anon restore` reproduces the original text exactly from output + map.

## Replacement design
- Token format: `{{CATEGORY_N}}` (double braces, Markdown-safe — unlike `[...]`).
- One counter per category; identical source value reuses its token.
- Map file: JSON `{ "{{PERSON_1}}": "original value", ... }`.

ADR-CANDIDATE: PDF support via external `pdf2md` subprocess rather than a code
dependency. Rationale: keeps backend choice open, avoids pulling heavy backend
deps, leaves `pdf-to-markdown` untouched. Alternative: import as a package
(rejected — couples to one backend branch).

ADR-CANDIDATE: token-based reversible replacement with a side map file.
Rationale: keeps output readable and allows restore. Alternatives: irreversible
masking (rejected — not restorable), inline encryption (rejected — unreadable).

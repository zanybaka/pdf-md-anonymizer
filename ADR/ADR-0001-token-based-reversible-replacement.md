# ADR-0001: Token-based reversible replacement with a side map file

- Status: Accepted
- Date: 2026-05-18
- Realized by: CORE-001

## Context
Anonymized documents must stay readable and the operation must be reversible,
so the original values can be recovered. The PRD recorded this as an
`ADR-CANDIDATE`; CORE-001 is the first implementation that realizes it.

## Decision
Replace each detected value with a `{{CATEGORY_N}}` token (double braces —
Markdown-safe). A per-category 1-based counter assigns tokens; an identical
value reuses its token. The token→original mapping is written to a separate
JSON map file. `restore()` rebuilds the original text from anonymized text plus
the map.

## Alternatives considered
- **Irreversible masking** (e.g. `***`) — rejected: not restorable.
- **Inline encryption of values** — rejected: output becomes unreadable.

## Consequences
- A side map file is PII-bearing and must be handled as sensitive.
- Input already containing `{{...}}` is handled: generated tokens skip any
  placeholder already present in the input.

# Project-specific agent rules (pdf-md-anonymizer)

Overrides and additions to the shared AGENTS.md for this repository only.

## Detection Module Invariants

These are not enforced by tests — agent must apply them manually.

- **New NER filter:** add a `SpanFilter` subclass to the `FILTERS` tuple in
  `src/anonymizer/detect/ner.py`; update the ordering snapshot in
  `tests/test_ner_filters.py`. Never add an inline `if … continue` block to
  `NerPipeline.detect()`.
- **Markdown / résumé logic:** ATX-header parsing, skill-section detection, and
  résumé-specific dict loads belong in `src/anonymizer/detect/structural.py`.
  `ner.py` imports and consumes the output; it does not own document-shape awareness.
- **NerPipeline state:** new per-pipeline state belongs on the `NerPipeline` class.
  Never introduce module-level mutable globals to `ner.py`; access the singleton
  via `get_default()`.
- **Corpus baseline:** `tests/corpus/baseline_metrics.json` is updated by hand in a
  PR when detection intentionally changes. `test_metrics_match_baseline` (±0.01
  tolerance) is the regression gate — do not auto-update it during refactors.
- **Enum hygiene:** always `Category.X`, `FileStatus.X`, `Stage.X` — never bare
  string literals. `test_architecture.py` guards detection modules; apply the same
  discipline in all other modules.
- **Rule ordering:** new `Rule(name="…", Category.X, re.compile(…))` entries in
  `src/anonymizer/detect/regex_rules.py` must update the snapshot in
  `tests/test_rule_ordering.py`. Earlier rules win on overlap — re-ordering is a
  detection behaviour change, not a refactor.

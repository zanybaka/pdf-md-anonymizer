# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added
- **DETECT-013** Optional label-anchored job-title and
  education-qualification detection. Two new opt-in regex rules
  (`JOB_TITLE`, `EDUCATION`) in `src/anonymizer/detect/regex_rules.py`
  capture the free-text role / qualification value listed after a Russian
  résumé label («Должность», «Занимаемая должность», «Роль» for `JOB_TITLE`;
  «Образование», «Квалификация», «Специальность», «Учёная степень» for
  `EDUCATION`) under a new umbrella `Category.OCCUPATION`
  (`src/anonymizer/categories.py`). The separator anchor requires at least
  one of `:`, `—`, or `-` between label and value (a pure-whitespace
  separator is rejected on purpose) so a free-text usage like «должность
  позволяет ему» — no colon, common-noun follow-on — does **not** match
  even with the flag on. The capture body `[^\n,;.]+` terminates on
  end-of-line, comma, semicolon, or period, so `Должность: Главный
  инженер.` tokenises the role text *without* the trailing period, and a
  two-clause line `Должность: Главный инженер. Образование: магистр
  информатики` splits into two distinct OCCUPATION captures. Off by
  default; opt-in via `Options.occupation: bool = False`
  (`src/anonymizer/api.py`) plus a CLI flag `--occupation`
  (`src/anonymizer/cli.py`). Gating uses the existing `Rule.option_name`
  field — `regex_rules.detect()` skips the gated rule when its
  `Options` attribute is falsy. The rule-ordering snapshot
  (`tests/test_rule_ordering.py`) is updated to add `JOB_TITLE`,
  `EDUCATION` after `FAMILY_RELATION`; the architecture-test category
  list (`tests/test_architecture.py::_CATEGORY_NAMES`) adds
  `OCCUPATION`; `Category` member count in `tests/test_categories.py`
  is bumped from 23 to 24. QA-001 corpus precision/recall is
  bit-identical when the flag is off (the new rules are gated behind
  `option_name="occupation"`); round-trip `anonymize → restore`
  reproduces the input exactly. No new dependencies; no network; no
  document content in logs.

- **DETECT-012** Optional label-anchored family-relation detection. A new
  opt-in regex rule (`FAMILY_RELATION`) in
  `src/anonymizer/detect/regex_rules.py` captures the capitalised names of
  family members listed after a Russian relation label («Супруга», «дети»,
  «сын», «дочь», «родители», «отец», «мать», «брат», «сестра» — including
  the «супруга»/«супруги»/«супругой» inflections) as `Category.PERSON`. The
  relation noun itself stays in the document — only the captured name
  becomes the span. Off by default; opt-in via `Options.family_relations:
  bool = False` (`src/anonymizer/api.py`) plus a CLI flag
  `--family-relations` (`src/anonymizer/cli.py`). The label part is
  case-insensitive via inline `(?i:…)` so a mid-sentence `дети:` after a
  semicolon matches as well as a sentence-leading `Супруга:`; the
  captured-name `[А-ЯЁ]` first-character anchor stays case-sensitive so a
  lowercase common-noun follow-on (`Дети программистов учатся быстрее`)
  does **not** match even with the flag on. A companion
  `_detect_family_continuation_names` helper walks comma-separated trailing
  names from the same label scope and emits each as its own PERSON span,
  so `Супруга: Иванова Анна Петровна; дети: Иванов Пётр, Иванова Мария`
  yields three distinct `{{PERSON_N}}` tokens. The relation noun list
  lives inline in the rule (no JSON dictionary, per the task spec). The
  rule-ordering snapshot (`tests/test_rule_ordering.py`) is updated to add
  `FAMILY_RELATION` after `BIOMETRIC_MENTION`; QA-001 corpus
  precision/recall is bit-identical when the flag is off (the new rule is
  gated behind `option_name="family_relations"`, just like the
  DETECT-009 biometric-mention precedent); round-trip
  `anonymize → restore` reproduces the input exactly. No new
  dependencies; no network; the new helper logs nothing.

- **DETECT-011** Structural validator for the БИК (Bank Identification
  Code) rule. A new `_bik_ok(value)` helper in
  `src/anonymizer/detect/regex_rules.py` rejects a 9-digit run that follows
  a `БИК` label but is not a real BIK: it enforces a 9-digit length, a
  country prefix in `{"04", "00"}` (Russia / CIS participants of the
  national payment system per the Central Bank of Russia), and a non-zero
  combined region-and-territorial sub-field (digits 3-6). The validator is
  attached to the existing label-anchored `BIK` rule via the `Rule.validator`
  field — the same wiring `_inn_ok`/`_ogrn_ok`/`_ogrnip_ok`/`_snils_ok` use.
  There is no published mathematical control-digit for BIK in the public
  CBR spec, so the validation is **structural** (length + country-prefix +
  non-zero sub-field) — documented explicitly in the `_bik_ok` docstring.
  No bare-BIK rule is added: without a mathematical checksum the
  false-positive rate on bare 9-digit runs (КПП looks identical, postal
  codes, internal IDs) would be unacceptable. CIS-country BIKs that share
  the format are kept detectable via the `00` prefix entry. Existing BIK
  coverage stays green — the corpus value `044599001`
  (`tests/corpus/02-company.json`) and the inline sample `044525225`
  (Sberbank Moscow, `tests/test_detect.py`) both pass the new validator;
  QA-001 baseline metrics are bit-identical. New unit tests in
  `tests/test_detect.py` cover the four cases: valid Russia-prefix BIK
  detected, invalid country prefix rejected, all-zero territorial
  sub-field rejected, corpus value still green, and a round-trip
  `anonymize → restore` is exact.

- **DETECT-010** Label-anchored medical-data detection. Four new always-on
  regex rules in `src/anonymizer/detect/regex_rules.py` cover ФЗ-152 medical
  PII: `OMS` for `Полис ОМС: <16 digits>`, `DMS` for `Полис ДМС: <token>`,
  `DIAGNOSIS` for `(?:диагноз|анамнез|история болезни): <line>`, and `ICD10`
  for МКБ-10 codes (`A00.0`…`Z99.9`) appearing immediately after a medical
  label (`диагноз`, `анамнез`, `МКБ`, `МКБ-10`, `код МКБ`). All four share a
  single umbrella `Category.MEDICAL` (`src/anonymizer/categories.py`) — the
  audit row lumps them together and the downstream replacement layer only
  cares about the category. The rules are precision-safe (every match
  requires an explicit Russian medical label), so they ship always-on like
  the existing label-anchored INN/OGRN/etc rules — no `Options` flag is
  introduced. The ICD-10 rule is compiled without `re.IGNORECASE` so the
  uppercase-Latin code (`I10.0`) is enforced; the label part carries its own
  inline `(?i:…)` group so `Диагноз`/`ДИАГНОЗ`/`диагноз` all match. A bare
  16-digit non-Luhn number outside a `Полис ОМС` label stays untokenised
  (the existing CARD rule misses real OMS numbers because they are not
  Luhn-valid), and an ICD-10-shaped token like `Раздел A10.1` in a table of
  contents is not matched (no preceding medical label). The rule-ordering
  snapshot (`tests/test_rule_ordering.py`) is updated to include `OMS`,
  `DMS`, `DIAGNOSIS`, `ICD10` between `SECRET_HIGH_ENTROPY` and
  `BIOMETRIC_MENTION`; the architecture-test category list adds `MEDICAL`.
  QA-001 corpus precision/recall is bit-identical (no medical descriptors in
  the corpus); round-trip `anonymize → restore` reproduces the input
  exactly.

- **DETECT-009** Optional surface-text biometric-mention detection. A new
  opt-in regex rule (`BIOMETRIC_MENTION`) in
  `src/anonymizer/detect/regex_rules.py` tokenises Russian biometric-data
  descriptors — «отпечаток пальца», «голосовой отпечаток», «голосовая
  модель», «ДНК», «генетические данные», «радужная оболочка [глаза]»,
  «биометрические данные» — under a new narrow `Category.BIOMETRIC`
  (`src/anonymizer/categories.py`). The rule is anchored on Cyrillic
  word boundaries (so a stem cannot match inside a longer word) and is
  case-insensitive. Default behaviour stays off — the mention itself is
  descriptive, not identifying — opt-in via a new `Options.biometric_mentions`
  flag (`src/anonymizer/api.py`) and a matching CLI flag
  `--biometric-mentions`. Gating is done by a new `Rule.option_name` field;
  `regex_rules.detect()` skips any rule whose gating attribute is falsy on
  the passed `Options`, so the existing rule list and detection pipeline
  stay unchanged when the flag is off. The rule-ordering snapshot
  (`tests/test_rule_ordering.py`) is updated to include `BIOMETRIC_MENTION`
  at the end of `RULES`, and the architecture-test category list is
  extended. With the flag off the QA-001 corpus precision/recall is
  bit-identical to the previous baseline (no biometric descriptors in the
  corpus); round-trip `anonymize → restore` reproduces the input exactly.
  Image / binary biometric payloads remain out-of-scope — this is text-only
  by construction.

- **DETECT-008** Document-declared alias propagation. A new
  `_ALIAS_RE` regex in `src/anonymizer/detect/regex_rules.py` matches the
  canonical Russian contract-alias shapes — `(далее — Х)`,
  `(далее именуемый Х)`, `(далее по тексту — Х)`. After regex and NER
  detection (and brand propagation), a new `_alias_propagate` pass in
  `src/anonymizer/detect/__init__.py` finds each alias declaration, locates
  the detected PERSON / ORG / LOC span immediately preceding the parenthesis
  (within ~10 non-whitespace characters), and emits a new span at the alias
  text site with the parent's category and `value=alias_text`. The
  downstream consistency sweep then propagates that span to every later
  word-bounded occurrence of the alias, so `ООО «Альфа-Бета» (далее —
  Альфа). … Альфа поставляет товар.` tokenises every `Альфа` mention as
  ORG, and `Иванов И.И. (далее именуемый Заказчик)` tokenises every
  `Заказчик` mention as PERSON — overriding Natasha's ORG tag for that
  word, because the alias declaration is the authoritative category for
  that text. Filters: alias text shorter than 3 characters, alias text
  containing `{{…}}` placeholders, and stoplisted alias text (country
  names, generic nouns — same NER stoplist used by brand propagation) are
  all skipped. Aliases with no detected parent span are left untokenized
  by the alias pass (Natasha may still tag them independently). QA-001
  corpus precision/recall unchanged (alias-declaration shape is not
  exercised in the current labelled corpus); round-trip `anonymize →
  restore` reproduces the input exactly.

- **DETECT-007** Brand short-name propagation across the document. A new
  propagation pass in `src/anonymizer/detect/__init__.py` (`_brand_propagate`)
  narrows every legal-form ORG span (`ООО «Альфа-Бета»`, `ООО АСТРАЛ-СОФТ`,
  full-spelling forms like `Общество с ограниченной ответственностью «Тест»`)
  to its inner company short-name and then scans the document for every
  word-bounded bare repeat of that short-name, adding it as an ORG span with
  the inner-name value. `replace_spans` reuses one token across the
  legal-form line and every later mention, so a document with one
  `ООО «Альфа-Бета»` followed by three bare `Альфа-Бета` mentions tokenizes
  all four occurrences to the same `{{ORG_1}}` and round-trip
  `anonymize → restore` reproduces the input exactly (the literal
  `ООО «...»` framing stays in the output). The reusable extractor lives in
  `src/anonymizer/detect/regex_rules.py` as `extract_inner_org_name(value)`
  — it strips the leading legal form, surrounding quotes, and a trailing
  legal-form short word. A minimum inner-name length of 3 characters and a
  reuse of the NER stoplist (`_lemma_key` against country names, generic
  nouns, …) gate propagation so `ИТ` from `ООО «ИТ-Сервис»` does not match
  inside `литер` and `Россия` from `ООО «Россия»` is not propagated to its
  bare country mentions. New `Options.brand_propagation: bool = True` plus a
  CLI `--brand-propagation` / `--no-brand-propagation` flag let callers opt
  out; with propagation off the legal-form ORG span keeps its full value
  (previous behaviour). `tests/corpus/02-company.json` updated to expect the
  inner-name ORG value (`Рога и Копыта`); QA-001 ORG precision/recall stay
  at 1.0/1.0 on the labelled corpus.

- **DETECT-006** ФЗ-152 PII coverage audit against the canonical category list
  in `../pdf c привт/TZ.md:80-146`. Triaged checklist now lives in
  `docs/detect-006-fz152-coverage.md`, with every row marked **covered /
  partial / missing / out-of-scope** plus file:line evidence. Five spawned
  per-gap tasks added to `BACKLOG.md` Phase 7: **DETECT-009** (biometric
  surface-text mentions, opt-in), **DETECT-010** (label-anchored ОМС / ДМС /
  МКБ-10 / диагноз / история болезни), **DETECT-011** (БИК structural
  validator), **DETECT-012** (optional family-relation labels), **DETECT-013**
  (optional job-title and education-qualification labels). Out-of-scope items
  (image / binary biometric data, photographs) recorded with one-line
  rationale. No detection code changed in this ticket — implementation lives
  in the spawned tasks.

- **DETECT-005** Context-anchored single-surname detector for electronic-signature
  blocks. A new `PERSON_SIGNATURE` rule in `src/anonymizer/detect/regex_rules.py`
  fires when a signature-context label (`УКЭП`, `подписант`, `подписал`,
  `подписавший`, `подписывающий`, `ФИО`, `фамилия`, `инициалы`, `подпись`) is
  followed by `:`/`-`/`—` and a capitalised Cyrillic token of ≥3 letters
  (e.g. `УКЭП: КРУГЛОВ`, `Подписант: Иванов`, `Подпись — Петрова`). Only the
  surname is captured as the span; the label stays verbatim. The label
  alternation is case-insensitive via an inline `(?i:…)` group, while the
  surname class is case-sensitive so a lowercase common noun does not match.
  Ordered after the CORE-005 patronymic-triple rule so a full ФИО after a
  signature label (`подписант: ИВАНОВ ИВАН ИВАНОВИЧ`) is still captured as the
  three-word person (the longer span wins overlap resolution in `_resolve`),
  not just the surname. Rule-ordering snapshot in `tests/test_rule_ordering.py`
  refreshed. Unit tests in `tests/test_detect.py` cover the three positive
  separators, the full-ФИО overlap, two negative cases (`Город: Москва` and
  `Подпись: АБ`), and a round-trip `anonymize → restore`. QA-001 corpus
  precision/recall on PERSON is unchanged.

- **UI-023** GitHub repository link in the main-window header. A small icon
  button anchored at the trailing edge of a new header row opens the project
  page in the user's default browser via `webbrowser.open`. The URL is read
  from PEP 621 metadata (`importlib.metadata.metadata("pdf-md-anonymizer")`,
  `Project-URL: Homepage, …`, with a `Home-page` fallback), so changing
  `[project.urls] Homepage` in `pyproject.toml` and reinstalling redirects
  the button without source-code edits. A monochrome GitHub Invertocat PNG
  is shipped under `src/anonymizer_ui/resources/` (1× and 2× variants); the
  button silently falls back to a "GitHub" text label if the icon cannot
  load. Unit tests in `tests/test_ui.py` cover the metadata resolver's
  Project-URL / Home-page / missing-package branches and assert the click
  handler calls `webbrowser.open` with the resolved URL.
- **UI-022** Main-window title now includes the running app version
  (e.g. `"PDF-MD Anonymizer 0.1.0"`) so users with multiple builds installed
  can tell at a glance which one is running. Version is sourced from
  Toga/Briefcase's `self.version` (already populated from `pyproject.toml`)
  with a fallback to `importlib.metadata.version("pdf-md-anonymizer")` and a
  final fallback to the bare formal name. The macOS application-menu name
  (Briefcase-controlled) is unchanged. Unit tests in `tests/test_ui.py`
  cover the three branches of `_window_title()` and assert the title matches
  the installed package version.

### Fixed
- **UI-021** Stage-progress log lines in the result view no longer concatenate
  onto a single row. `BatchRunController._on_stage_update` now appends `\n`
  when forwarding stage text to the `on_log` callback, matching the existing
  file-result lines (`✓ file.pdf (Xs)\n` / `✗ file.pdf: error\n`). The
  internal `_stage_text` used by `progress_text()` stays newline-free so the
  single-line status label is unaffected. Unit test
  `test_batch_controller_stage_log_is_newline_terminated` drives the
  controller through CONVERTING → DETECTING and asserts every log line ends
  with `\n` and that consecutive stage updates do not glue together.

### Changed
- **Complexity cleanup** Reduced cyclomatic complexity across the codebase
  (radon / lizard / xenon). Two functions at radon rank C were refactored
  via extract-function: `pdf_to_markdown` (CCN 11 → 4, split into
  `_spawn_pdf2md` / `_wait_for_pdf2md`) and `_find_site_packages`
  (CCN 12 → 8, split out `_resolve_via_shebang`). `AnonymizerApp.startup`
  was decomposed from 137 lines / CCN 6 into five focused helpers
  (`_build_main_layout`, `_register_global_commands`,
  `_apply_initial_window_prefs`, `_install_macos_hooks`,
  `_setup_pdf_controller`); `on_run` was flattened by extracting
  `_ensure_pdf_backend_ready`.

- **appkit_bridge package** Split the 831-line `appkit_bridge.py` into the
  `appkit_bridge/` package: `_common`, `activation`, `pasteboard`,
  `notifications`, `file_picker`, `status_icon`, `drag_drop`,
  `global_hotkey`, `reopen_handler`, `accessibility`, `login_item`. The
  public API is re-exported from `__init__.py`, so callers keep using
  `from anonymizer_ui import appkit_bridge` and `appkit_bridge.X`. The
  UI-009 architectural rule ("ObjCClass calls confined to one place") is
  preserved at the package boundary; `test_objcclass_only_in_appkit_bridge`
  updated accordingly. Test monkeypatches of private helpers
  (`_macos_version_tuple`, `_register_via_swift`, …) now target the
  submodule that owns them.

- **pdf_backend package** Split the 525-line `pdf_backend.py` into the
  `pdf_backend/` package: `_smoke` (smoke-test runner + minimal-PDF
  generator), `_script_patch` (`pdf2md` shebang rewriter), and the rest
  in `__init__.py`. Site-packages resolution stays in `__init__` so the
  `pdf_backend._python_lib_tag` monkeypatch in tests keeps working.

- **ner_helpers split** Extracted span-shape helpers and POS predicates
  from `detect/ner.py` (500 LOC) into `detect/ner_helpers.py`. The
  filter chain (`FILTERS` tuple + `SpanFilter` subclasses) and the
  `NerPipeline` class stay in `ner.py` per the Phase-8 architectural
  invariant. `ner.py` re-exports the helpers so test imports such as
  `from anonymizer.detect.ner import _merge_hyphenated` keep working.

- **clipboard_ops + main_window_layout** Extracted the clipboard/notify
  flow (`run_anonymize_to_clipboard`, `read_clipboard`, `write_clipboard`,
  `send_notification`) and the Toga widget construction
  (`build_main_layout` returning a `MainWindowWidgets` dataclass) from
  `app.py`. Three regression tests for the threaded anonymize path were
  updated to call `clipboard_ops.run_anonymize_to_clipboard` directly
  with explicit callbacks instead of monkeypatching an unbound method.

### Fixed
- **Briefcase create — docopt install** Vendored
  `vendor/docopt-0.6.2-py2.py3-none-any.whl` and referenced it from
  `[tool.briefcase.app.anonymizer-ui].requires`. pymorphy2 (transitive
  dep of natasha) requires `docopt>=0.6`, but upstream docopt 0.6.2 ships
  sdist-only on PyPI, which Briefcase's `--only-binary :all:` pip install
  cannot fetch. The vendored wheel resolves the requirement from a local
  path before pip queries PyPI. Pre-existing failure unrelated to the
  complexity cleanup (same error in `logs/briefcase.2026_05_18-*.log`).

### Added
- **PDF-004** Batched `pdf2md` invocation: `convert.pdf_batch_to_markdown`
  spawns **one** subprocess for a group of PDFs and streams per-file results
  out through an `on_file` callback as each conversion finishes. The
  Docling model loads once per group instead of once per file, so a 3-file
  PDF batch costs roughly `init + N × per_file_convert` wall-clock instead
  of `N × (init + per_file_convert)`. `batch.process_files` now groups
  consecutive `.pdf` inputs into one `pdf_batch_to_markdown` call; a `.md`
  input or end-of-list flushes the group. Per-file conversion failures are
  reported via `on_file(path, exception)` and do not abort siblings;
  `cancel()` between files kills the subprocess and keeps already-written
  outputs. ADR-0002's subprocess boundary is preserved — the import of the
  `pdf-to-markdown` package lives in a `-c` driver string executed in the
  child process, never in `src/anonymizer/`. A `pdf2md` build with no
  Python shebang or older builds without `create_docling_converter` fall
  back to one subprocess per file. Public `pdf_to_markdown(path, …)`
  signature unchanged. New ADR-0010.

- **Complexity tooling** `radon`, `lizard`, `xenon`, `wily` added to the
  `dev` extra. New `xenon` pre-commit hook
  (`--max-absolute B --max-modules B --max-average A src/`) fails the
  commit when any function lands at rank C or worse.

- **DETECT-004** Regex detector for `@`-style nickname mentions. A new
  `NICKNAME` category and rule detect handles such as `@vasily`, `@john_doe`,
  and `@user-name`. The negative lookbehind `(?<!\w)` prevents matching the
  local-part of an email address (`vasily@example.com`), and the EMAIL rule
  (ordered first) wins any overlap. A bare `@` or `@123` (no leading letter)
  is not matched. `Category.NICKNAME` added to the `Category` StrEnum.
  Rule ordering snapshot updated.

- **UI-020** "Launch at Login" toggle in the status-bar menu, placed in the
  same section as the Quit item. When enabled, the app registers itself as
  a macOS login item with `--background` via `SMAppService.mainAppService`
  (macOS 13+) or a user `LaunchAgent` plist (older macOS), and forces the
  "Stay in menu bar" switch ON and disables it (menu-bar mode is a
  prerequisite for a background-only start). When disabled, the login item
  is unregistered and the Stay switch is restored to its prior state.
  The `--background` flag is consumed in `__main__.py` before
  `toga.App.main_loop()`; when present, `main_window.show()` is skipped so
  only the menu-bar icon appears at login. `launch_at_login: bool` is
  persisted in `prefs.json`. On startup the pref is reconciled with the
  actual `SMAppService` registration status. No new runtime dependencies.
  New `appkit_bridge` helpers: `register_login_item(args)`,
  `unregister_login_item()`, `is_login_item_registered()`.
  New `MenuBarController` methods: `_apply_stay_lock`, `_cmd_toggle_launch_at_login`,
  `_reconcile_launch_at_login`, `stay_locked` property.

### Fixed
- **UI-019** Drag-and-drop was silently rejected on macOS 12+ because Finder
  switched its primary file-drag pasteboard type from `NSFilenamesPboardType`
  to `public.file-url` (NSPasteboardTypeFileURL), but the overlay registered
  only the legacy type so `draggingEntered_` was never called — no drop cursor
  appeared and files were never added to the list.
  Fix in `appkit_bridge.setup_drag_drop`: (1) the overlay now registers for
  **both** `"NSFilenamesPboardType"` and `"public.file-url"` so AppKit invokes
  the drag-enter callback on all macOS versions; (2) `performDragOperation_`
  tries the legacy `propertyListForType_("NSFilenamesPboardType")` path first
  and falls back to `readObjectsForClasses_options_(NSArray<NSURL>, None)`,
  extracting paths via `NSURL.path`, when the legacy type returns nothing.
  The `.pdf`/`.md` extension filter in `drag_drop_overlay.setup` is unchanged.
  No new dependencies.

### Added
- **UI-018** Global system keyboard shortcut ⌃⌥⌘C for "Anonymize Clipboard"
  while menu-bar mode is active. Uses
  `NSEvent.addGlobalMonitorForEventsMatchingMask:handler:` (Input Monitoring)
  so the action works from any application without switching focus.
  The handler fires on an AppKit thread and schedules work on the asyncio
  event loop via `loop.call_soon_threadsafe`, producing identical UX to the
  menu-bar "Anonymize Clipboard" item (same notification, same busy icon).
  A `global_hotkey_enabled: bool` pref (default `true`) in `prefs.json`
  suppresses registration without disabling menu-bar mode.  A one-time
  guidance notification fires on first menu-bar activation to direct the user
  to System Settings › Privacy & Security › Input Monitoring; the
  `hotkey_permission_prompted: bool` pref prevents repeat prompts.
  The shortcut is registered when the status item is created and unregistered
  when it is removed — active/inactive within one toggle cycle, no restart
  needed.  `appkit_bridge.register_global_hotkey` /
  `appkit_bridge.remove_global_hotkey` are independently unit-tested with a
  stubbed `NSEvent` class.

### Fixed
- `NerPipeline.detect` now recovers PERSON (and ORG/LOC) spans that Natasha's CRF
  model silently drops when the immediately surrounding lines provide a confusing
  token sequence (observed: a bare `/` on the line after a name, or a navigation
  word like `Аватар` on the line before it). The fix adds a per-line fallback pass:
  after the full-document NER run, `_detect_inner` is also called for each individual
  line and any non-overlapping spans are added to the result with adjusted offsets.
  Skill-section suppression is re-applied post-hoc using full-document ranges so
  ORG/LOC entities inside skills sections are not incorrectly resurrected.
  Trade-off: ~2× NER inference time on the total text; not a concern for clipboard
  or typical résumé lengths.

### Changed
- pdf-backend pip runner unified to a single `SubprocessPipRunner`. The in-process
  variant (`InProcessPipRunner`, `_find_pip_wheel`, `_LineWriter`) was dead defensive
  code: in `.app` we already used the subprocess runner with the system python, and
  in a dev venv the bundled-wheel `sys.path` injection was redundant because pip is
  importable from the venv anyway. The remaining runner binds to
  `_find_build_python() or sys.executable`, keeping the same behaviour for both
  deployment modes while removing ~60 lines and the side effects of importing
  `pip._internal` into our own process.

### Fixed
- `_find_site_packages` could pick a stale `lib/pythonX.Y/site-packages/` from a
  previous install when several Python-version subtrees coexisted (e.g. an old
  `.app` install put packages under `python3.14` and a later dev-venv install
  put them under `python3.12`). The old name-sort heuristic returned the
  highest-version one even though pip had freshly installed to the lower
  version dir matching its actual Python.  Consequence:
  `_clean_orphan_python_dirs` then deleted the FRESH install (treating it as
  orphan) and `_patch_pdf2md_script` pointed `sys.path` at the stale tree —
  the shebang Python then tried to load a `.so` built for a different CPython
  ABI and the smoke test failed with `ModuleNotFoundError: pydantic_core._pydantic_core`.
  Now `_find_site_packages` queries the shebang of `bin/pdf2md` (the Python pip
  actually used) for its `python{X}.{Y}` tag and returns the matching subtree.
- File open dialog could appear behind another frontmost app on first menu-bar
  invocation: `appkit_bridge.pick_file` was using the same `ns_app.activate()`
  (macOS 14+) → `activateIgnoringOtherApps_` fallback chain that caused the
  "Show Window" two-click bug. Right after the Accessory → Regular activation
  policy flip, `activate()` no-ops and the NSOpenPanel lands behind whichever
  app was previously frontmost. Switched to the legacy aggressive form to match
  the fix in `activate_app`.
- "Anonymize File" felt dead for tens of seconds before showing the start alert
  on PDF input: `_anonymize_in_thread` was calling `source()` (which for the PDF
  path is `read_input(path)` → `pdf2md` subprocess, 30–90 s) on the UI thread
  **before** firing the "Anonymizing…" notification and starting the busy icon.
  Moved `source()` inside the worker thread so the notification and busy icon
  fire immediately on click; added a regression test
  (`test_anonymize_in_thread_notifies_before_slow_source`) that asserts the
  notification and `_begin_busy` precede the `source()` call.
- "Show Window" required two clicks: `appkit_bridge.activate_app()` was using the
  macOS 14+ `NSApplication.activate()` API which respects the currently frontmost
  app and silently no-ops right after an Accessory → Regular activation-policy
  transition. The first click changed policy but did not yank focus; the second
  click then worked because the app was already Regular. Reverted to the legacy
  `activateIgnoringOtherApps_(True)` (the same call the pre-refactor code used),
  which works on the first click.
- Cancel during PDF conversion: `pdf_to_markdown()` now accepts a `cancel: Callable[[], bool]`
  parameter. Internally it uses `Popen` + `communicate(timeout=0.2)` polling; when
  `cancel()` returns `True` the subprocess is killed and `ConversionCancelled` is raised.
  `read_input()` and `anonymize_file()` thread the `CancelToken` down to the subprocess,
  so Cancel now interrupts an in-progress PDF conversion within ~200 ms instead of only
  taking effect between files.
- PDF backend after Update: install / update now run a post-install
  `_finalize_install()` that (a) sweeps orphan `lib/pythonX.Y/` subtrees left by
  previous installs against now-uninstalled Python versions (e.g. after a Homebrew
  bump of `python3`), (b) writes the minimal `sys.path.insert` patch into `pdf2md`,
  (c) runs a smoke conversion on a tiny in-code-generated PDF, and (d) only if that
  smoke test fails on the docling MPS+float64 limitation does it rewrite the script
  with `torch.backends.mps.is_available = lambda: False`. When upstream docling fixes
  the float64 use, the next Update's smoke test passes and the shim is left out
  automatically — restoring GPU acceleration without a code change. `_patch_pdf2md_script()`
  is now parameterised (`with_mps_shim`) and fully idempotent (sentinel-tagged lines plus
  the older non-sentinel `sys.path.insert` form are both stripped before re-injection).
  `_find_site_packages()` prefers the directory that contains `pdf_to_markdown*` files
  so an update that installs to a different Python version subdirectory picks the right path.

### Added
- CLI-003: replaced the `sys.argv` rewrite in `cli.main()` with an argparse-native
  routing strategy. Subcommand names are now derived from the parser itself via
  the subparsers action's `choices` dict, so adding a new `sub.add_parser(...)` call
  automatically extends routing with no inclusion-list edit. When no subcommand is
  given, `main()` builds a standalone anonymize parser (prog="anon") and parses
  directly. `anon doc.md`, `anon restore out.md --map m.json`, and `anon --help`
  all behave as before. ADR not required — CLI contract unchanged; pure refactor.
- QA-002: added `tests/corpus/baseline_metrics.json` storing per-category
  precision/recall (3 decimal places) and tp/fp/fn counts. Added
  `test_metrics_match_baseline` to `test_corpus_eval.py` asserting each metric
  stays within ±0.01 of the baseline. Updated `load_corpus()` to only load
  numbered corpus files (`NN-*.json`) so the baseline JSON is not treated as a
  corpus document. Baseline must be updated manually when detection intentionally
  changes. ADR not required — no detection logic change.
- NER-011: moved `_ensure_pkg_resources()` call to module import time in a
  `warnings.catch_warnings()` block that suppresses the `pkg_resources is deprecated`
  UserWarning once for the whole process. Removed the per-build `with warnings.catch_warnings()`
  block and `_ensure_pkg_resources()` call from `_build_pipeline`. The stub is installed
  before any natasha-side import that needs it. ADR not required — no behaviour change.
- NER-010: created `src/anonymizer/detect/structural.py` with `skill_section_ranges(text)`
  and `is_in_any_range(start, ranges)`. Moved `_HEADER_RE`, `RESUME_FIELD_LABELS`,
  `RESUME_SECTION_HEADERS`, `RESUME_SKILL_SECTION_STEMS` from `ner.py` to `structural.py`.
  `ner.py` imports `structural` and delegates; `_skill_section_ranges` kept as a
  backward-compat alias. `_SkillSection.keep()` updated to use `is_in_any_range()`.
  `_STOPLIST_TERMS` references `structural.RESUME_*` constants. Added 11 tests in
  `tests/test_structural.py`. ADR not required — pure refactor, no detection change.
- NER-009: introduced `NerPipeline` class in `src/anonymizer/detect/ner.py`.
  The class builds the natasha components in `__init__`, exposes `lemma_key(text)`
  as an instance-level `lru_cache`d method, owns the stoplist as a lazy property,
  and provides `detect(text, options) -> list[Span]` using the `FILTERS` chain.
  Module-level globals `_pipeline` and `_stoplist_keys` removed; replaced by
  `_default: NerPipeline | None` and `get_default()` factory with double-checked
  locking. `warmup(on_step=...)` and module-level `detect()` delegate to the
  singleton. ADR not required — backward-compat API unchanged; pure refactor.
- NER-008: extracted `SpanFilter(Protocol)` chain from `ner.detect()`. Added
  `NerContext` dataclass (`text`, `skill_ranges`, `stoplist`) and six concrete
  filters — `_CategoryRouting`, `_PersonPropn`, `_OrgLocPropn`, `_SkillSection`,
  `_TechStoplist`, `_LemmaStoplist` — collected in a module-level `FILTERS` tuple.
  `detect()` body is now 19 lines (was 53). Ordering locked in `tests/test_ner_filters.py`
  snapshot; 21 new unit tests cover each filter independently. ADR not required —
  pure refactor, no detection output change.
- DETECT-003: converted `Rule` in `src/anonymizer/detect/regex_rules.py` from a
  `NamedTuple` to a `@dataclass(frozen=True)` with a new `name: str` field as the
  first argument. Every entry in `RULES` now carries a stable identifier (e.g.
  `"INN_LABELED"`, `"INN_BARE"`, `"SECRET_PEM"`, `"SECRET_HIGH_ENTROPY"`). Added
  `tests/test_rule_ordering.py` with a snapshot test that locks the current rule
  sequence. Architecture test updated to allow `Rule(...)` name strings that coincide
  with category names. ADR not required — purely internal refactor with no API changes.
- CORE-009: `detect/__init__.py` now imports `ner` at module scope (no more lazy
  `try/except ImportError`). `getattr(options, "consistency_sweep", True)` replaced
  with `options.consistency_sweep` (the field has always been a dataclass default).
  A missing `natasha` install now fails loudly at import rather than silently skipping
  NER detection.
- CORE-008: replaced `OutputDirArg` Union and `_resolve_dir` in `batch.py` with
  `class OutputPolicy` providing `OutputPolicy.into_directory(d)` and
  `OutputPolicy.next_to_input()` classmethods and a `resolve(input_path) -> Path`
  method. `process_files` now accepts `output_policy`/`map_policy` parameters.
  `cli.py`, `app.py`, and `batch_controller.py` updated accordingly. Tests updated.
- CORE-007: added `FileStatus` (DONE/FAILED/CANCELLED) and `Stage` (CONVERTING/DETECTING)
  `StrEnum` classes in `src/anonymizer/batch.py`. `FileResult.status` narrowed to
  `FileStatus`; all `on_stage` callbacks use `Stage` values. Raw string literals
  replaced in `batch.py`, `cli.py`, `app.py`, and `batch_controller.py`. Architecture
  test added to `test_architecture.py` verifying no bare status/stage strings remain.
- CORE-006: introduced `Category` (`StrEnum`) in `src/anonymizer/categories.py` with
  all 20 detection category members. `Span.category` narrowed from `str` to `Category`;
  all `Rule(...)` entries in `regex_rules.py` use `Category.<NAME>`; `_TYPE_TO_CATEGORY`
  and every `if category == ...` check in `ner.py` use `Category` enum values. Because
  `Category` is a `StrEnum`, the `{{CATEGORY_N}}` wire format and all string comparisons
  are unchanged. Architecture test added to `tests/test_architecture.py`; new
  `tests/test_categories.py` verifies equality, f-string formatting, and member count.
- UI-015: replaced `_run_pip` / `_run_pip_subprocess` / `_pip_install(upgrade=…)` in
  `pdf_backend.py` with `PipRunner` Protocol, `InProcessPipRunner`, and
  `SubprocessPipRunner`. Boolean flag replaced by separate `install_backend` /
  `update_backend` functions. Added `resolve_cert()` free function. `sys.path.insert`
  for the pip wheel now happens at most once per `InProcessPipRunner` instance. Two new
  tests verify the exit-code-to-RuntimeError mapping and the single-insertion invariant.
- UI-014: created `src/anonymizer_ui/drag_drop_overlay.py` with a `setup()` function
  that wraps `appkit_bridge.setup_drag_drop` and adds pure-Python `.pdf`/`.md`
  extension filtering. `app.py._setup_drag_drop` now calls
  `drag_drop_overlay.setup(...)`. Two unit tests verify extension filtering without
  requiring a real ObjC runtime.
- UI-013: extracted `_anonymize_in_thread` helper on `AnonymizerApp`, collapsing the
  duplicate thread-and-notify boilerplate in `_do_anon_file_to_clipboard` and
  `_anon_clipboard_to_clipboard`. Both are now one-line delegating wrappers.
  Empty-source (empty clipboard) early-exit is now inside the helper.
- UI-012: extracted `MenuBarController` into `src/anonymizer_ui/menubar_controller.py`.
  It owns `_status_icon`, `_status_commands_added`, `_busy_count`,
  `_saved_status_icon_image`, and all menu-bar lifecycle methods
  (`create_status_item`, `remove_status_item`, `hide_window_to_menubar`,
  `show_main_window`, `begin_busy`, `end_busy`). `app.py` forwards to the
  controller; `app.py` no longer references `toga.MenuStatusIcon` directly.
  All `test_on_window_close_*`, `test_on_menubar_pref_change_*`, and
  `test_status_bar_has_two_clipboard_commands` tests rewritten to drive the
  controller directly.
- REF-001: added `tests/test_architecture.py` with `_files_matching` and `_grep_count`
  helpers and a smoke test asserting the core package does not import Toga.
  This file is the canonical home for Phase 8 module-boundary checks.
- UI-008: two status-bar quick actions.
  "Anonymize to Clipboard…" is replaced by two distinct menu items:
  **"Anonymize File to Clipboard…"** opens a file picker each time it is
  pressed; the picker is shown via `NSOpenPanel.beginWithCompletionHandler_`
  (rubicon-objc Block) without attaching to the main window, so the hidden
  main window stays hidden when the app is in menu-bar-resident mode.
  **"Anonymize Clipboard"** reads plain text from `NSPasteboard`, anonymizes
  it in a background thread, and writes the result back to the clipboard —
  no file picker, no file written to disk. A macOS notification fires on
  success or when the clipboard holds no text. Added `_read_clipboard()`
  static method and `_pick_file_standalone()` async helper. Three unit tests
  added: anonymize-text path, empty-clipboard notification, and menu-command
  registry check.
- UI-004: menu-bar resident mode with "Anonymize to Clipboard" quick action.
  A "Stay in menu bar when window is closed" toggle (default off) persists in
  `~/Library/Application Support/pdf-md-anonymizer/prefs.json`. When on,
  closing the main window hides it via `NSWindow.orderOut:` and shows a
  status-bar icon with a menu: "Show Window" (restores the window and brings
  the app to the front), "Anonymize to Clipboard…" (opens a single-file
  picker, anonymizes in a background thread, writes result to `NSPasteboard`,
  fires an `NSUserNotification` on success or failure), and — after a
  separator — "Quit". Toggling the switch off removes the status icon
  immediately. The status icon uses Toga's native `toga.MenuStatusIcon` so
  menu command dispatch goes through Toga's own command machinery (ADR-0009) —
  no new runtime dependency. Four unit tests added.
- UI-006: "Save replacement map" switch in the desktop UI (default off).
  A `toga.Switch` labelled "Save replacement map" appears below the output
  folder label and above the file table. When checked, a `.map.json` is
  written alongside each anonymized output (into the chosen output folder or
  next to each input file when no output folder is set). When unchecked (the
  default), no map is written. The switch is disabled while a run is in
  progress and re-enabled when the run completes. Depends on CLI-002.
- CLI-002: map export is now opt-in across CLI, batch layer, and UI.
  `anon doc.md` writes only `doc.anon.md`; add `--map <file>` or
  `--map <dir>` to also write the replacement map. Batch mode similarly
  writes no maps unless `--map` is given. The UI writes no maps unless the
  new "Save replacement map" switch is on. `anon restore` is unchanged.
  Tests updated: two auto-map assertions replaced with explicit no-map
  assertions; two new tests verify opt-in behavior.
- UI-005: drag-and-drop and Finder-clipboard paste to add input files.
  Dropping one or more `.pdf`/`.md` files from Finder onto the app window
  appends them to the input list; non-.pdf/.md files are silently ignored;
  the status bar shows "Drop files here…" while a drag hovers over the window.
  Copying files in Finder (Cmd+C) and pressing Cmd+V in the app reads file
  paths from `NSFilenamesPboardType` via NSPasteboard and appends them too
  (no-op when the clipboard holds no file URLs). Both paths reuse the new
  `_add_inputs` helper (extracted from the file-dialog handler), which
  deduplicates and filters by extension; the drag-and-drop overlay is a
  transparent rubicon-objc `NSView` subclass (`_AnonymDropOverlay`) with
  `hitTest:` returning nil so normal click/keyboard events pass through.
  Three unit tests added for `_add_inputs` (filtering, string coercion,
  no-refresh-when-empty).
- UI-003: bundled `pdf_to_markdown-*.whl` in `anonymizer_ui/resources/wheelhouse/`
  so the first-use PDF backend install no longer requires a system Python
  interpreter.  `pdf_backend.install()` passes `--find-links <wheelhouse>` to
  in-process pip; pip installs `pdf-to-markdown` from the local wheel and
  downloads all heavy deps (docling, torch, …) as binary wheels from PyPI — no
  source compilation, no `sys.executable` build-isolation subprocesses.  Added
  `pdf_backend.installed_version()` to read the installed version from
  `dist-info`.  Added `pdf_backend.update()` to upgrade from the latest git
  revision (still requires a system Python because pip must build from source).
  The desktop UI now shows the current backend version and an «Update PDF
  backend» button; the button is gated behind a check for system Python and
  shows an informative dialog when none is found.
- UI-002: first-use PDF backend install in the desktop `.app`. When the user
  opens a PDF and no `pdf2md` is found, the app asks once whether to install
  the docling-backed `pdf-to-markdown` backend. The install runs off the UI
  thread; pip output streams live to the result view so the user can see
  progress. The backend lands in a Python venv at
  `~/Library/Application Support/pdf-md-anonymizer/pdf-backend/`; later
  launches detect it and skip the install. On network failure the install
  fails gracefully — a clear error is shown and Markdown files continue to
  work. The CLI `[pdf]` extra and `pdf2md`-on-`PATH` behaviours are unchanged.
  `convert.py` now checks the user backend venv as the second resolution step
  (after env-local, before PATH). `anonymizer_ui.pdf_backend` module added with
  `backend_dir`, `pdf2md_path`, `is_installed`, and `install` helpers. Realizes
  ADR-0008.
- CORE-001: detection span model (`Span`), `Options`, `AnonResult`, and
  right-to-left token replacement (`replace.py`, `api.py`). Tokens use a
  per-category 1-based counter; identical values reuse their token;
  pre-existing `{{...}}` placeholders never collide with generated tokens.
- CORE-002: regex/dictionary detectors for EMAIL, PHONE, INN, SNILS, OGRN,
  OGRNIP, KPP, BIK, ACCOUNT, CARD (Luhn-validated), DOB, POSTAL_CODE, ADDRESS,
  PASSPORT, IP (v4/v6), URL, SECRET, and legal entities (ORG) — abbreviated and
  full forms. Overlap resolution: earlier match wins.
- CORE-003: replacement-map serialization (sorted-key UTF-8 JSON), `restore()`,
  and the `anon restore` subcommand.
- PDF-001: `convert.py` subprocess wrapper over the external `pdf2md` CLI,
  with `--pdf2md-cmd` override and clear errors for missing/failed commands.
- PDF-002: opt-in `[pdf]` extra bundling the `pdf-to-markdown` converter from
  git into the anonymizer's own environment (`[tool.hatch.metadata]
  allow-direct-references` enabled for the git dependency). `convert.py` now
  prefers the env-local `pdf2md` (`sys.prefix/bin`) over `PATH`; `--pdf2md-cmd`
  still overrides. (The desktop `.app` no longer bundles it — see ADR-0008.)
- CLI-001: batch input — multiple files and glob wildcards, extension-preserving
  output names, observable per-file results (`batch.process_files`), and a
  cooperative `CancelToken`.
- NER-001: Natasha NER detection (`detect/ner.py`) for PERSON, ORG, and LOC,
  all tokenized by default; `--no-ner-org`/`--no-ner-loc` opt out. Regex matches
  keep priority over NER. Adds the `natasha` runtime dependency.
- NER-002: NER post-filter in `detect/ner.py` — each span is clipped at its
  first newline and stripped of edge whitespace/markdown (so spans no longer
  leak into adjacent blocks), and spans whose value matches a non-sensitive
  stoplist (country names, document grifs, generic nouns, bare legal forms)
  are dropped. The stoplist is matched on word-by-word Natasha lemma keys, so
  any declension is caught (e.g. "Российской Федерации", a genitive bare
  "Общества с ограниченной ответственностью") — a morph tagger is added to the
  NER pipeline; no new dependency.
- CORE-004: post-detection consistency sweep — after regex + NER detection,
  each detected value is propagated to its remaining word-bounded occurrences
  so partially-detected entities get fully tokenized (closes NER recall gaps).
  On by default; `Options.consistency_sweep` / CLI `--no-consistency-sweep`
  disable it.
- DETECT-002: bare INN detection — a label-free 10- or 12-digit run is now
  tokenized as `INN` when it passes the `_inn_ok` checksum (from DETECT-001),
  so an INN in free text no longer leaks. Ordered after the label-anchored INN
  and the bare OGRN/OGRNIP rules; a 13/15-digit OGRN/OGRNIP run cannot match.
- CORE-005: two regex detectors for PII leaking in electronic-signature blocks.
  A `PERSON` rule matches three-word ФИО anchored by a Russian patronymic suffix
  (case-insensitive, so it catches all-caps signatures Natasha misses and also
  complements NER on normal-case names); a capitalised word triple without a
  patronymic is not matched. A `SECRET` rule matches `№`-prefixed uppercase-hex
  certificate serials of 20+ characters (the high-entropy rule needs mixed case
  and misses them). No new dependencies.
- NER-003: case normalization before NER. `detect/ner.py` now feeds Natasha a
  copy of the text where ALL-CAPS Cyrillic words are Title-cased (legal-form
  abbreviations kept uppercase), so ALL-CAPS ФИО and unquoted company names
  (`ООО АСТРАЛ-СОФТ`) are tagged. The rewrite is length-preserving, so span
  offsets index the original text and each value is sliced from the original
  casing — `restore` stays exact. No new dependencies.
- PDF-003: `convert.py` now rejoins hyphenated words wrapped across a line by
  `pdf2md` (`Санкт-\nПетербург` → `Санкт-Петербург`) before the Markdown is
  returned, so one entity is no longer split into two tokens. Markdown list
  markers and em-dash bullets are left untouched.
- NER-004: NER post-filter extended — a `PERSON` span with no `PROPN` token is
  dropped (common nouns like `Программист` mislabeled as a name), and the
  stoplist gained the twelve Russian month names and résumé section headers.
- NER-005: curated developer-tool stoplist in `detect/ner.py` — `ORG`/`PERSON`
  spans matching common tools/technologies (`Docker`, `Jenkins`, `Gitlab CI`,
  …) are dropped, while real Latin-script company names stay detected. The
  stoplist also covers common engineering practice terms (`Code Review`,
  `Mentoring`, `Production`, …) and generic nouns (`Банк`, `Вэб`) that surface
  as false positives in résumé skill sections.
- NER-006: structural NER false-positive suppression — `detect/ner.py` now
  detects skills/technologies/competencies sections by their Markdown header
  and drops `ORG`/`LOC` spans starting inside them, so résumé tool names are
  suppressed wholesale instead of one curated stoplist entry at a time. Real
  employer names (in the experience section) stay detected; the NER-004/005
  stoplists remain as a precision backstop. No new dependencies.
- NER-007: the NER POS filter now also covers `ORG`/`LOC` spans — a span built
  purely from common-noun-class words (noisy-transcript false positives like
  `Вокруг`/`Канцелярия`) is dropped, while a real org/place keeps its `PROPN`
  token and a Latin-script company (`Deutsche Bank`, tagged `X` by the morph
  tagger) is kept. Gated by `Options.ner_pos_filter` / CLI `--no-ner-pos-filter`
  (default on). A noisy-transcript document was added to the QA-001 corpus; the
  evaluation harness shows the `Вокруг` `LOC` false positive eliminated with
  the filter on and no recall regression on real entities.
- UI-001: Toga desktop UI (`anonymizer_ui` package) over the in-process core —
  multi-file pick, options, off-thread batch run with live per-file status,
  overall progress, elapsed/ETA, and a Cancel control. Briefcase packaging
  config added under `[tool.briefcase]`. UI deps live in the `ui` optional
  group, not the core runtime. `briefcase create`/`build` produce a runnable
  `pdf-md-anonymizer.app`; a local `wheelhouse/` provides a `docopt` wheel because
  Briefcase installs bundle requirements with `--only-binary`.

### Fixed
- Briefcase config: the app table key was `pdf-md-anonymizer` while the UI
  package is `anonymizer_ui`; Briefcase requires the app's package to be in
  `sources` and named after the app key (hyphens → underscores), so
  `briefcase build` aborted with a `sources` configuration error. The key is
  now `[tool.briefcase.app.anonymizer-ui]` → package `anonymizer_ui`. The
  bundled app stays `pdf-md-anonymizer.app` (from `formal_name`).
- DETECT-001: INN, OGRN, OGRNIP, and SNILS detectors now verify the official
  control digit (`_inn_ok`, `_ogrn_ok`, `_ogrnip_ok`, `_snils_ok` attached as
  rule validators, like `CARD`'s Luhn check). A long non-identifier digit run
  (cost-estimate amounts, order codes) that fails the checksum is no longer
  mis-tokenized as OGRN/OGRNIP.
- NER-004 POS filter: the proper-noun check now only inspects tokens inside
  the trimmed span, so a heading like `Желательное` is no longer kept alive by
  a real name that the untrimmed span pulled in across a newline.
- DOB detection now also fires on the `родился`/`родилась` anchor and on a
  date written with a Russian month name (`16 января 1983`), not only numeric
  formats next to `дата рождения`/`д.р.` — it stays label-anchored.
- URL detection now catches scheme-less links: a `www.` host and a bare domain
  on a known TLD (`unicum.ru`). This covers markdown link text
  (`[www.site.com/x](…)`), whose visible half carries no `https://` prefix.
  Dotted dev-tool names (`Node.js`, `Socket.io`) are not mistaken for URLs.
- The C-family languages (`C`, `C++`, `C#`) are now in the developer-tool
  stoplist — Natasha tagged `C++` as `ORG`, and they sit in inline prose / a
  `Languages:` list, not under a skills-section header, so NER-006's structural
  suppression does not reach them.
- The résumé field label `Желательное` ("Желательное время в пути") is no
  longer tokenized as `PERSON` — Natasha's morph tagger tags it `PROPN`, so the
  POS filter cannot drop it; it is now in the NER stoplist.
- Split city names from `pdf2md`: it space-pads punctuation, so
  `Санкт-Петербург` arrives as `Санкт - Петербург` (and, inconsistently,
  `Санкт -Петербург`, where Natasha missed the second half entirely).
  `convert.py` now normalizes every space-padded hyphen to `" - "`, and
  `detect/ner.py` merges two adjacent same-category NER spans bridged only by a
  spaced hyphen — so the city is one `LOC` token and `Петербург` no longer
  leaks. A real `Русский - Родной` separator is unaffected (its halves are not
  the same entity category); genuine joined compounds (`кто-то`) are untouched.

### Changed
- The desktop `.app` no longer bundles `pdf2md`: `pdf-to-markdown` was removed
  from the Briefcase `requires`. Briefcase installs bundle deps cross-target
  with `--only-binary` for macOS 11.0 / cp312, and the docling stack
  (`docling-parse`, `deepsearch-glm`) has no wheels for that target, so
  `briefcase create` failed; bundling docling + torch would also bloat the
  distributable. The `.app` now ships lean; PDF support is installed on first
  use instead (ADR-0008 / UI-002). The CLI `[pdf]` extra is unchanged.
- QA-001: synthetic labelled corpus under `tests/corpus/` (fictional data only
  — «Рога и Копыта», invented checksum-valid IDs, reserved-TLD emails) and a
  precision/recall evaluation harness (`tests/evaluate_corpus.py`, run with
  `PYTHONPATH=src python -m tests.evaluate_corpus`). The harness scores
  `detect_all` per category and is a dev tool, not shipped in the wheel.
- DOC-001: `README.md` gained a "How it works" section listing the detection
  pipeline stages in order (input, conversion cleanup, regex, NER, consistency
  sweep, overlap resolution, replacement). Docs only.
- Dictionary content expansion (data-only, no code change): `dict_country_names`
  expanded from 3 entries to ~110 world countries (so `Индия`, `Германия`, … are
  no longer mistagged as `LOC`); `dict_tech_terms` substantially enlarged —
  languages, markup/formats, build/CI, IDEs, testing, frameworks, data/ML,
  databases, infra, OS, protocols, API tools and a `methodologies` group
  (`Kanban`, `Scrum`, …), with well-known standalone company names deliberately
  excluded so real employers stay detected; `dict_org_forms` /
  `dict_org_abbreviations` gained ГУП/МУП/ФГУП/ФГБУ/ГБУ/МБУ/АНО/ТСЖ/ЖСК/СНТ/КФХ
  and their full spellings; `dict_document_grifs`, `dict_generic_nouns`,
  `dict_resume_section_headers` and `dict_url_tlds` topped up.
- New `dict_colloquial_words` stoplist — conversational filler words
  (interjections, discourse markers, slang: `Угу`, `Точно`, `Короче`, `Топ`,
  …) that Natasha NER mistags as PERSON/ORG on speech-to-text transcripts.
  Folded into `_STOPLIST_TERMS`; complements the NER-007 POS filter by also
  catching fillers the morph tagger labels `PROPN`. Does not cover ASR garbage
  (non-existent mis-transcribed words).
- DICT-001: every hand-curated exclusion dictionary and stoplist moved out of
  the detection modules into a dedicated `detect/dictionaries/` package — one
  `dict_<name>.json` resource per list (`dict_org_forms`,
  `dict_org_abbreviations`, `dict_url_tlds`, `dict_country_names`,
  `dict_document_grifs`, `dict_generic_nouns`, `dict_tech_terms`, and the
  document-type-named `dict_resume_section_headers`, `dict_resume_field_labels`,
  `dict_resume_skill_section_stems`). Each JSON file carries a `description`
  field (purpose + how to extend) and an `items` array (or grouped `groups`
  for the tech terms); the package's `load()` reads and caches them.
  `regex_rules.py` and `ner.py` load the data; composition logic
  (`_STOPLIST_TERMS`, the URL-TLD alternation) and all regex patterns stay in
  code. `_MONTH_NAMES` stays inline (a fixed universal list, not an open-ended
  exclusion dictionary). Pure refactor, no behaviour change.
- The deprecated-`pkg_resources` warning that pymorphy2 emits when the NER
  model loads is now suppressed, keeping the CLI's stderr output clean.
- ADDRESS label detection now requires a colon after the `адрес` label
  (word-boundary anchored, optional qualifier words allowed), so plural nouns
  like "адреса средств коммуникации" are no longer mistaken for an address.
  The structured `г. Город, ул. …` rule is unchanged.
- DOB detection is now label-anchored only: a date is tokenized as `DOB` only
  next to "дата рождения" / "д.р.". Bare dates (e.g. contract dates) are no
  longer caught — the unconditional any-date rule was removed. The anchored
  rule now also accepts the ISO `ГГГГ-ММ-ДД` format.
- A single input without `-o` now writes `<name>.anon.md` and
  `<name>.anon.map.json` next to the input file instead of printing to stdout.
  stdin (`-`) still writes to stdout.
- The CLI prints stage progress to stderr as work begins — `converting PDF…`
  then `detecting…` — with `[i/total]` numbering in batch mode.
  `batch.process_files` / `anonymize_file` gained an `on_stage` callback.

### Decisions
- ADR-0001: token-based reversible replacement with a side map file.
- ADR-0002: PDF support via the external `pdf2md` subprocess.
- ADR-0003: detection ordering — regex before NER.
- ADR-0004: desktop UI toolkit — Toga + Briefcase.
- ADR-0005: bundle `pdf2md` as an opt-in `[pdf]` extra — revises ADR-0002.
- ADR-0006: case normalization before NER — Title-case ALL-CAPS words so
  Natasha tags ALL-CAPS entities, instead of a regex rule per shape.
- ADR-0007: structural NER suppression for résumé skill sections — drop
  `ORG`/`LOC` inside skills/technologies/competencies sections instead of
  enumerating tool names in a stoplist.
- ADR-0008: the desktop `.app` does not bundle `pdf2md` — the docling backend
  is installed on first PDF use into a user-writable dir — revises ADR-0005.
- ADR-0010: `pdf2md` batch driver — one subprocess per PDF group, JSON
  manifest stream over stdout, per-file Markdown in a temp directory.

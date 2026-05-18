# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added
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

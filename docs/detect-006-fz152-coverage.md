# DETECT-006 — ФЗ-152 PII coverage audit

Triaged coverage of the ФЗ-152 «О персональных данных» PII enumeration in
`../pdf c привт/TZ.md:80-146` against the current detector set in
`src/anonymizer/detect/regex_rules.py`, `src/anonymizer/detect/ner.py`, and
the structural stoplists. No detection code is changed in this ticket; every
`missing` / `partial` row spawns a dedicated `DETECT-*` backlog task.

Verdict legend: **covered** — detection rule already exists with positive
test evidence; **partial** — detector exists but is narrower than the ФЗ-152
row (e.g. label-only, no checksum, weak guard); **missing** — no detector
exists today; **out-of-scope** — the row describes data that cannot appear
as Markdown text (image/binary biometric data).

## Audit checklist

### 1. Паспорт: код подразделения / орган выдачи / дата выдачи

| Field | Verdict | Evidence |
| --- | --- | --- |
| Код подразделения (`XXX-XXX`) | covered | `PASSPORT_DEPT_CODE` rule, `src/anonymizer/detect/regex_rules.py:205-210` — `код подразделения[:\s]*(\d{3}-\d{3})`; exercised by the `Код подразделения 770-053` line in `tests/test_detect.py:27` via `test_every_category_detected` |
| Орган выдачи | covered | `PASSPORT_ISSUER` rule, `src/anonymizer/detect/regex_rules.py:211-216` — `(?:кем выдан|орган выдачи)[:\s]*([^\n]+)`; exercised by the `Кем выдан ОВД района Хамовники` line in `tests/test_detect.py:28` |
| Дата выдачи (label-anchored) | covered | `PASSPORT_ISSUE_DATE` rule, `src/anonymizer/detect/regex_rules.py:199-204` — `(?:дата выдачи)[:\s]*(\d{2}[./]\d{2}[./]\d{4})`; exercised by the `Дата выдачи 20.03.2015` line in `tests/test_detect.py:26` |

No new task — all three fields detected.

### 2. Биометрия (surface-text mentions only)

| Field | Verdict | Evidence |
| --- | --- | --- |
| «отпечаток пальца», «голосовой отпечаток», «ДНК», «радужная оболочка» | missing | No rule, no NER category, no stoplist entry — `rg -i "отпеч\|голосовой\|ДНК\|радужн" src/anonymizer/` returns nothing. Whether these surface-text mentions warrant a dedicated detector is a product decision: they are descriptors, not personal identifiers — only the **fact** that a document references biometric data is sensitive. |
| Image / binary biometric data (fingerprint scans, DNA sequences) | out-of-scope | A Markdown anonymizer operates on text strings only; image and binary biometric payloads do not survive the `pdf2md` text-extraction stage. This is text-only by construction. |

New task: **DETECT-009** (biometric surface-text mentions — optional / opt-in).

### 3. Медицинские данные

| Field | Verdict | Evidence |
| --- | --- | --- |
| Номер полиса ОМС (16 digits) | missing | No `ОМС`/`полис` rule. The 16-digit run would only be picked up by `CARD` (`src/anonymizer/detect/regex_rules.py:290-295`), and only when the Luhn checksum happens to pass — real OMS numbers do not follow Luhn, so they slip through. |
| Полис ДМС | missing | No `ДМС` rule; the policy number format varies, so a label-anchored rule is the realistic approach. |
| Диагноз / код МКБ-10 | missing | No rule. Free-text diagnoses are caught by no detector; МКБ-10 codes (`A00.0` … `Z99.9`) have no rule. |
| История болезни | missing | No rule. Treated as free text. |

New task: **DETECT-010** (label-anchored medical-data detection — ОМС / ДМС / диагноз / МКБ-10 / история болезни).

### 4. Финансовая периферия

| Field | Verdict | Evidence |
| --- | --- | --- |
| БИК (9 digits, label-anchored) | partial | `BIK` rule, `src/anonymizer/detect/regex_rules.py:255` — `БИК[:\s]*(\d{9})(?!\d)`. Label-anchored, no checksum. A non-BIK 9-digit number after a `БИК` label would be tokenised; a bare BIK in free text is missed. ФЗ-152 row mentions "checksum" as the desired guard. |
| Номер банковского счёта (20 digits) | covered | `ACCOUNT_LABELED` (`src/anonymizer/detect/regex_rules.py:280-288`) plus `ACCOUNT_BARE` (`src/anonymizer/detect/regex_rules.py:289`) — labels include `расчётный счёт`, `р/сч`, `р/с`, `к/с`, `счёт`, `сч.`; bare 20-digit runs always match. Exercised by `tests/corpus/02-company.json`. |
| Корреспондентский счёт (20 digits, label-anchored) | covered | `ACCOUNT_LABELED` label list contains `к/с` (the canonical short form for «корр. счёт»); the longer `корреспондентский счёт` ends with `счёт`, which the same label list also matches. Confirmed by ad-hoc regex check in DETECT-006 worktree. |
| КПП (already covered — confirm) | partial | `KPP` rule, `src/anonymizer/detect/regex_rules.py:254` — `КПП[:\s]*(\d{9})(?!\d)`. Label-anchored, no checksum, no bare-rule variant. Consistent with how БИК is handled today; both share the same "9-digit no-checksum" caveat. |

New task: **DETECT-011** (БИК checksum validator, mirroring the DETECT-001 pattern for INN/OGRN/OGRNIP/SNILS). КПП has no published checksum — it stays label-only.

### 5. Семейное положение и родственники

| Field | Verdict | Evidence |
| --- | --- | --- |
| «супруг(а)», «дети», «родители» (label-anchored) | missing | No rule, no stoplist entry. These are common nouns Natasha does not flag as PII; PRD lists «семейное положение» as an in-scope ФЗ-152 row. The row itself notes the detection is **optional**. |

New task: **DETECT-012** (optional label-anchored family-relation detection, off by default — opt-in via `--family-relations`).

### 6. Место работы / должность / образование как PII категории

| Field | Verdict | Evidence |
| --- | --- | --- |
| Место работы (organisation name) | partial | Caught when the employer name is a recognisable ORG via Natasha NER (`src/anonymizer/detect/ner.py:_TYPE_TO_CATEGORY`) — see the `tests/corpus/baseline_metrics.json` `ORG` row. Job-title noun itself («директор», «инженер») is **not** caught — Natasha does not emit it as an entity. PRD §"Scope (in)" explicitly delegates ORG detection to Natasha. |
| Должность (job title) | missing | No rule; common nouns are not NER targets. PRD intent: maximum removal. |
| Образование (учебное заведение / специальность) | partial | University name caught as ORG when Natasha recognises it. Specialty/qualification text («магистр», «инженер-программист») is a common noun — not caught. |

New task: **DETECT-013** (job titles, education qualifications, и т.п. — label-anchored only, optional / opt-in to keep precision).

### 7. Юридические адреса

| Field | Verdict | Evidence |
| --- | --- | --- |
| «юридический адрес», «фактический адрес» (legal-entity addresses) | covered | `ADDRESS_LABELED` rule, `src/anonymizer/detect/regex_rules.py:219-224` — `\bадрес\w*(?:\s+[А-Яа-яёЁ]+){0,2}\s*:\s*([^\n]+)`. The `\bадрес\w*` head matches the noun «адрес» (and «адреса», «адресу»), and `\b` is not anchored to the start of a line — verified empirically: `Юридический адрес: …` and `Фактический адрес: …` both produce an ADDRESS span. |

No new task — already covered.

## Spawned tasks

| New ID | Row | Verdict | One-line summary |
| --- | --- | --- | --- |
| DETECT-009 | Биометрия surface-text | missing | Optional label-list rule for biometric-data mentions |
| DETECT-010 | Медицинские данные | missing | Label-anchored ОМС / ДМС / диагноз / МКБ-10 / история болезни |
| DETECT-011 | БИК checksum | partial | Add BIK checksum validator (DETECT-001 pattern) |
| DETECT-012 | Семейное положение | missing | Optional label-anchored family-relation detection |
| DETECT-013 | Должность / образование | partial | Label-anchored job-title and education-qualification detection |

## Out-of-scope rationale

- Image / binary biometric data (raw fingerprint scans, DNA sequences, iris
  images) — never appears as Markdown text. `pdf2md` extracts text; image
  payloads are dropped at the conversion boundary.
- Photographs of people (`TZ.md:126`) — same reason as above; not text.

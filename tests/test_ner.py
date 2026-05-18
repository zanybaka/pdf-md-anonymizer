"""NER-001/NER-002: Natasha PERSON/ORG/LOC detection and post-filter."""

from anonymizer.api import Options, anonymize
from anonymizer.detect import detect_all
from anonymizer.detect.ner import (
    _get_stoplist,
    _lemma_key,
    _normalize_caps,
    _trim,
    detect,
)
from anonymizer.mapping import restore
from anonymizer.replace import Span

TEXT = "Иван Петров живёт в Москве и работает в компании Газпром."


def test_person_org_loc_detected_by_default():
    cats = {s.category for s in detect_all(TEXT, Options())}
    assert {"PERSON", "ORG", "LOC"} <= cats


def test_no_ner_org_suppresses_org():
    cats = {s.category for s in detect_all(TEXT, Options(ner_org=False))}
    assert "ORG" not in cats
    assert "PERSON" in cats


def test_no_ner_loc_suppresses_loc():
    cats = {s.category for s in detect_all(TEXT, Options(ner_loc=False))}
    assert "LOC" not in cats
    assert "PERSON" in cats


def test_regex_identifiers_not_relabeled_by_ner():
    text = "Иван Петров, ИНН 7707083893, почта ivan@example.ru"
    spans = detect_all(text, Options())
    inn = [s for s in spans if s.category == "INN"]
    assert inn and inn[0].value == "7707083893"
    for s in spans:
        if s.category in ("PERSON", "ORG", "LOC"):
            assert not (s.start < inn[0].end and inn[0].start < s.end)


def test_person_is_tokenized():
    result = anonymize(TEXT, Options())
    assert "Иван Петров" not in result.text
    assert any(t.startswith("{{PERSON_") for t in result.mapping)


def test_trim_clips_at_newline():
    raw = "ООО «Рога и Копыта»\n\n## Сводный отчёт"
    start, end, value = _trim(0, raw)
    assert value == "ООО «Рога и Копыта»"
    assert raw[start:end] == value


def test_trim_strips_leading_markdown_and_adjusts_offset():
    start, end, value = _trim(5, "## Газпром")
    assert value == "Газпром"
    assert (start, end) == (8, 15)


def test_trim_drops_empty_span():
    assert _trim(0, "## \n текст") is None


def test_stoplist_matches_declined_forms():
    stop = _get_stoplist()
    for term in ("Российская Федерация", "Российской Федерации", "РФ",
                 "УТВЕРЖДАЮ", "ООО",
                 "Общества  с  ограниченной  ответственностью"):
        assert _lemma_key(term) in stop
    assert _lemma_key("Газпром") not in stop


def test_stoplisted_term_not_tokenized():
    text = "Договор действует на всей территории Российской Федерации."
    result = anonymize(text, Options())
    assert "Российской Федерации" in result.text


def test_normalize_caps_is_length_preserving():
    text = "Подписал КРУГЛОВ ОЛЕГ от ООО АСТРАЛ-СОФТ, а И — союз."
    norm = _normalize_caps(text)
    assert len(norm) == len(text)
    assert "Круглов" in norm and "Астрал-Софт" in norm
    # Single-letter all-caps token (the conjunction "И") is left alone.
    assert " И " in norm


def test_allcaps_fio_detected_via_ner():
    text = "Документ заверил КРУГЛОВ ОЛЕГ АНАТОЛЬЕВИЧ лично."
    persons = [s for s in detect(text, Options()) if s.category == "PERSON"]
    assert persons
    span = persons[0]
    assert text[span.start:span.end] == span.value
    assert span.value == "КРУГЛОВ ОЛЕГ АНАТОЛЬЕВИЧ"


def test_allcaps_unquoted_org_detected_via_ner():
    text = "Исполнитель — ООО АСТРАЛ-СОФТ по договору."
    orgs = [s for s in detect(text, Options()) if s.category == "ORG"]
    assert orgs
    values = {s.value for s in orgs}
    assert any("АСТРАЛ-СОФТ" in v for v in values)
    for s in orgs:
        assert text[s.start:s.end] == s.value


def test_normal_case_ner_unchanged_and_quoted_org_detected():
    text = "Иван Петров работает в ООО «Ромашка» в Москве."
    spans = detect(text, Options())
    cats = {s.category for s in spans}
    assert {"PERSON", "LOC"} <= cats
    for s in spans:
        assert text[s.start:s.end] == s.value


def test_allcaps_ner_round_trip():
    text = "КРУГЛОВ ОЛЕГ АНАТОЛЬЕВИЧ из ООО АСТРАЛ-СОФТ подписал."
    result = anonymize(text, Options())
    assert restore(result.text, result.mapping) == text


# --- NER-004: POS filter, month names, section headers --------------------


def test_common_noun_not_tokenized_as_person():
    text = "Программист и Желательное направление развития."
    persons = [s for s in detect(text, Options()) if s.category == "PERSON"]
    assert not persons


def test_month_names_not_tokenized():
    text = "Опыт работы: Май 2020 — Декабрь 2022 годы."
    result = anonymize(text, Options())
    assert "Май" in result.text and "Декабрь" in result.text


def test_section_header_not_tokenized_as_org():
    text = "Образование высшее, профильное."
    orgs = [s for s in detect(text, Options()) if s.category == "ORG"]
    assert not any(s.value == "Образование" for s in orgs)


def test_real_fio_still_detected():
    persons = [s for s in detect("Иван Петров подписал акт.", Options())
               if s.category == "PERSON"]
    assert persons and persons[0].value == "Иван Петров"


def test_real_org_still_detected_after_ner004():
    orgs = [s for s in detect("Договор с ООО «Ромашка» подписан.", Options())
            if s.category == "ORG"]
    assert orgs


# --- NER-005: developer-tool stoplist -------------------------------------


def test_dev_tools_not_tokenized():
    text = ("Использовал Docker, Jenkins, Redux и Sonarqube, "
            "а также Gitlab CI ежедневно.")
    spans = detect(text, Options())
    values = {s.value for s in spans}
    for tool in ("Docker", "Jenkins", "Redux", "Sonarqube", "Gitlab CI"):
        assert tool not in values


def test_tech_stoplist_case_and_spacing_variants():
    from anonymizer.detect.ner import _TECH_KEYS, _tech_key

    assert _tech_key("DOCKER") in _TECH_KEYS
    assert _tech_key("Gitlab   CI") in _TECH_KEYS


def test_real_latin_company_still_detected():
    text = "Работал в Deutsche Bank и Aker Solutions много лет."
    orgs = [s for s in detect(text, Options()) if s.category == "ORG"]
    values = {s.value for s in orgs}
    assert "Deutsche Bank" in values or "Aker Solutions" in values


# --- Post-feedback: POS filter bounds + wider stoplist --------------------


def test_has_propn_ignores_tokens_outside_trimmed_range():
    from anonymizer.detect.ner import _has_propn

    class _Tok:
        def __init__(self, pos, start, stop):
            self.pos, self.start, self.stop = pos, start, stop

    class _Span:
        pass

    span = _Span()
    # Heading "Желательное" at [0,11) is a common noun; a real name sits past
    # a blank line at [13,24) and must not keep the heading-only span alive.
    span.tokens = [
        _Tok("ADJ", 0, 11), _Tok("PROPN", 13, 19), _Tok("PROPN", 20, 24),
    ]
    assert _has_propn(span, 0, 11) is False
    assert _has_propn(span, 13, 24) is True


def test_more_dev_tools_in_tech_stoplist():
    from anonymizer.detect.ner import _TECH_KEYS, _tech_key

    for term in ("Git", "TFS", "WASM", "WebWorkers", "MS Visual Studio",
                 "Testing Library", "Kotlyn", "Code Review", "Mentoring",
                 "Monorepos", "Production", "Migration Guides",
                 "C", "C++", "C#"):
        assert _tech_key(term) in _TECH_KEYS


def test_generic_nouns_in_stoplist():
    stop = _get_stoplist()
    assert _lemma_key("Банк") in stop
    assert _lemma_key("Вэб") in stop


def test_colloquial_words_in_stoplist():
    stop = _get_stoplist()
    for word in ("Угу", "Точно", "Короче", "Кстати", "Топ"):
        assert _lemma_key(word) in stop


# --- NER-006: structural suppression in résumé skill sections -------------


def test_skill_section_ranges_bounded_by_same_depth_header():
    from anonymizer.detect.ner import _skill_section_ranges

    text = (
        "# Резюме\n\n"
        "## Опыт работы\n\nработал пять лет\n\n"
        "## Ключевые навыки\n\n"
        "### Языки\n\nPython, Java\n\n"
        "## Образование\n\nуниверситет\n"
    )
    ranges = _skill_section_ranges(text)
    assert len(ranges) == 1
    lo, hi = ranges[0]
    # section starts at the skills header; a deeper subheader stays inside
    assert text[lo:].startswith("## Ключевые навыки")
    assert text.index("### Языки") < hi
    # and it ends at the next same-depth header
    assert text[hi:].startswith("## Образование")


def test_org_in_skill_section_dropped_employer_kept():
    # The same fictional employer is named in both sections: detected in the
    # experience section, suppressed inside the skills section.
    text = (
        "## Опыт работы\n\n"
        "Работал в компании «Рога и Копыта».\n\n"
        "## Технологии\n\n"
        "Использовал инструменты компании «Рога и Копыта».\n"
    )
    skill_start = text.index("## Технологии")
    spans = detect(text, Options())
    # the experience-section ORG mention survives
    orgs = [s for s in spans if s.category == "ORG"]
    assert any(s.start < skill_start for s in orgs)
    # no ORG/LOC span starts inside the skills section
    assert not any(
        s.category in ("ORG", "LOC") and s.start >= skill_start for s in spans
    )


def test_skill_section_suppression_round_trip():
    text = (
        "## Опыт работы\n\nКомпания «Рога и Копыта».\n\n"
        "## Навыки\n\nDocker, React, Redux.\n"
    )
    res = anonymize(text, Options())
    assert restore(res.text, res.mapping) == text


# --- Post-feedback: spaced-hyphen merge + Желательное field label ----------


def test_merge_hyphenated_joins_same_category_neighbours():
    from anonymizer.detect.ner import _merge_hyphenated

    text = "Санкт - Петербург"
    spans = [
        Span(0, 5, "LOC", "Санкт"),
        Span(8, 17, "LOC", "Петербург"),
    ]
    merged = _merge_hyphenated(text, spans)
    assert merged == [Span(0, 17, "LOC", "Санкт - Петербург")]


def test_merge_hyphenated_keeps_different_categories_apart():
    from anonymizer.detect.ner import _merge_hyphenated

    # A real "слово - слово" separator: the two halves differ in category, so
    # they are not merged.
    text = "Москва - PERSON"
    spans = [
        Span(0, 6, "LOC", "Москва"),
        Span(9, 15, "PERSON", "PERSON"),
    ]
    assert _merge_hyphenated(text, spans) == spans


def test_split_city_merged_into_one_loc_span():
    text = "Он живёт в городе Санкт - Петербург уже давно."
    loc = [s for s in detect(text, Options()) if s.category == "LOC"]
    assert any(s.value == "Санкт - Петербург" for s in loc)


def test_zhelatelnoe_field_label_not_detected_as_person():
    text = "Желательное время в пути до работы: не имеет значения."
    spans = detect(text, Options())
    assert not any(s.value == "Желательное" for s in spans)


# --- NER-007: POS filter extended to ORG/LOC ------------------------------

# A noisy transcript where Natasha mistags the adverb "Вокруг" as LOC.
_TRANSCRIPT = "Совещание провёл Иван Петров. Вокруг шумел лес, Вокруг было тихо."


def test_common_noun_loc_dropped_by_pos_filter():
    locs = [s for s in detect(_TRANSCRIPT, Options()) if s.category == "LOC"]
    assert not locs


def test_pos_filter_org_loc_can_be_disabled():
    locs = [s for s in detect(_TRANSCRIPT, Options(ner_pos_filter=False))
            if s.category == "LOC"]
    assert any(s.value == "Вокруг" for s in locs)


def test_real_org_and_city_survive_pos_filter():
    spans = detect("Встреча прошла в Москве с участием Газпром.", Options())
    assert any(s.category == "ORG" and "Газпром" in s.value for s in spans)
    assert any(s.category == "LOC" and s.value.startswith("Москв")
               for s in spans)


def test_ner007_round_trip():
    result = anonymize(_TRANSCRIPT, Options())
    assert restore(result.text, result.mapping) == _TRANSCRIPT

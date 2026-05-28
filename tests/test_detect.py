"""CORE-002: regex/dictionary detectors."""

import anonymizer.detect as detect_mod
from anonymizer.api import Options, anonymize
from anonymizer.categories import Category
from anonymizer.detect import _sweep, detect_all
from anonymizer.detect.regex_rules import detect
from anonymizer.mapping import restore
from anonymizer.replace import Span, replace_spans

SAMPLE = """\
Email: ivan@example.ru
Сайт: https://example.com/page
Телефон: +7 (495) 123-45-67
ИНН 7707083893
СНИЛС 112-233-445 95
ОГРН 1027700132195
ОГРНИП 304500116000157
КПП 770701001
БИК 044525225
Расчётный счёт 40702810900000012345
Карта 4111 1111 1111 1111
Дата рождения 12.05.1990
Почтовый индекс 101000
Адрес: г. Москва, ул. Ленина, д. 1, кв. 5
Паспорт 4509 123456
Дата выдачи 20.03.2015
Код подразделения 770-053
Кем выдан ОВД района Хамовники
IP 192.168.1.1
IPv6 2001:0db8:85a3:0000:0000:8a2e:0370:7334
api_key=SecretValue12345
Организация: ООО «Ромашка»
"""

EXPECTED_CATEGORIES = {
    "EMAIL",
    "URL",
    "PHONE",
    "INN",
    "SNILS",
    "OGRN",
    "OGRNIP",
    "KPP",
    "BIK",
    "ACCOUNT",
    "CARD",
    "DOB",
    "POSTAL_CODE",
    "ADDRESS",
    "PASSPORT",
    "IP",
    "SECRET",
    "ORG",
}


def test_every_category_detected():
    found = {s.category for s in detect_all(SAMPLE, Options())}
    missing = EXPECTED_CATEGORIES - found
    assert not missing, f"categories not detected: {sorted(missing)}"


def test_card_rejects_non_luhn():
    bad = "Карта 1234 5678 9012 3456"
    assert not [s for s in detect(bad) if s.category == "CARD"]
    good = "Карта 4111 1111 1111 1111"
    assert [s for s in detect(good) if s.category == "CARD"]


def test_dob_is_label_anchored_only():
    bare = "Договор заключён 04.09.2026 и 1997-03-06."
    assert not [s for s in detect(bare) if s.category == "DOB"]
    anchored = "Дата рождения 12.05.1990. Д.р. 1997-03-06."
    dob = {s.value for s in detect(anchored) if s.category == "DOB"}
    assert dob == {"12.05.1990", "1997-03-06"}


def test_address_label_requires_colon():
    fp = "адреса средств коммуникации; адреса, телефоны и сведения"
    assert not [s for s in detect(fp) if s.category == "ADDRESS"]
    anchored = "Адрес регистрации: г. Тверь, ул. Мира, д. 5"
    assert [s for s in detect(anchored) if s.category == "ADDRESS"]


def test_detection_spans_do_not_overlap():
    spans = sorted(detect_all(SAMPLE, Options()), key=lambda s: s.start)
    for a, b in zip(spans, spans[1:], strict=False):
        assert a.end <= b.start


def test_sweep_propagates_value_and_reuses_one_token():
    text = "Рога и Копыта открыли офис. Позже Рога и Копыта закрылись."
    detected = [Span(0, 13, "ORG", "Рога и Копыта")]
    spans = detected + _sweep(text, detected)
    result = replace_spans(text, spans)
    assert "Рога и Копыта" not in result.text
    assert list(result.mapping) == ["{{ORG_1}}"]
    assert restore(result.text, result.mapping) == text


def test_sweep_respects_word_boundary():
    text = "РИК — это компания. Слово ПРИКАЗ не считается."
    assert _sweep(text, [Span(0, 3, "ORG", "РИК")]) == []


def test_consistency_sweep_can_be_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(detect_mod, "_sweep", lambda *a: calls.append(1) or [])
    detect_all("Иван Петров подписал.", Options(consistency_sweep=False))
    assert not calls
    detect_all("Иван Петров подписал.", Options())
    assert calls


def test_legal_forms_abbreviated_and_full():
    abbreviated = [
        "ООО",
        "АО",
        "ПАО",
        "ЗАО",
        "ОАО",
        "ИП",
        "НПО",
        "НКО",
        "ИЧП",
        "ТОО",
        "ОП",
        "ФГУП",
        "ФГБУ",
        "ГУП",
        "МУП",
        "ГБУ",
        "МБУ",
        "АНО",
        "ТСЖ",
        "ЖСК",
        "СНТ",
        "КФХ",
    ]
    full = [
        "Общество с ограниченной ответственностью",
        "Акционерное общество",
        "Публичное акционерное общество",
        "Закрытое акционерное общество",
        "Открытое акционерное общество",
        "Индивидуальный предприниматель",
        "Научно-производственное объединение",
        "Некоммерческая организация",
        "Индивидуальное частное предприятие",
        "Товарищество с ограниченной ответственностью",
        "Обособленное подразделение",
        "Федеральное государственное унитарное предприятие",
        "Государственное унитарное предприятие",
        "Муниципальное унитарное предприятие",
        "Автономная некоммерческая организация",
        "Государственное бюджетное учреждение",
        "Товарищество собственников жилья",
        "Жилищно-строительный кооператив",
        "Производственный кооператив",
    ]
    for form in abbreviated + full:
        text = f"Компания {form} «Тест» работает."
        orgs = [s for s in detect(text) if s.category == "ORG"]
        assert orgs, f"legal form not detected: {form}"


def test_allcaps_fio_with_patronymic_detected():
    text = "Подписал КРУГЛОВ ОЛЕГ АНАТОЛЬЕВИЧ"
    persons = [s for s in detect(text) if s.category == "PERSON"]
    assert [s.value for s in persons] == ["КРУГЛОВ ОЛЕГ АНАТОЛЬЕВИЧ"]


def test_normal_case_fio_with_patronymic_detected():
    text = "Документ подписал Круглов Олег Анатольевич лично."
    persons = [s for s in detect(text) if s.category == "PERSON"]
    assert [s.value for s in persons] == ["Круглов Олег Анатольевич"]


def test_word_triple_without_patronymic_not_matched():
    text = "Северный Ледовитый Океан омывает берега."
    assert not [s for s in detect(text) if s.category == "PERSON"]


def test_certificate_serial_detected_as_secret():
    text = "Сертификат №0262948600F2B281BC43ECDADC4C5F4E5B действителен."
    secrets = [s for s in detect(text) if s.category == "SECRET"]
    assert "0262948600F2B281BC43ECDADC4C5F4E5B" in {s.value for s in secrets}


def test_signature_block_dates_remain_undetected():
    text = "Срок действия: с 12.03.2024 по 12.06.2025. Время подписи 20.03.2015."
    spans = detect(text)
    assert not [s for s in spans if s.category == "DOB"]


def test_core005_round_trip():
    text = "Подписал КРУГЛОВ ОЛЕГ АНАТОЛЬЕВИЧ\nСертификат №0262948600F2B281BC43ECDADC4C5F4E5B"
    result = anonymize(text, Options())
    assert restore(result.text, result.mapping) == text


# --- DETECT-005: context-anchored single surname in signature blocks -------


def test_detect005_ukep_label_captures_allcaps_surname():
    text = "УКЭП: КРУГЛОВ"
    persons = [s for s in detect(text) if s.category == "PERSON"]
    assert [s.value for s in persons] == ["КРУГЛОВ"]
    # Label itself stays verbatim — only the captured group is the span.
    span = persons[0]
    assert text[span.start : span.end] == "КРУГЛОВ"
    assert text[: span.start].endswith(": ")


def test_detect005_signature_label_captures_normalcase_surname():
    text = "Подписант: Иванов"
    persons = [s for s in detect(text) if s.category == "PERSON"]
    assert [s.value for s in persons] == ["Иванов"]


def test_detect005_emdash_separator_captures_surname():
    text = "Подпись — Петрова"
    persons = [s for s in detect(text) if s.category == "PERSON"]
    assert [s.value for s in persons] == ["Петрова"]


def test_detect005_full_fio_after_label_wins_over_single_surname():
    # CORE-005 patronymic-triple rule must win the overlap: the full ФИО is the
    # longer span, so _resolve in detect_all keeps it instead of just the surname.
    text = "подписант: ИВАНОВ ИВАН ИВАНОВИЧ"
    persons = [s for s in detect_all(text, Options()) if s.category == "PERSON"]
    assert [s.value for s in persons] == ["ИВАНОВ ИВАН ИВАНОВИЧ"]


def test_detect005_non_signature_label_not_matched():
    text = "Город: Москва"
    assert not [s for s in detect(text) if s.category == "PERSON"]


def test_detect005_two_letter_token_after_label_not_matched():
    text = "Подпись: АБ"
    assert not [s for s in detect(text) if s.category == "PERSON"]


def test_detect005_round_trip():
    text = "УКЭП: КРУГЛОВ\nПодписант: Иванов\nПодпись — Петрова"
    result = anonymize(text, Options())
    assert restore(result.text, result.mapping) == text


def test_anonymize_produces_tokens_and_map():
    result = anonymize(SAMPLE, Options())
    assert "ivan@example.ru" not in result.text
    assert "{{EMAIL_1}}" in result.text
    assert result.mapping["{{EMAIL_1}}"] == "ivan@example.ru"


# --- Post-feedback: textual DOB + scheme-less URLs -------------------------


def test_dob_textual_month_and_rodilsya_anchor():
    text = "Мужчина, 43 года, родился 16 января 1983 года."
    dob = [s for s in detect(text) if s.category == "DOB"]
    assert dob and dob[0].value == "16 января 1983"
    # "родилась" anchor too
    fem = "Она родилась 2 мая 1990 в этом городе."
    assert [s for s in detect(fem) if s.category == "DOB"]


def test_dob_age_parens_format():
    # English-locale HH.ru export: "26 years (November 17, 1999)"
    text = "26 years (November 17, 1999), Мужской gender"
    dob = [s for s in detect(text) if s.category == "DOB"]
    assert dob and dob[0].value == "November 17, 1999"
    # Russian age with Russian month name
    text_ru = "26 лет (17 ноября 1999), Мужской"
    dob_ru = [s for s in detect(text_ru) if s.category == "DOB"]
    assert dob_ru and dob_ru[0].value == "17 ноября 1999"
    # Russian age with numeric date
    text_num = "26 лет (17.11.1999), Мужской"
    dob_num = [s for s in detect(text_num) if s.category == "DOB"]
    assert dob_num and dob_num[0].value == "17.11.1999"
    # Bare date without age anchor must NOT match
    bare = "November 17, 1999"
    assert not [s for s in detect(bare) if s.category == "DOB"]


def test_url_www_host_and_bare_domain():
    bare = [s.value for s in detect("сайт компании unicum.ru сейчас") if s.category == "URL"]
    assert bare == ["unicum.ru"]
    # markdown link: the visible text has no scheme, the target does — both
    # halves are tokenized so neither leaks.
    link = "[www.site.com/x](https://www.site.com/x)"
    urls = {s.value for s in detect(link) if s.category == "URL"}
    assert "www.site.com/x" in urls
    assert "https://www.site.com/x" in urls


def test_url_does_not_match_dotted_dev_tool_names():
    # "js"/"io" are not URL TLDs, so library names are not mistaken for URLs.
    spans = detect("Используем Node.js и Socket.io в проекте.")
    assert not [s for s in spans if s.category == "URL"]


# --- DETECT-001: control-digit validation ----------------------------------


def test_inn_control_digit_validation():
    # 10-digit (legal entity) and 12-digit (individual) INN.
    assert [s for s in detect("ИНН 7707083893") if s.category == "INN"]
    assert not [s for s in detect("ИНН 7707083894") if s.category == "INN"]
    assert [s for s in detect("ИНН 500100123426") if s.category == "INN"]
    assert not [s for s in detect("ИНН 500100123427") if s.category == "INN"]


def test_ogrn_control_digit_validation():
    assert [s for s in detect("ОГРН 1027700132195") if s.category == "OGRN"]
    assert not [s for s in detect("ОГРН 1027700132196") if s.category == "OGRN"]


def test_ogrnip_control_digit_validation():
    assert [s for s in detect("ОГРНИП 304500116000157") if s.category == "OGRNIP"]
    assert not [s for s in detect("ОГРНИП 304500116000158") if s.category == "OGRNIP"]


def test_snils_control_digit_validation():
    assert [s for s in detect("СНИЛС 112-233-445 95") if s.category == "SNILS"]
    assert not [s for s in detect("СНИЛС 112-233-445 96") if s.category == "SNILS"]


def test_long_numeric_not_tokenized_as_ogrn():
    # A 13-digit code that fails the OGRN checksum is no longer mis-tokenized.
    text = "Код заказа 1111111111111 в смете."
    assert not [s for s in detect(text) if s.category in ("OGRN", "OGRNIP")]


# --- DETECT-002: bare INN guarded by the checksum --------------------------


def test_bare_inn_detected_when_checksum_valid():
    inn = [s for s in detect("Контрагент 7707083893 в реестре.") if s.category == "INN"]
    assert inn and inn[0].value == "7707083893"


def test_bare_invalid_inn_not_detected():
    assert not [s for s in detect("Номер 7707083894 в документе.") if s.category == "INN"]
    assert not [s for s in detect("Код 500100123427 здесь.") if s.category == "INN"]


def test_bare_ogrn_not_relabeled_as_inn():
    spans = detect("Запись 1027700132195 в реестре.")
    assert [s for s in spans if s.category == "OGRN"]
    assert not [s for s in spans if s.category == "INN"]


def test_detect_checksum_round_trip():
    text = "ИНН 7707083893, ОГРН 1027700132195, бар 7707083893 ещё."
    result = anonymize(text, Options())
    assert restore(result.text, result.mapping) == text


# --- DETECT-004: @-style nickname mentions ---------------------------------


def test_nickname_simple_handles():
    for handle in ("@vasily", "@john_doe", "@user-name"):
        spans = [s for s in detect(f"Написал {handle} сегодня.") if s.category == "NICKNAME"]
        assert spans and spans[0].value == handle, f"expected NICKNAME for {handle}"


def test_email_wins_over_nickname():
    # Raw detect returns both; overlap resolution in detect_all keeps only EMAIL.
    spans = detect_all("vasily@example.com", Options())
    assert [s for s in spans if s.category == "EMAIL"]
    assert not [s for s in spans if s.category == "NICKNAME"]


def test_bare_at_sign_not_matched():
    assert not [s for s in detect("price @ 100 rub") if s.category == "NICKNAME"]


def test_at_digit_not_matched():
    assert not [s for s in detect("версия @123") if s.category == "NICKNAME"]


def test_consecutive_mentions_both_caught():
    spans = [s for s in detect("@vasi@vasi") if s.category == "NICKNAME"]
    assert [s.value for s in spans] == ["@vasi", "@vasi"]


def test_nickname_round_trip():
    text = "Связаться: @vasily или @john_doe."
    result = anonymize(text, Options())
    assert "@vasily" not in result.text
    assert "@john_doe" not in result.text
    assert restore(result.text, result.mapping) == text


# --- DETECT-007: brand short-name propagation ------------------------------


def test_brand_propagation_share_one_token_across_legal_form_and_bare_repeats():
    text = (
        "ООО «Альфа-Бета» открыло офис. "
        "Альфа-Бета поставляет товар. "
        "Заказ от Альфа-Бета принят. "
        "Альфа-Бета закрылась."
    )
    result = anonymize(text, Options())
    # No raw mention of the short name leaks anywhere in the tokenized output.
    assert "Альфа-Бета" not in result.text
    # All four occurrences share one ORG token; the legal-form line surfaces it
    # inside the literal "ООО «...»" framing so the round-trip stays exact.
    org_tokens = {t for t in result.mapping if t.startswith("{{ORG_")}
    assert org_tokens == {"{{ORG_1}}"}
    assert result.mapping["{{ORG_1}}"] == "Альфа-Бета"
    assert result.text.count("{{ORG_1}}") == 4
    assert "ООО «{{ORG_1}}»" in result.text
    assert restore(result.text, result.mapping) == text


def test_brand_propagation_does_not_double_tokenize_the_inner_name():
    # The legal-form line itself produces exactly one ORG span (the inner name),
    # not a parent + nested span pair.
    text = "ООО «Альфа-Бета» работает в Москве."
    spans = [s for s in detect_all(text, Options()) if s.category == "ORG"]
    assert [s.value for s in spans] == ["Альфа-Бета"]


def test_brand_propagation_skips_stoplisted_inner_name():
    # "Россия" is a country (stoplist entry); the legal-form line stays
    # detected as ORG, but the country word is not propagated to its bare
    # mentions elsewhere in the document.
    text = "ООО «Россия» зарегистрировано. Договор действует на территории Россия."
    spans = [s for s in detect_all(text, Options()) if s.category == "ORG"]
    # The legal-form line is still an ORG match — registered name shape stays
    # tokenized — but the bare "Россия" later is not added as ORG.
    values = [s.value for s in spans]
    assert "Россия" not in values
    # The legal-form span keeps its full value (no narrowing for stoplisted
    # inner names), so the original behaviour is preserved.
    assert any(v.startswith("ООО") and "Россия" in v for v in values)


def test_brand_propagation_can_be_disabled():
    text = "ООО «Альфа-Бета» открыло офис. Альфа-Бета поставляет товар."
    # Default behaviour (brand_propagation=True): the inner short-name is
    # mined and propagated, so the legal-form line and the bare repeat share
    # one ORG token.
    on = anonymize(text, Options())
    assert on.text.count("{{ORG_1}}") == 2
    assert on.mapping["{{ORG_1}}"] == "Альфа-Бета"
    # With propagation off: the legal-form line still tokenizes via the regex
    # ORG rule (full value), but the bare repeat is *not* re-detected as ORG
    # — restoring the previous behaviour.
    off = anonymize(text, Options(brand_propagation=False))
    assert "ООО «{{ORG_1}}»" not in off.text  # no narrowing
    assert any(v == "ООО «Альфа-Бета»" for v in off.mapping.values())
    # No ORG token covers the bare "Альфа-Бета" mention.
    bare_offset = text.index("Альфа-Бета поставляет")
    legal_form_tokens = [t for t, v in off.mapping.items() if v == "ООО «Альфа-Бета»"]
    # Either the bare repeat is still in the text, or it was tagged in a
    # non-ORG category (LOC/PERSON) — but it does not reuse the legal-form
    # ORG token, which is the propagation-specific behaviour.
    assert not any(
        off.text[bare_offset : bare_offset + 16].startswith(t) for t in legal_form_tokens
    )


def test_brand_propagation_respects_word_boundary():
    # A 3-letter inner name ("РИК") must not match inside an ordinary Russian
    # word containing the same letters in lowercase ("литерик" — a fictitious
    # compound chosen to avoid NER tagging it as anything in particular).
    text = "ООО «РИК» подписало. Слово литерик не считается. РИК отчитался."
    result = anonymize(text, Options())
    assert "литерик" in result.text  # bare lowercase substring untouched
    # Two ORG occurrences (legal-form line + the bare repeat) share one token.
    assert result.text.count("{{ORG_1}}") == 2
    assert result.mapping["{{ORG_1}}"] == "РИК"
    assert restore(result.text, result.mapping) == text


def test_brand_propagation_round_trip_exact():
    text = (
        "ООО «Альфа-Бета» (исполнитель). "
        "Альфа-Бета поставляет ПО. "
        "Реквизиты Альфа-Бета приведены ниже."
    )
    result = anonymize(text, Options())
    assert restore(result.text, result.mapping) == text


def test_extract_inner_org_name_handles_common_shapes():
    from anonymizer.detect.regex_rules import extract_inner_org_name

    assert extract_inner_org_name("ООО «Альфа-Бета»") == "Альфа-Бета"
    assert extract_inner_org_name("ООО АСТРАЛ-СОФТ") == "АСТРАЛ-СОФТ"
    assert extract_inner_org_name("Общество с ограниченной ответственностью «Тест»") == "Тест"
    # No leading legal form: not propagatable.
    assert extract_inner_org_name("Просто текст") is None
    # Leading legal form only: nothing to propagate.
    assert extract_inner_org_name("ООО") is None
    # Trailing legal-form short word is stripped.
    assert extract_inner_org_name("ООО Альфа НПО") == "Альфа"


# --- DETECT-008: document-declared alias propagation ----------------------


def test_alias_org_propagates_to_later_bare_mentions():
    # «(далее — Альфа)» declared right after «ООО «Альфа-Бета»» turns every
    # later bare «Альфа» into an ORG token. The legal-form line tokenizes as
    # ORG via brand narrowing; the alias declaration plus two later «Альфа»
    # mentions share one ORG token of their own (different value, same
    # category — both are ORG).
    text = (
        "ООО «Альфа-Бета» (далее — Альфа). Договор. Альфа поставляет товар. Альфа выполнит работу."
    )
    result = anonymize(text, Options())
    # The legal-form line and both later «Альфа» mentions are ORG-tokenized.
    assert "Альфа-Бета" not in result.text
    assert "Альфа" not in result.text
    # Two ORG tokens: one for the narrowed brand, one shared across all
    # «Альфа» mentions (declaration site + later bare repeats).
    org_tokens = {t for t in result.mapping if t.startswith("{{ORG_")}
    assert org_tokens == {"{{ORG_1}}", "{{ORG_2}}"}
    assert result.mapping["{{ORG_1}}"] == "Альфа-Бета"
    assert result.mapping["{{ORG_2}}"] == "Альфа"
    # Three occurrences of the alias token: declaration site + two later
    # mentions.
    assert result.text.count("{{ORG_2}}") == 3
    assert restore(result.text, result.mapping) == text


def test_alias_person_overrides_natasha_org_tagging():
    # Natasha tags «Заказчик» as ORG on its own; the «(далее именуемый
    # Заказчик)» declaration after «Иванов И.И.» overrides that tag — every
    # «Заказчик» mention is PERSON because the parent is PERSON.
    text = (
        "Иванов И.И. (далее именуемый Заказчик) подписал договор. "
        "Заказчик обязуется оплатить услуги."
    )
    result = anonymize(text, Options())
    person_tokens = {t for t in result.mapping if t.startswith("{{PERSON_")}
    # Two PERSON tokens: «Иванов И.И.» and «Заказчик» — different values,
    # both correctly categorised as PERSON.
    assert person_tokens == {"{{PERSON_1}}", "{{PERSON_2}}"}
    assert result.mapping["{{PERSON_1}}"] == "Иванов И.И."
    assert result.mapping["{{PERSON_2}}"] == "Заказчик"
    # «Заказчик» was *not* tokenised as ORG anywhere.
    org_tokens = {v for t, v in result.mapping.items() if t.startswith("{{ORG_")}
    assert "Заказчик" not in org_tokens
    assert restore(result.text, result.mapping) == text


def test_alias_without_parent_is_not_propagated_by_alias_pass():
    # An alias declaration with no detected span in the preceding ~10
    # non-whitespace characters has no parent category to assign — the alias
    # pass produces no new spans. (Natasha may still tag the alias word
    # independently; this test asserts only that the alias pass itself does
    # not synthesise an orphan span.)
    from anonymizer.detect import _alias_propagate

    text = "Подписан некий документ (далее по тексту — Сторона-1). Сторона-1 обязуется."
    # No detected spans precede the parenthesis at all — orphan case.
    survivors, alias_extra = _alias_propagate(text, [])
    assert alias_extra == []
    assert survivors == []


def test_alias_stoplisted_value_is_not_propagated():
    # «Россия» is on the NER stoplist (country name); even when it appears as
    # an alias, it is not promoted to a propagation span. The legal-form line
    # still tokenizes the country-named ORG via the regex ORG rule (DETECT-007
    # leaves stoplisted inner names un-narrowed), but no extra ORG span is
    # added for «Россия» mentions elsewhere in the text.
    text = "ООО «Регион-Сервис» (далее — Россия). Россия зарегистрирована."
    spans = detect_all(text, Options())
    # Find ORG spans whose value is exactly «Россия» (alias-only spans). The
    # alias pass would have added one if «Россия» were not stoplisted.
    russia_orgs = [s for s in spans if s.category == "ORG" and s.value == "Россия"]
    assert russia_orgs == []


def test_alias_short_text_is_not_propagated():
    # An alias text shorter than 3 characters is filtered out — it would
    # otherwise match inside ordinary words during the consistency sweep.
    from anonymizer.detect import _alias_propagate
    from anonymizer.replace import Span

    text = "Иванов Иван Иванович (далее — а) подписал документ."
    parent = Span(0, 20, Category.PERSON, "Иванов Иван Иванович")
    survivors, alias_extra = _alias_propagate(text, [parent])
    # «а» is too short — no alias-extra spans even though a valid parent
    # precedes the parenthesis.
    assert alias_extra == []
    assert survivors == [parent]


def test_alias_placeholder_text_is_not_propagated():
    # Aliases enclosing «{{…}}» placeholder markers (e.g. when running over
    # already-anonymised text) are filtered out so generated tokens do not
    # collide.
    from anonymizer.detect import _alias_propagate
    from anonymizer.replace import Span

    text = "Иванов Иван Иванович (далее — {{PERSON_1}}). Документ."
    parent = Span(0, 20, Category.PERSON, "Иванов Иван Иванович")
    survivors, alias_extra = _alias_propagate(text, [parent])
    assert alias_extra == []
    assert survivors == [parent]


def test_alias_round_trip_exact_with_multiple_declarations():
    # A two-party contract declaring both an ORG alias and a PERSON alias
    # tokenises every later use under the parent's category and restores the
    # original text exactly.
    text = (
        "ООО «Альфа-Бета» (далее — Альфа) и Иванов Иван Иванович "
        "(далее именуемый Заказчик) заключили договор. "
        "Альфа поставит товар. Заказчик оплатит услуги."
    )
    result = anonymize(text, Options())
    assert restore(result.text, result.mapping) == text


def test_alias_re_capture_shapes():
    # Sanity check on the regex itself — the three documented declaration
    # shapes all match and capture the alias text in group 1.
    from anonymizer.detect.regex_rules import _ALIAS_RE

    cases = [
        ("(далее — Альфа)", "Альфа"),
        ("(далее именуемый Заказчик)", "Заказчик"),
        ("(далее по тексту — Сторона-1)", "Сторона-1"),
        ("(далее именуемая Сторона)", "Сторона"),
    ]
    for text, expected in cases:
        match = _ALIAS_RE.search(text)
        assert match is not None, f"regex did not match {text!r}"
        assert match.group(1).strip() == expected


# --- DETECT-009: opt-in biometric-mention detection ---------------------


_BIOMETRIC_SAMPLE = (
    "Перечень: отпечаток пальца, голосовой отпечаток, ДНК, "
    "радужная оболочка глаза, биометрические данные."
)


def test_biometric_mentions_off_by_default_keeps_descriptors_untokenized():
    # The default Options() leaves biometric_mentions=False, so the regex
    # detector emits zero BIOMETRIC spans for the same input it tokenises
    # when the flag is on. This is the DoD invariant — "without the flag
    # the same input passes through unchanged" with respect to the
    # BIOMETRIC category.
    spans = detect(_BIOMETRIC_SAMPLE, Options())
    assert not [s for s in spans if s.category == Category.BIOMETRIC]
    # The candidate phrases themselves remain in the text — the regex never
    # claimed them, so anonymize() (which only replaces detected spans) cannot
    # have rewritten any biometric substring.
    result = anonymize(_BIOMETRIC_SAMPLE, Options())
    for needle in (
        "отпечаток пальца",
        "голосовой отпечаток",
        "радужная оболочка глаза",
        "биометрические данные",
    ):
        assert needle in result.text, f"{needle} unexpectedly tokenized"
    # No BIOMETRIC token leaked into the mapping.
    assert not [t for t in result.mapping if t.startswith("{{BIOMETRIC_")]


def test_biometric_mentions_flag_tokenizes_each_descriptor_once():
    # DoD-required input: each of «отпечаток пальца», «голосовой отпечаток»,
    # «ДНК», «радужная оболочка глаза» is tokenized once with the flag on.
    text = (
        "Сотрудник предоставил отпечаток пальца, голосовой отпечаток, "
        "образец ДНК и снимок радужная оболочка глаза."
    )
    result = anonymize(text, Options(biometric_mentions=True))
    # No raw biometric descriptor leaks anywhere in the tokenized output.
    for needle in (
        "отпечаток пальца",
        "голосовой отпечаток",
        "ДНК",
        "радужная оболочка глаза",
    ):
        assert needle not in result.text, f"{needle} leaked"
    # Each descriptor produced its own BIOMETRIC token (four distinct values).
    bio_tokens = {t for t in result.mapping if t.startswith("{{BIOMETRIC_")}
    assert bio_tokens == {
        "{{BIOMETRIC_1}}",
        "{{BIOMETRIC_2}}",
        "{{BIOMETRIC_3}}",
        "{{BIOMETRIC_4}}",
    }
    # Each token appears exactly once in the tokenized output.
    for tok in bio_tokens:
        assert result.text.count(tok) == 1
    # Round-trip is exact.
    assert restore(result.text, result.mapping) == text


def test_biometric_mentions_case_insensitive_and_word_bounded():
    # Title-case forms still match; a Cyrillic stem inside a longer word does
    # NOT match (word boundary on Cyrillic letters).
    text = "Биометрические данные собраны. отпечаток пальцами не считается."
    result = anonymize(text, Options(biometric_mentions=True))
    # "Биометрические данные" is tokenized (case-insensitive match).
    assert "Биометрические данные" not in result.text
    # "пальцами" is not "пальца" — the trailing Cyrillic letter blocks the
    # match, so "отпечаток пальцами" stays in the output unchanged.
    assert "отпечаток пальцами" in result.text


def test_biometric_mentions_qa001_corpus_invariant_when_off():
    # When the flag is off, regex_rules.detect() must not return any
    # BIOMETRIC span even if the surface text happens to contain a candidate
    # phrase — confirming the QA-001 corpus precision/recall is bit-identical
    # to the pre-DETECT-009 baseline whenever the opt-in stays disabled.
    text = "Биометрические данные не упоминаются как PII в данном тесте."
    spans_off = detect(text, Options())
    spans_default = detect(text, None)
    assert all(s.category != Category.BIOMETRIC for s in spans_off)
    assert all(s.category != Category.BIOMETRIC for s in spans_default)


def test_biometric_mentions_round_trip_exact():
    text = (
        "Биометрические данные включают отпечаток пальца, "
        "голосовой отпечаток, ДНК и радужная оболочка глаза."
    )
    result = anonymize(text, Options(biometric_mentions=True))
    assert restore(result.text, result.mapping) == text


# --- DETECT-010: label-anchored medical-data detection -------------------


def test_medical_oms_label_anchored_16_digits():
    text = "Полис ОМС: 1234567890123456"
    medical = [s for s in detect(text) if s.category == Category.MEDICAL]
    assert [s.value for s in medical] == ["1234567890123456"]


def test_medical_dms_label_anchored_arbitrary_format():
    # ДМС policy numbers have no canonical shape — a non-whitespace run after
    # the label is enough.
    text = "Полис ДМС: AB-100500"
    medical = [s for s in detect(text) if s.category == Category.MEDICAL]
    assert [s.value for s in medical] == ["AB-100500"]


def test_medical_diagnosis_label_captures_free_text():
    text = "Диагноз: гипертония II ст."
    medical = [s for s in detect(text) if s.category == Category.MEDICAL]
    assert [s.value for s in medical] == ["гипертония II ст."]


def test_medical_history_and_anamnesis_labels_match():
    # «анамнез» and «история болезни» share the DIAGNOSIS rule.
    text = "История болезни: бронхит\nАнамнез: ОРВИ"
    values = [s.value for s in detect(text) if s.category == Category.MEDICAL]
    assert values == ["бронхит", "ОРВИ"]


def test_medical_icd10_context_anchored_detected():
    # ICD-10 code under a «Диагноз» label is tokenized as MEDICAL.
    text = "Диагноз I10.0"
    medical = [s for s in detect_all(text, Options()) if s.category == Category.MEDICAL]
    assert [s.value for s in medical] == ["I10.0"]


def test_medical_icd10_under_mkb_label_detected():
    # The ICD-10 rule accepts the explicit «МКБ-10» / «МКБ» / «код МКБ» labels.
    for label in ("МКБ-10: I10.0", "МКБ I10.0", "код МКБ: I10.0"):
        medical = [s for s in detect(label) if s.category == Category.MEDICAL]
        assert any(s.value == "I10.0" for s in medical), f"missed: {label!r}"


def test_medical_bare_16_digits_not_tokenized_as_medical():
    # A bare 16-digit run outside a `Полис ОМС` label is not MEDICAL. Whether
    # it is tokenized as CARD or untouched depends on the Luhn checksum; that
    # is irrelevant to this assertion.
    text = "Контрагент 1234567890123456 в реестре."
    medical = [s for s in detect(text) if s.category == Category.MEDICAL]
    assert medical == []


def test_medical_icd10_looking_token_outside_medical_context_not_tokenized():
    # An ICD-10-shaped token in a non-medical context (table-of-contents heading)
    # is not matched — the ICD-10 rule requires an immediately preceding
    # medical label.
    text = "Раздел A10.1 — общие сведения"
    spans = detect(text)
    assert not [s for s in spans if s.category == Category.MEDICAL]


def test_medical_icd10_case_sensitive_lowercase_not_matched():
    # МКБ-10 codes are always uppercase Latin — a lowercase token does not
    # match the ICD-10 rule even when followed by a digit triple. (The
    # DIAGNOSIS rule would still capture a label-anchored line — this test
    # checks the bare-code rule, not the label rule.)
    text = "Код a10.1 справочника"  # no medical label
    spans = detect(text)
    assert not [s for s in spans if s.category == Category.MEDICAL]


def test_medical_round_trip_exact():
    text = (
        "Полис ОМС: 1234567890123456\n"
        "Полис ДМС: AB-100500\n"
        "Диагноз: гипертония II ст.\n"
        "МКБ-10: I10.0"
    )
    result = anonymize(text, Options())
    # All four medical values are tokenized — none leaks.
    for needle in ("1234567890123456", "AB-100500", "гипертония II ст.", "I10.0"):
        assert needle not in result.text, f"{needle!r} leaked"
    med_tokens = {t for t in result.mapping if t.startswith("{{MEDICAL_")}
    assert med_tokens == {
        "{{MEDICAL_1}}",
        "{{MEDICAL_2}}",
        "{{MEDICAL_3}}",
        "{{MEDICAL_4}}",
    }
    assert restore(result.text, result.mapping) == text


# --- DETECT-011: BIK structural validator --------------------------------


def test_bik_valid_country_prefix_detected():
    # Sberbank Moscow — `04` country prefix, non-zero region/branch sub-field.
    bik = [s for s in detect("БИК 044525225") if s.category == "BIK"]
    assert [s.value for s in bik] == ["044525225"]


def test_bik_invalid_country_prefix_rejected():
    # `99…` is not a Central Bank of Russia country prefix — the structural
    # validator rejects it so a non-BIK 9-digit number after the «БИК» label
    # is no longer mis-tokenized.
    assert not [s for s in detect("БИК 999000000") if s.category == "BIK"]


def test_bik_zero_territorial_subfield_rejected():
    # A `04`-prefixed run with an all-zero region+territorial sub-field
    # (digits 3-6) is structurally invalid — no real BIK uses `040000…`.
    assert not [s for s in detect("БИК 040000000") if s.category == "BIK"]


def test_bik_corpus_value_still_detected():
    # The labelled corpus uses `044599001` (tests/corpus/02-company.json);
    # the validator must keep that detection green.
    bik = [s for s in detect("БИК 044599001") if s.category == "BIK"]
    assert [s.value for s in bik] == ["044599001"]


def test_bik_round_trip_exact():
    text = "БИК 044525225 — Сбербанк России (Москва)."
    result = anonymize(text, Options())
    assert "044525225" not in result.text
    assert "{{BIK_1}}" in result.text
    assert restore(result.text, result.mapping) == text


# --- DETECT-012: opt-in family-relation label detection ------------------


_FAMILY_RELATION_SAMPLE = "Супруга: Иванова Анна Петровна; дети: Иванов Пётр, Иванова Мария"


def test_family_relations_off_by_default_emits_no_family_spans():
    # With the default Options() the FAMILY_RELATION rule is gated off, so
    # ``regex_rules.detect`` emits no span whose start sits inside a
    # family-relation label scope. The existing PERSON patronymic rule may
    # still fire on «Иванова Анна Петровна» — that is not a family-relation
    # span, so the assertion targets the rule-attributable continuation
    # names which are unique to DETECT-012 (`Иванов Пётр`, `Иванова Мария`).
    spans = detect(_FAMILY_RELATION_SAMPLE, Options())
    person_values = [s.value for s in spans if s.category == Category.PERSON]
    assert "Иванов Пётр" not in person_values
    assert "Иванова Мария" not in person_values


def test_family_relations_flag_tokenizes_each_name_as_person():
    # DoD: with --family-relations on, each of the three names is captured
    # as PERSON and the relation labels stay verbatim in the text.
    result = anonymize(_FAMILY_RELATION_SAMPLE, Options(family_relations=True))
    person_tokens = {t for t in result.mapping if t.startswith("{{PERSON_")}
    person_values = {result.mapping[t] for t in person_tokens}
    assert person_values == {"Иванова Анна Петровна", "Иванов Пётр", "Иванова Мария"}
    # No raw name leaks.
    for needle in ("Иванова Анна Петровна", "Иванов Пётр", "Иванова Мария"):
        assert needle not in result.text, f"{needle!r} leaked"
    # Relation labels stay verbatim in the anonymized text.
    assert "Супруга:" in result.text
    assert "дети:" in result.text


def test_family_relations_common_noun_usage_not_matched_with_flag_on():
    # DoD: «Дети программистов учатся быстрее» — the trailing word starts
    # lowercase, so the case-sensitive ``[А-ЯЁ]`` first-character anchor in
    # the name capture rejects it. No FAMILY_RELATION span is emitted even
    # with the flag on.
    text = "Дети программистов учатся быстрее"
    spans = detect(text, Options(family_relations=True))
    # No PERSON span is emitted by any regex rule on this text: the PERSON
    # patronymic rule needs a 3-word patronymic suffix and the
    # FAMILY_RELATION rule needs a capitalised follow-on.
    assert not [s for s in spans if s.category == Category.PERSON]


def test_family_relations_options_none_does_not_run_rule():
    # The historical ``options=None`` default keeps every gated rule off,
    # so a family-relation labelled line yields no continuation spans.
    spans = detect(_FAMILY_RELATION_SAMPLE, None)
    values = {s.value for s in spans if s.category == Category.PERSON}
    assert "Иванов Пётр" not in values
    assert "Иванова Мария" not in values


def test_family_relations_label_inflections_match():
    # Inline ``(?i:…)`` on the label part means mid-sentence lowercase
    # labels also match. The inflections («супруги», «супругой») accepted
    # by the rule cover the common forms.
    cases = (
        ("супруги Иванов и Петров", "Иванов"),
        ("Брат: Иванов Иван", "Иванов Иван"),
        ("Сестра Иванова Анна", "Иванова Анна"),
        ("отец — Иванов", "Иванов"),
        ("мать - Иванова Мария", "Иванова Мария"),
        ("Сын Сидоров", "Сидоров"),
    )
    for text, expected in cases:
        spans = detect(text, Options(family_relations=True))
        family_values = [
            s.value for s in spans if s.category == Category.PERSON and s.value == expected
        ]
        assert family_values, f"missed name {expected!r} in {text!r}"


def test_family_relations_qa001_corpus_invariant_when_off():
    # When the flag is off, regex_rules.detect() must not return any
    # FAMILY_RELATION-attributable PERSON span on a labelled sample —
    # confirming the QA-001 corpus precision/recall is bit-identical to
    # the pre-DETECT-012 baseline whenever the opt-in stays disabled.
    text = "Супруг: Иванов Пётр, дочь: Иванова Мария."
    spans_off = detect(text, Options())
    spans_default = detect(text, None)
    off_values = {s.value for s in spans_off if s.category == Category.PERSON}
    default_values = {s.value for s in spans_default if s.category == Category.PERSON}
    assert "Иванов Пётр" not in off_values
    assert "Иванова Мария" not in off_values
    assert "Иванов Пётр" not in default_values
    assert "Иванова Мария" not in default_values


def test_family_relations_round_trip_exact():
    # Round-trip ``anonymize → restore`` reproduces the input character for
    # character — the relation labels stay verbatim and only the captured
    # names are replaced with reversible {{PERSON_N}} tokens.
    result = anonymize(_FAMILY_RELATION_SAMPLE, Options(family_relations=True))
    assert restore(result.text, result.mapping) == _FAMILY_RELATION_SAMPLE


# --- DETECT-013: opt-in job-title and education-qualification detection --


_OCCUPATION_SAMPLE = "Должность: Главный инженер. Образование: магистр информатики"


def test_occupation_off_by_default_keeps_role_text_untokenized():
    # With the default Options() the JOB_TITLE / EDUCATION rules are gated
    # off, so the regex detector emits zero OCCUPATION spans even for an
    # input that does contain the résumé labels. This is the QA-001
    # bit-identity invariant — without the flag the same input passes
    # through unchanged with respect to the OCCUPATION category.
    spans = detect(_OCCUPATION_SAMPLE, Options())
    assert not [s for s in spans if s.category == Category.OCCUPATION]
    # The candidate values themselves remain in the text.
    result = anonymize(_OCCUPATION_SAMPLE, Options())
    assert "Главный инженер" in result.text
    assert "магистр информатики" in result.text
    # No OCCUPATION token leaked into the mapping.
    assert not [t for t in result.mapping if t.startswith("{{OCCUPATION_")]


def test_occupation_flag_tokenizes_job_title_and_education():
    # DoD-required input: with --occupation on, both ``Главный инженер``
    # (Должность) and ``магистр информатики`` (Образование) are tokenized
    # under Category.OCCUPATION; the labels themselves stay verbatim.
    result = anonymize(_OCCUPATION_SAMPLE, Options(occupation=True))
    occ_tokens = {t for t in result.mapping if t.startswith("{{OCCUPATION_")}
    occ_values = {result.mapping[t] for t in occ_tokens}
    assert occ_values == {"Главный инженер", "магистр информатики"}
    # No raw role/qualification text leaks.
    assert "Главный инженер" not in result.text
    assert "магистр информатики" not in result.text
    # Labels stay verbatim in the anonymized text.
    assert "Должность:" in result.text
    assert "Образование:" in result.text


def test_occupation_common_noun_usage_not_matched_with_flag_on():
    # DoD: ``должность позволяет ему`` — no colon / em-dash / hyphen anchor
    # after the label, so the non-whitespace-separator gate rejects the
    # match. No OCCUPATION span is emitted even with the flag on.
    text = "должность позволяет ему работать удалённо"
    spans = detect(text, Options(occupation=True))
    assert not [s for s in spans if s.category == Category.OCCUPATION]


def test_occupation_options_none_does_not_run_rule():
    # The historical ``options=None`` default keeps every gated rule off,
    # so an occupation-labelled line yields no OCCUPATION spans.
    spans = detect(_OCCUPATION_SAMPLE, None)
    assert not [s for s in spans if s.category == Category.OCCUPATION]


def test_occupation_label_variants_match():
    # Each label form documented in the task spec produces a capture.
    cases = (
        ("Должность: Директор", "Директор"),
        ("Занимаемая должность: Старший разработчик", "Старший разработчик"),
        ("Роль — наставник", "наставник"),
        ("Образование: высшее техническое", "высшее техническое"),
        ("Квалификация: бакалавр", "бакалавр"),
        ("Специальность: программная инженерия", "программная инженерия"),
        ("Учёная степень: кандидат наук", "кандидат наук"),
        ("Учёная степень - доктор наук", "доктор наук"),
    )
    for text, expected in cases:
        spans = detect(text, Options(occupation=True))
        values = [s.value for s in spans if s.category == Category.OCCUPATION]
        assert expected in values, f"missed {expected!r} in {text!r} (got {values!r})"


def test_occupation_qa001_corpus_invariant_when_off():
    # When the flag is off, regex_rules.detect() must not return any
    # OCCUPATION-attributable span on a labelled sample — confirming the
    # QA-001 corpus precision/recall is bit-identical to the pre-DETECT-013
    # baseline whenever the opt-in stays disabled.
    text = "Должность: Главный инженер. Образование: магистр информатики"
    spans_off = detect(text, Options())
    spans_default = detect(text, None)
    assert all(s.category != Category.OCCUPATION for s in spans_off)
    assert all(s.category != Category.OCCUPATION for s in spans_default)


def test_occupation_round_trip_exact():
    # Round-trip ``anonymize → restore`` reproduces the input character for
    # character — the labels stay verbatim and only the captured role /
    # qualification values are replaced with reversible {{OCCUPATION_N}} tokens.
    result = anonymize(_OCCUPATION_SAMPLE, Options(occupation=True))
    assert restore(result.text, result.mapping) == _OCCUPATION_SAMPLE


def test_occupation_period_terminator_excluded_from_capture():
    # The `[^\n,;.]+` capture body terminates on `.` so a trailing period
    # does NOT leak into the captured value (the DoD requires `Главный
    # инженер` without the period).
    result = anonymize("Должность: Главный инженер.", Options(occupation=True))
    values = set(result.mapping.values())
    assert "Главный инженер" in values
    assert "Главный инженер." not in values

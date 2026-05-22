"""CORE-002: regex/dictionary detectors."""

import anonymizer.detect as detect_mod
from anonymizer.api import Options, anonymize
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
    "EMAIL", "URL", "PHONE", "INN", "SNILS", "OGRN", "OGRNIP", "KPP", "BIK",
    "ACCOUNT", "CARD", "DOB", "POSTAL_CODE", "ADDRESS", "PASSPORT", "IP",
    "SECRET", "ORG",
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
    for a, b in zip(spans, spans[1:]):
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
    abbreviated = ["ООО", "АО", "ПАО", "ЗАО", "ОАО", "ИП", "НПО", "НКО",
                   "ИЧП", "ТОО", "ОП", "ФГУП", "ФГБУ", "ГУП", "МУП", "ГБУ",
                   "МБУ", "АНО", "ТСЖ", "ЖСК", "СНТ", "КФХ"]
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
    text = (
        "Подписал КРУГЛОВ ОЛЕГ АНАТОЛЬЕВИЧ\n"
        "Сертификат №0262948600F2B281BC43ECDADC4C5F4E5B"
    )
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


def test_url_www_host_and_bare_domain():
    bare = [s.value for s in detect("сайт компании unicum.ru сейчас")
            if s.category == "URL"]
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
    assert [s for s in detect("ОГРНИП 304500116000157")
            if s.category == "OGRNIP"]
    assert not [s for s in detect("ОГРНИП 304500116000158")
                if s.category == "OGRNIP"]


def test_snils_control_digit_validation():
    assert [s for s in detect("СНИЛС 112-233-445 95") if s.category == "SNILS"]
    assert not [s for s in detect("СНИЛС 112-233-445 96")
                if s.category == "SNILS"]


def test_long_numeric_not_tokenized_as_ogrn():
    # A 13-digit code that fails the OGRN checksum is no longer mis-tokenized.
    text = "Код заказа 1111111111111 в смете."
    assert not [s for s in detect(text) if s.category in ("OGRN", "OGRNIP")]


# --- DETECT-002: bare INN guarded by the checksum --------------------------


def test_bare_inn_detected_when_checksum_valid():
    inn = [s for s in detect("Контрагент 7707083893 в реестре.")
           if s.category == "INN"]
    assert inn and inn[0].value == "7707083893"


def test_bare_invalid_inn_not_detected():
    assert not [s for s in detect("Номер 7707083894 в документе.")
                if s.category == "INN"]
    assert not [s for s in detect("Код 500100123427 здесь.")
                if s.category == "INN"]


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

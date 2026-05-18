"""CORE-001: span model and right-to-left token replacement."""

from anonymizer.replace import Span, replace_spans


def test_token_reuse_for_identical_value():
    text = "mail a@x.ru then a@x.ru again"
    spans = [
        Span(5, 11, "EMAIL", "a@x.ru"),
        Span(17, 23, "EMAIL", "a@x.ru"),
    ]
    result = replace_spans(text, spans)
    assert result.text == "mail {{EMAIL_1}} then {{EMAIL_1}} again"
    assert result.mapping == {"{{EMAIL_1}}": "a@x.ru"}


def test_per_category_counters():
    text = "a b c d"
    spans = [
        Span(0, 1, "EMAIL", "a"),
        Span(2, 3, "PHONE", "b"),
        Span(4, 5, "EMAIL", "c"),
        Span(6, 7, "PHONE", "d"),
    ]
    result = replace_spans(text, spans)
    assert result.text == "{{EMAIL_1}} {{PHONE_1}} {{EMAIL_2}} {{PHONE_2}}"


def test_right_to_left_offsets_stay_valid():
    text = "X aaaa Y bb Z"
    spans = [
        Span(2, 6, "INN", "aaaa"),
        Span(9, 11, "PHONE", "bb"),
    ]
    result = replace_spans(text, spans)
    assert result.text == "X {{INN_1}} Y {{PHONE_1}} Z"


def test_preexisting_braces_do_not_collide():
    text = "literal {{EMAIL_1}} and real a@x.ru"
    spans = [Span(29, 35, "EMAIL", "a@x.ru")]
    result = replace_spans(text, spans)
    assert result.text == "literal {{EMAIL_1}} and real {{EMAIL_2}}"
    assert result.mapping == {"{{EMAIL_2}}": "a@x.ru"}

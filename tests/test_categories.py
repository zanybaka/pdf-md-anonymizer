"""Tests for the Category StrEnum (CORE-006)."""

from anonymizer.categories import Category


def test_str_equality():
    assert Category("PERSON").value == "PERSON"
    assert Category.EMAIL == "EMAIL"


def test_token_format():
    # Category is a StrEnum, so f"{Category.EMAIL}" yields "EMAIL" (not "Category.EMAIL").
    # The {{CATEGORY_N}} wire format must remain intact.
    assert f"{{{{{Category.EMAIL}_1}}}}" == "{{EMAIL_1}}"


def test_all_members():
    assert len(Category) == 24

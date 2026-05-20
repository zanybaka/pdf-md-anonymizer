"""Tests for anonymizer.detect.structural (NER-010)."""

from anonymizer.detect.structural import is_in_any_range, skill_section_ranges


def test_skill_section_ranges_basic():
    text = (
        "# Резюме\n\n"
        "## Ключевые навыки\n\nPython, Java\n\n"
        "## Образование\n\nуниверситет\n"
    )
    ranges = skill_section_ranges(text)
    assert len(ranges) == 1
    lo, hi = ranges[0]
    assert text[lo:].startswith("## Ключевые навыки")
    assert text[hi:].startswith("## Образование")


def test_skill_section_ranges_bounded_by_same_depth():
    text = (
        "# Резюме\n\n"
        "## Опыт работы\n\nработал пять лет\n\n"
        "## Ключевые навыки\n\n"
        "### Языки\n\nPython, Java\n\n"
        "## Образование\n\nуниверситет\n"
    )
    ranges = skill_section_ranges(text)
    assert len(ranges) == 1
    lo, hi = ranges[0]
    assert text[lo:].startswith("## Ключевые навыки")
    # deeper subheader stays inside
    assert text.index("### Языки") < hi
    # next same-depth header ends the section
    assert text[hi:].startswith("## Образование")


def test_skill_section_ranges_empty_text():
    assert skill_section_ranges("") == []


def test_skill_section_ranges_no_skills_header():
    text = "## Опыт работы\n\nработал\n\n## Образование\nуниверситет\n"
    assert skill_section_ranges(text) == []


def test_skill_section_ranges_extends_to_end_of_text():
    text = "## Навыки\n\nPython\n"
    ranges = skill_section_ranges(text)
    assert len(ranges) == 1
    lo, hi = ranges[0]
    assert hi == len(text)


def test_is_in_any_range_inside():
    assert is_in_any_range(15, [(10, 50)]) is True


def test_is_in_any_range_outside():
    assert is_in_any_range(5, [(10, 50)]) is False


def test_is_in_any_range_at_boundary_lo():
    assert is_in_any_range(10, [(10, 50)]) is True


def test_is_in_any_range_at_boundary_hi():
    assert is_in_any_range(50, [(10, 50)]) is False


def test_is_in_any_range_empty_ranges():
    assert is_in_any_range(5, []) is False


def test_is_in_any_range_multiple_ranges():
    assert is_in_any_range(25, [(0, 10), (20, 30)]) is True
    assert is_in_any_range(15, [(0, 10), (20, 30)]) is False

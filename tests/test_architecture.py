"""Architecture boundary checks for the pdf-md-anonymizer project.

This module is the canonical home for Phase 8 module-boundary and
forbidden-pattern assertions.  Each Phase 8 task (UI-009, UI-015,
CORE-006, CORE-007, DETECT-003, NER-008, …) that needs to verify
"pattern X appears in only one module" or "no string literal of
category Y exists outside the enum" adds its check here.

Helpers
-------
_files_matching(pattern, root)
    Return every file under *root* whose name matches *pattern*.
_grep_count(pattern, in_paths, flags)
    Count total regex matches across the given files.
"""

import re
from pathlib import Path


def _files_matching(pattern: str, root: Path = Path("src")) -> list[Path]:
    """Walk *root* and return paths whose file name matches *pattern*."""
    import fnmatch

    return [p for p in root.rglob("*") if p.is_file() and fnmatch.fnmatch(p.name, pattern)]


def _grep_count(pattern: str, *, in_paths: list[Path], flags: int = 0) -> int:
    """Return the total number of regex matches across *in_paths*."""
    rx = re.compile(pattern, flags)
    total = 0
    for path in in_paths:
        total += len(rx.findall(path.read_text(encoding="utf-8", errors="replace")))
    return total


# ---------------------------------------------------------------------------
# Smoke check
# ---------------------------------------------------------------------------


def test_core_does_not_import_toga():
    """The core anonymizer package must not depend on Toga (UI layer)."""
    core_files = _files_matching("*.py", Path("src/anonymizer"))
    assert _grep_count(r"^\s*import toga\b", in_paths=core_files, flags=re.MULTILINE) == 0


def test_objcclass_only_in_appkit_bridge():
    """ObjCClass(...) calls must be confined to the appkit_bridge package (UI-009)."""
    ui_files = _files_matching("*.py", Path("src/anonymizer_ui"))
    non_bridge = [p for p in ui_files if "appkit_bridge" not in p.parts]
    count = _grep_count(r"ObjCClass\(", in_paths=non_bridge)
    assert count == 0, f"Found {count} ObjCClass(...) call(s) outside the appkit_bridge package"


# ---------------------------------------------------------------------------
# CORE-006: Category enum
# ---------------------------------------------------------------------------

_CATEGORY_NAMES = [
    "EMAIL",
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
    "URL",
    "SECRET",
    "ORG",
    "PERSON",
    "LOC",
    "NICKNAME",
    "BIOMETRIC",
    "MEDICAL",
    "OCCUPATION",
]

# Files that must NOT contain bare category string literals (the enum module
# and test files are excluded from this check).
_CATEGORY_LITERAL_FORBIDDEN = [
    Path("src/anonymizer/detect/regex_rules.py"),
    Path("src/anonymizer/detect/ner.py"),
    Path("src/anonymizer/detect/__init__.py"),
]


def test_category_strings_only_in_categories_module():
    """No bare category-name string literals in regex_rules.py, ner.py, or detect/__init__.py.

    After CORE-006 all category names are Category enum members; only
    ``src/anonymizer/categories.py`` may contain their string values.
    """
    # Build a pattern that matches any of the category names as a quoted string
    # literal, e.g. "EMAIL" or 'PERSON', but NOT when used as a dict key
    # (followed by a colon) — the _TYPE_TO_CATEGORY keys {"PER", "ORG", "LOC"}
    # are Natasha internal type codes and must not be flagged.
    alternation = "|".join(_CATEGORY_NAMES)
    # Negative lookahead for ": " catches dict-key positions.
    # To handle both single-line Rule("NAME", ...) and ruff-format-expanded multiline
    # Rule(\n    "NAME", ...) forms, strip Rule() first-arg strings from the text before
    # scanning — they are rule identifiers, not category value literals (DETECT-003).
    rule_name_rx = re.compile(rf"""Rule\(\s*(?:"|')(?:{alternation})(?:"|')""", re.DOTALL)
    pattern = re.compile(rf"""(?:"|')(?:{alternation})(?:"|')(?!\s*:)""")
    count = 0
    for path in _CATEGORY_LITERAL_FORBIDDEN:
        text = path.read_text(encoding="utf-8", errors="replace")
        text = rule_name_rx.sub("Rule(__", text)
        count += len(pattern.findall(text))
    assert count == 0, (
        f"Found {count} bare category string literal(s) in the detection modules. "
        "Use Category.<NAME> instead."
    )


# ---------------------------------------------------------------------------
# CORE-007: FileStatus / Stage enums
# ---------------------------------------------------------------------------

_STATUS_LITERALS = ["done", "failed", "cancelled"]
_STAGE_LITERALS = ["converting", "detecting"]

_STATUS_STAGE_FORBIDDEN = [
    Path("src/anonymizer/batch.py"),
    Path("src/anonymizer/cli.py"),
    Path("src/anonymizer_ui/app.py"),
    Path("src/anonymizer_ui/batch_controller.py"),
]


def test_filestatus_strings_only_in_batch_enum():
    """No raw status/stage string literals outside their enum definitions.

    After CORE-007 all status and stage names must be FileStatus/Stage enum
    values; bare string literals like "done" or "converting" must not appear
    in the production modules (other than the enum value assignments).
    """
    alt_status = "|".join(_STATUS_LITERALS)
    alt_stage = "|".join(_STAGE_LITERALS)
    # Match quoted literals; negative lookbehind for '=' to skip enum value
    # assignments (e.g.  DONE = "done").
    pattern = rf"""(?<!=\s)(?:"|')(?:{alt_status}|{alt_stage})(?:"|')"""
    count = _grep_count(pattern, in_paths=_STATUS_STAGE_FORBIDDEN)
    assert count == 0, (
        f"Found {count} raw status/stage string literal(s). "
        "Use FileStatus.<NAME> or Stage.<NAME> instead."
    )

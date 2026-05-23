"""PDF-001/PDF-002/PDF-003: external pdf2md subprocess wrapper."""

import pytest

from anonymizer.api import Options, anonymize
from anonymizer.convert import (
    ConversionError,
    default_pdf2md_command,
    normalize_hyphen_spacing,
    pdf_to_markdown,
    rejoin_hyphenated_linebreaks,
)
from anonymizer.detect import detect_all
from anonymizer.mapping import restore


def test_missing_executable_raises_named_error():
    with pytest.raises(ConversionError, match="no-such-pdf2md-xyz"):
        pdf_to_markdown("doc.pdf", command="no-such-pdf2md-xyz")


def test_nonzero_exit_raises(tmp_path):
    # `cat` on a missing file exits non-zero.
    with pytest.raises(ConversionError):
        pdf_to_markdown(tmp_path / "missing.pdf", command="cat")


def test_success_captures_stdout(tmp_path):
    doc = tmp_path / "doc.pdf"
    doc.write_text("# Converted", encoding="utf-8")
    assert pdf_to_markdown(doc, command="cat") == "# Converted"


def test_default_command_prefers_env_local(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "pdf2md"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr("sys.prefix", str(tmp_path))
    assert default_pdf2md_command() == str(exe)


def test_default_command_falls_back_to_path(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.prefix", str(tmp_path))
    import anonymizer.convert as _conv

    monkeypatch.setattr(_conv, "_user_backend_pdf2md", lambda: tmp_path / "bin" / "pdf2md")
    assert default_pdf2md_command() == "pdf2md"


def test_default_command_finds_user_backend(monkeypatch, tmp_path):
    """pdf2md in the user backend dir is preferred over PATH when env-local is absent."""
    monkeypatch.setattr("sys.prefix", str(tmp_path))
    backend_bin = tmp_path / "backend" / "bin"
    backend_bin.mkdir(parents=True)
    pdf2md_exe = backend_bin / "pdf2md"
    pdf2md_exe.write_text("#!/bin/sh\n", encoding="utf-8")
    from anonymizer import convert

    monkeypatch.setattr(convert, "_user_backend_pdf2md", lambda: pdf2md_exe)
    assert default_pdf2md_command() == str(pdf2md_exe)


def test_default_command_env_local_beats_user_backend(monkeypatch, tmp_path):
    """Env-local pdf2md takes priority over the user backend."""
    env_bin = tmp_path / "bin"
    env_bin.mkdir()
    env_exe = env_bin / "pdf2md"
    env_exe.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr("sys.prefix", str(tmp_path))
    backend_exe = tmp_path / "backend" / "bin" / "pdf2md"
    from anonymizer import convert

    monkeypatch.setattr(convert, "_user_backend_pdf2md", lambda: backend_exe)
    assert default_pdf2md_command() == str(env_exe)


# --- PDF-003: rejoin hyphenated line-breaks --------------------------------


def test_rejoin_hyphenated_word():
    assert rejoin_hyphenated_linebreaks("Санкт-\nПетербург") == "Санкт-Петербург"


def test_rejoin_drops_continuation_indentation():
    assert rejoin_hyphenated_linebreaks("Санкт-\n   Петербург") == "Санкт-Петербург"


def test_rejoin_leaves_markdown_list_untouched():
    md = "- пункт один\n- пункт два\n"
    assert rejoin_hyphenated_linebreaks(md) == md


def test_rejoin_leaves_emdash_bullets_untouched():
    md = "— первый\n— второй\n"
    assert rejoin_hyphenated_linebreaks(md) == md


def test_rejoin_skips_hyphen_with_trailing_space_before_newline():
    text = "слово - \nдругое"
    assert rejoin_hyphenated_linebreaks(text) == text


def test_rejoined_city_detected_as_single_loc_span():
    cleaned = rejoin_hyphenated_linebreaks("Живёт в городе Санкт-\nПетербург сейчас.")
    loc = [s for s in detect_all(cleaned, Options()) if s.category == "LOC"]
    assert any("Санкт-Петербург" in s.value for s in loc)


def test_rejoined_markdown_round_trips():
    cleaned = rejoin_hyphenated_linebreaks("Санкт-\nПетербург, ИНН 7707083893.")
    result = anonymize(cleaned, Options())
    assert restore(result.text, result.mapping) == cleaned


# --- Normalize space-padded hyphens (pdf2md punctuation spacing) -----------


def test_normalize_collapses_padded_hyphen_variants():
    assert normalize_hyphen_spacing("Санкт - Петербург") == "Санкт - Петербург"
    assert normalize_hyphen_spacing("Санкт -Петербург") == "Санкт - Петербург"
    assert normalize_hyphen_spacing("Санкт- Петербург") == "Санкт - Петербург"


def test_normalize_leaves_joined_compounds_untouched():
    # No padding — a genuine compound, not a pdf2md artifact.
    for word in ("кто-то", "e-mail", "IT-компания"):
        assert normalize_hyphen_spacing(word) == word


def test_normalize_leaves_list_markers_and_emdash_untouched():
    md = "- пункт один\n- пункт два\n"
    assert normalize_hyphen_spacing(md) == md
    assert normalize_hyphen_spacing("слово — другое") == "слово — другое"


def test_normalized_split_city_detected_as_one_loc_span():
    # The glued variant pdf2md emits — Natasha misses the second half until
    # the spacing is normalized and the NER layer merges the two halves.
    text = "Живёт в Санкт -Петербург сейчас."
    cleaned = normalize_hyphen_spacing(text)
    loc = [s for s in detect_all(cleaned, Options()) if s.category == "LOC"]
    assert any(s.value == "Санкт - Петербург" for s in loc)
    result = anonymize(cleaned, Options())
    assert restore(result.text, result.mapping) == cleaned

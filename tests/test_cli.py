"""CLI-001: batch input, wildcards, and single-file behavior."""

import io
import sys

import pytest

from anonymizer import cli


def run(argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["anon", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return exc.value.code or 0


def test_single_file_explicit_output(tmp_path, monkeypatch):
    src = tmp_path / "a.md"
    src.write_text("mail ivan@example.ru", encoding="utf-8")
    out = tmp_path / "out.md"
    mp = tmp_path / "out.map.json"
    assert run([str(src), "-o", str(out), "--map", str(mp)], monkeypatch) == 0
    assert "ivan@example.ru" not in out.read_text(encoding="utf-8")
    assert mp.exists()


def test_single_file_auto_output_next_to_input(tmp_path, monkeypatch, capsys):
    src = tmp_path / "report.md"
    src.write_text("mail ivan@example.ru", encoding="utf-8")
    assert run([str(src)], monkeypatch) == 0
    out = tmp_path / "report.anon.md"
    mp = tmp_path / "report.anon.map.json"
    assert out.exists()
    assert not mp.exists(), "map must not be written without --map"
    assert "ivan@example.ru" not in out.read_text(encoding="utf-8")
    assert capsys.readouterr().out == ""  # nothing written to stdout


def test_single_file_explicit_map_written(tmp_path, monkeypatch):
    src = tmp_path / "report.md"
    src.write_text("mail ivan@example.ru", encoding="utf-8")
    mp = tmp_path / "report.map.json"
    assert run([str(src), "--map", str(mp)], monkeypatch) == 0
    assert mp.exists()
    assert "ivan@example.ru" in mp.read_text(encoding="utf-8")


def test_single_file_prints_stage_progress(tmp_path, monkeypatch, capsys):
    src = tmp_path / "report.md"
    src.write_text("mail ivan@example.ru", encoding="utf-8")
    assert run([str(src)], monkeypatch) == 0
    err = capsys.readouterr().err
    assert "detecting" in err and "done" in err


def test_batch_prints_numbered_stage_progress(tmp_path, monkeypatch, capsys):
    (tmp_path / "a.md").write_text("a@x.ru", encoding="utf-8")
    (tmp_path / "b.md").write_text("b@x.ru", encoding="utf-8")
    outdir = tmp_path / "out"
    code = run(
        [str(tmp_path / "a.md"), str(tmp_path / "b.md"), "-o", str(outdir)],
        monkeypatch,
    )
    assert code == 0
    err = capsys.readouterr().err
    assert "[1/2]" in err and "[2/2]" in err and "detecting" in err


def test_single_pdf_auto_output_strips_extension(tmp_path, monkeypatch):
    src = tmp_path / "report.pdf"
    src.write_text("mail ivan@example.ru", encoding="utf-8")
    assert run([str(src), "--pdf2md-cmd", "cat"], monkeypatch) == 0
    assert (tmp_path / "report.anon.md").exists()
    assert not (tmp_path / "report.anon.map.json").exists(), "map must not be written without --map"


def test_stdin_still_writes_to_stdout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("mail ivan@example.ru"))
    assert run(["-"], monkeypatch) == 0
    assert "{{EMAIL_1}}" in capsys.readouterr().out


def test_batch_extension_preserving_names(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("ivan@example.ru", encoding="utf-8")
    (tmp_path / "a.pdf").write_text("petr@example.ru", encoding="utf-8")
    outdir = tmp_path / "out"
    code = run(
        [str(tmp_path / "a.md"), str(tmp_path / "a.pdf"), "-o", str(outdir), "--pdf2md-cmd", "cat"],
        monkeypatch,
    )
    assert code == 0
    assert (outdir / "a.md.anon.md").exists()
    assert (outdir / "a.pdf.anon.md").exists()
    assert not (outdir / "a.md.map.json").exists(), "map must not be written without --map"
    assert not (outdir / "a.pdf.map.json").exists(), "map must not be written without --map"


def test_batch_explicit_map_dir_written(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("ivan@example.ru", encoding="utf-8")
    (tmp_path / "b.md").write_text("petr@example.ru", encoding="utf-8")
    outdir = tmp_path / "out"
    mapdir = tmp_path / "maps"
    code = run(
        [str(tmp_path / "a.md"), str(tmp_path / "b.md"), "-o", str(outdir), "--map", str(mapdir)],
        monkeypatch,
    )
    assert code == 0
    assert (outdir / "a.md.anon.md").exists()
    assert (mapdir / "a.md.map.json").exists()


def test_glob_wildcard_expansion(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "x.md").write_text("a@x.ru", encoding="utf-8")
    (docs / "y.md").write_text("b@x.ru", encoding="utf-8")
    outdir = tmp_path / "out"
    assert run([str(docs / "*.md"), "-o", str(outdir)], monkeypatch) == 0
    assert (outdir / "x.md.anon.md").exists()
    assert (outdir / "y.md.anon.md").exists()


def test_bad_file_does_not_abort_batch(tmp_path, monkeypatch, capsys):
    (tmp_path / "good.md").write_text("a@x.ru", encoding="utf-8")
    outdir = tmp_path / "out"
    code = run(
        [str(tmp_path / "good.md"), str(tmp_path / "missing.md"), "-o", str(outdir)],
        monkeypatch,
    )
    assert code == 1
    assert (outdir / "good.md.anon.md").exists()
    err = capsys.readouterr().err
    assert "a@x.ru" not in err  # progress/error output carries no document content


def test_no_args_prints_help_without_crashing(monkeypatch, capsys):
    code = run([], monkeypatch)
    assert code == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_restore_round_trip(tmp_path, monkeypatch):
    src = tmp_path / "a.md"
    src.write_text("mail ivan@example.ru here", encoding="utf-8")
    out = tmp_path / "out.md"
    mp = tmp_path / "m.json"
    back = tmp_path / "back.md"
    assert run([str(src), "-o", str(out), "--map", str(mp)], monkeypatch) == 0
    assert run(["restore", str(out), "--map", str(mp), "-o", str(back)], monkeypatch) == 0
    assert back.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")

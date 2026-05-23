"""PDF-004: batched pdf2md invocation.

These tests stub out the resolution of the pdf2md interpreter so a real
docling install is not required. The driver-style ``pdf2md`` command is a
short Python script (with a ``#!`` shebang) that mimics the contract of the
upstream batch CLI: it consumes ``out_dir`` + pdf paths and emits one JSON
record per file to stdout as each one finishes.
"""

from __future__ import annotations

import os
import re
import sys
import textwrap
from pathlib import Path

import pytest

from anonymizer import convert
from anonymizer.convert import (
    ConversionError,
    pdf_batch_to_markdown,
    pdf_to_markdown,
)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX shebang assumed")


def _make_fake_pdf2md(
    tmp_path: Path,
    *,
    fail_on: set[str] | None = None,
    sleep_between: float = 0.0,
    record_invocations: Path | None = None,
) -> Path:
    """Write a fake ``pdf2md`` script that pretends to be a docling-backed CLI.

    The script's body is intentionally empty when invoked single-file (it just
    ``cat``s the input), and when invoked batch-driver-style (``-c <code>``)
    it reads pdfs from argv, writes per-file markdown into the temp dir, and
    streams JSON records to stdout.
    """
    fail_on = fail_on or set()
    body = textwrap.dedent(
        f"""\
        #!{sys.executable}
        import json, sys, time
        from pathlib import Path

        FAIL_ON = {sorted(fail_on)!r}
        SLEEP_BETWEEN = {sleep_between!r}
        RECORD_INVOCATIONS = {str(record_invocations) if record_invocations else None!r}

        if RECORD_INVOCATIONS:
            Path(RECORD_INVOCATIONS).write_text(
                (Path(RECORD_INVOCATIONS).read_text() if Path(RECORD_INVOCATIONS).exists() else "")
                + "INVOKE\\n",
                encoding="utf-8",
            )

        def render(p):
            # Identical conversion logic in both branches so a batch run and
            # per-file run produce bit-identical Markdown for the same input.
            return Path(p).read_text(encoding="utf-8", errors="replace")

        if len(sys.argv) >= 2 and sys.argv[1] == "-c":
            # Batch-driver branch: argv = [self, "-c", driver_src, out_dir, *pdfs]
            out_dir = Path(sys.argv[3])
            pdfs = [Path(p) for p in sys.argv[4:]]
            for i, p in enumerate(pdfs):
                name = Path(p).name
                if name in FAIL_ON:
                    rec = {{"index": i, "path": str(p), "status": "error",
                            "error": "ValueError: pretend " + name + " is corrupt"}}
                else:
                    out = out_dir / (str(i) + ".md")
                    out.write_text(render(p), encoding="utf-8")
                    rec = {{"index": i, "path": str(p), "status": "ok",
                            "output": str(out)}}
                sys.stdout.write(json.dumps(rec) + chr(10))
                sys.stdout.flush()
                if SLEEP_BETWEEN:
                    time.sleep(SLEEP_BETWEEN)
        else:
            # Single-file branch (PDF-001 contract): same render function.
            sys.stdout.write(render(sys.argv[1]))
        """
    )
    script = tmp_path / "fake_pdf2md"
    script.write_text(body, encoding="utf-8")
    script.chmod(0o755)
    return script


def _patch_driver_to_invoke_fake_script(monkeypatch, fake_script: Path) -> None:
    """Make the production batch driver invoke our fake script, not our driver.

    ``pdf_batch_to_markdown`` runs ``[pdf2md_python, "-c", driver_src, out_dir, *paths]``.
    We swap the resolved ``pdf2md_python`` for the fake script itself so the
    script receives the same argv shape and emits JSON records the parent
    reads back.
    """
    monkeypatch.setattr(convert, "_resolve_pdf2md_python", lambda _cmd: (str(fake_script), []))


# --- pdf_batch_to_markdown ------------------------------------------------


def test_batch_streams_per_file_results(tmp_path, monkeypatch):
    pdfs = [tmp_path / f"f{i}.pdf" for i in range(3)]
    for i, p in enumerate(pdfs):
        p.write_text(f"body-{i}", encoding="utf-8")
    fake = _make_fake_pdf2md(tmp_path)
    _patch_driver_to_invoke_fake_script(monkeypatch, fake)

    results: list[tuple[Path, str | Exception]] = []
    pdf_batch_to_markdown(
        pdfs,
        command=str(fake),
        on_file=lambda p, payload: results.append((p, payload)),
    )
    assert [p for p, _ in results] == pdfs
    # Post-processing applied (hyphen rejoin is a no-op here) and body present.
    for p, md in results:
        assert isinstance(md, str)
        assert f"body-{pdfs.index(p)}" in md


def test_batch_per_file_failure_does_not_abort_siblings(tmp_path, monkeypatch):
    pdfs = [tmp_path / "a.pdf", tmp_path / "b.pdf", tmp_path / "c.pdf"]
    for p in pdfs:
        p.write_text("x", encoding="utf-8")
    fake = _make_fake_pdf2md(tmp_path, fail_on={"b.pdf"})
    _patch_driver_to_invoke_fake_script(monkeypatch, fake)

    results: list[tuple[Path, str | Exception]] = []
    pdf_batch_to_markdown(
        pdfs,
        command=str(fake),
        on_file=lambda p, payload: results.append((p, payload)),
    )
    assert [p for p, _ in results] == pdfs
    assert isinstance(results[0][1], str)
    assert isinstance(results[1][1], Exception)
    assert "b.pdf" in str(results[1][1])
    assert isinstance(results[2][1], str)


def test_batch_runs_one_subprocess_for_three_pdfs(tmp_path, monkeypatch):
    """DoD: model-init happens once per group, not once per file."""
    pdfs = [tmp_path / f"f{i}.pdf" for i in range(3)]
    for p in pdfs:
        p.write_text("x", encoding="utf-8")
    invocations = tmp_path / "invocations.log"
    fake = _make_fake_pdf2md(tmp_path, record_invocations=invocations)
    _patch_driver_to_invoke_fake_script(monkeypatch, fake)

    pdf_batch_to_markdown(pdfs, command=str(fake), on_file=lambda *_: None)
    invocations_text = invocations.read_text(encoding="utf-8")
    assert invocations_text.count("INVOKE") == 1, (
        f"expected exactly one batch subprocess for 3 PDFs, got {invocations_text.count('INVOKE')}"
    )


def test_batch_cancel_between_files(tmp_path, monkeypatch):
    pdfs = [tmp_path / f"f{i}.pdf" for i in range(3)]
    for p in pdfs:
        p.write_text("x", encoding="utf-8")
    fake = _make_fake_pdf2md(tmp_path, sleep_between=0.5)
    _patch_driver_to_invoke_fake_script(monkeypatch, fake)

    delivered: list[Path] = []
    cancelled = {"flag": False}

    def on_file(p, payload):
        delivered.append(p)
        # Trip cancel after the first successful delivery.
        cancelled["flag"] = True

    pdf_batch_to_markdown(
        pdfs,
        command=str(fake),
        cancel=lambda: cancelled["flag"],
        on_file=on_file,
    )
    # The first file is delivered; the rest are skipped because the parent
    # kills the subprocess between records.
    assert delivered == pdfs[:1]


def test_batch_falls_back_when_command_has_no_shebang(tmp_path):
    """A non-Python ``cat`` shells out one-per-file via the fallback path."""
    pdfs = [tmp_path / "a.pdf", tmp_path / "b.pdf"]
    for p in pdfs:
        p.write_text("# title", encoding="utf-8")
    results: list[tuple[Path, str | Exception]] = []
    pdf_batch_to_markdown(
        pdfs, command="cat", on_file=lambda p, payload: results.append((p, payload))
    )
    assert [p for p, _ in results] == pdfs
    for _, payload in results:
        assert isinstance(payload, str)
        assert "# title" in payload


def test_batch_missing_executable_raises():
    with pytest.raises(ConversionError, match="no-such-pdf2md-xyz"):
        pdf_batch_to_markdown(
            [Path("doc.pdf")], command="no-such-pdf2md-xyz", on_file=lambda *_: None
        )


def test_batch_empty_paths_is_noop():
    # Must not raise even when the command would be unresolvable.
    pdf_batch_to_markdown([], command="no-such-pdf2md-xyz", on_file=lambda *_: None)


# --- pdf_to_markdown stays bit-identical to PDF-001/PDF-003 ----------------


def test_pdf_to_markdown_still_uses_cat_per_file(tmp_path):
    """PDF-001 contract preserved: single-file API spawns one ``cat``."""
    doc = tmp_path / "doc.pdf"
    doc.write_text("# Converted\nLine", encoding="utf-8")
    assert pdf_to_markdown(doc, command="cat") == "# Converted\nLine"


# --- ADR-0002: subprocess boundary preserved -------------------------------


def test_no_pdf_to_markdown_import_in_anonymizer_source():
    """ADR-0002: src/anonymizer/ must not import the pdf_to_markdown package."""
    src_root = Path("src/anonymizer")
    rx = re.compile(r"^\s*(?:from|import)\s+pdf_to_markdown\b", re.MULTILINE)
    offenders: list[Path] = []
    for path in src_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if rx.search(text):
            offenders.append(path)
    assert offenders == [], (
        f"Found `import pdf_to_markdown` in src/anonymizer/: {offenders}. "
        "ADR-0002 requires pdf-to-markdown to be reached only via subprocess."
    )

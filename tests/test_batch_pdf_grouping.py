"""PDF-004: process_files groups consecutive PDFs into one pdf2md call.

The fake pdf2md script in ``tests/test_convert_batch.py`` accepts both the
single-file PDF-001 contract (``cat <pdf>``) and the new batch-driver
contract (``-c <driver> <out_dir> <pdfs...>``); we reuse it here.

Regression invariant: with the same fake converter, the output ``.anon.md``
and ``.map.json`` for a multi-PDF run must be bit-identical to a per-file
``pdf_to_markdown`` run feeding ``anonymize`` directly. That nails down DoD
"per-file outputs are bit-identical to the previous one-subprocess-per-file
path".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.api import Options, anonymize
from anonymizer.batch import (
    CancelToken,
    FileStatus,
    OutputPolicy,
    process_files,
)
from anonymizer.convert import pdf_to_markdown
from anonymizer.mapping import write_map
from tests.test_convert_batch import (
    _make_fake_pdf2md,
    _patch_driver_to_invoke_fake_script,
)

_FIXTURE_TEXTS = [
    "Контакт: ivan@example.ru, тел +7 495 111-22-33.",
    "ООО «Рога и Копыта», ИНН 7707083893.",
    "Адрес: г. Москва, ул. Ленина, д. 1.",
]


def _write_fixtures(tmp_path: Path) -> list[Path]:
    pdfs = []
    for i, text in enumerate(_FIXTURE_TEXTS):
        p = tmp_path / f"f{i}.pdf"
        p.write_text(text, encoding="utf-8")
        pdfs.append(p)
    return pdfs


def test_process_files_groups_consecutive_pdfs_into_one_subprocess(tmp_path, monkeypatch):
    pdfs = _write_fixtures(tmp_path)
    invocations = tmp_path / "invocations.log"
    fake = _make_fake_pdf2md(tmp_path, record_invocations=invocations)
    _patch_driver_to_invoke_fake_script(monkeypatch, fake)

    outdir = tmp_path / "out"
    results = list(
        process_files(
            pdfs,
            output_policy=OutputPolicy.into_directory(outdir),
            map_policy=OutputPolicy.into_directory(outdir),
            options=Options(),
            pdf2md_cmd=str(fake),
        )
    )
    assert [r.status for r in results] == [FileStatus.DONE] * 3
    assert invocations.read_text(encoding="utf-8").count("INVOKE") == 1
    for p in pdfs:
        assert (outdir / f"{p.name}.anon.md").exists()
        assert (outdir / f"{p.name}.map.json").exists()


def test_process_files_pdfs_bit_identical_to_per_file_path(tmp_path, monkeypatch):
    """DoD: batched outputs match what we'd get with one subprocess per file."""
    pdfs = _write_fixtures(tmp_path)
    fake = _make_fake_pdf2md(tmp_path)

    # --- Reference: per-file `pdf_to_markdown` + anonymize via the same
    # production helpers process_files uses, so any difference is purely the
    # batching transport.
    ref_dir = tmp_path / "ref"
    ref_dir.mkdir()
    for p in pdfs:
        md = pdf_to_markdown(p, command=str(fake))
        result = anonymize(md, Options())
        (ref_dir / f"{p.name}.anon.md").write_text(result.text, encoding="utf-8")
        write_map(ref_dir / f"{p.name}.map.json", result.mapping)

    # --- Batched run via the new process_files grouping.
    _patch_driver_to_invoke_fake_script(monkeypatch, fake)
    batched_dir = tmp_path / "batched"
    list(
        process_files(
            pdfs,
            output_policy=OutputPolicy.into_directory(batched_dir),
            map_policy=OutputPolicy.into_directory(batched_dir),
            options=Options(),
            pdf2md_cmd=str(fake),
        )
    )

    for p in pdfs:
        ref_anon = (ref_dir / f"{p.name}.anon.md").read_text(encoding="utf-8")
        bat_anon = (batched_dir / f"{p.name}.anon.md").read_text(encoding="utf-8")
        assert bat_anon == ref_anon, f"anon.md differs for {p.name}"
        ref_map = (ref_dir / f"{p.name}.map.json").read_text(encoding="utf-8")
        bat_map = (batched_dir / f"{p.name}.map.json").read_text(encoding="utf-8")
        assert bat_map == ref_map, f"map.json differs for {p.name}"


def test_process_files_mixed_md_pdf_flushes_group(tmp_path, monkeypatch):
    """A ``.md`` between PDFs splits the run into two pdf2md subprocesses."""
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.md"
    c = tmp_path / "c.pdf"
    a.write_text("ivan@example.ru", encoding="utf-8")
    b.write_text("petr@example.ru", encoding="utf-8")
    c.write_text("masha@example.ru", encoding="utf-8")

    invocations = tmp_path / "invocations.log"
    fake = _make_fake_pdf2md(tmp_path, record_invocations=invocations)
    _patch_driver_to_invoke_fake_script(monkeypatch, fake)

    outdir = tmp_path / "out"
    results = list(
        process_files(
            [a, b, c],
            output_policy=OutputPolicy.into_directory(outdir),
            options=Options(),
            pdf2md_cmd=str(fake),
        )
    )
    assert [r.status for r in results] == [FileStatus.DONE] * 3
    # input order preserved.
    assert [r.input_path for r in results] == [a, b, c]
    # Two batches: [a] and [c]; the .md does not trigger pdf2md.
    assert invocations.read_text(encoding="utf-8").count("INVOKE") == 2


def test_process_files_per_pdf_failure_does_not_abort_group(tmp_path, monkeypatch):
    pdfs = _write_fixtures(tmp_path)
    fake = _make_fake_pdf2md(tmp_path, fail_on={pdfs[1].name})
    _patch_driver_to_invoke_fake_script(monkeypatch, fake)

    outdir = tmp_path / "out"
    results = list(
        process_files(
            pdfs,
            output_policy=OutputPolicy.into_directory(outdir),
            options=Options(),
            pdf2md_cmd=str(fake),
        )
    )
    statuses = [r.status for r in results]
    assert statuses == [FileStatus.DONE, FileStatus.FAILED, FileStatus.DONE]
    assert (outdir / f"{pdfs[0].name}.anon.md").exists()
    assert not (outdir / f"{pdfs[1].name}.anon.md").exists()
    assert (outdir / f"{pdfs[2].name}.anon.md").exists()
    assert "b" in str(results[1].error) or pdfs[1].name in str(results[1].error)


def test_process_files_cancel_between_files_keeps_done_outputs(tmp_path, monkeypatch):
    pdfs = _write_fixtures(tmp_path)
    fake = _make_fake_pdf2md(tmp_path, sleep_between=0.5)
    _patch_driver_to_invoke_fake_script(monkeypatch, fake)

    token = CancelToken()
    outdir = tmp_path / "out"

    # Cancel after the first DONE result is produced inside on_file.
    # We achieve this by wrapping the public callable in monkeypatch — but
    # simpler: install a small shim around _process_pdf_group's on_file.
    # Instead, just trip the token from a thread the moment the first file
    # lands; reading process_files lazily makes that work — we consume
    # results one by one and cancel between them.
    it = process_files(
        pdfs,
        output_policy=OutputPolicy.into_directory(outdir),
        options=Options(),
        pdf2md_cmd=str(fake),
        cancel=token,
    )
    first = next(it)
    # All results for the PDF group are already buffered (the batch call ran
    # to completion before yielding the first one), but the sleep_between
    # gives Cancel a real window — trip the token now and drain.
    token.cancel()
    statuses = [first.status] + [r.status for r in it]
    # First file completed successfully; the rest must not be FAILED — they
    # are either DONE (if delivered before cancel killed the proc) or
    # CANCELLED. Already-written .anon.md is kept on disk.
    assert statuses[0] == FileStatus.DONE
    assert FileStatus.FAILED not in statuses
    assert (outdir / f"{pdfs[0].name}.anon.md").exists()


@pytest.mark.parametrize("nfiles", [3])
def test_process_files_dod_speedup_smoke(tmp_path, monkeypatch, nfiles):
    """Sanity-check the speedup wiring: subprocess count == 1 for an all-PDF run."""
    pdfs = []
    for i in range(nfiles):
        p = tmp_path / f"f{i}.pdf"
        p.write_text(f"content-{i}", encoding="utf-8")
        pdfs.append(p)
    invocations = tmp_path / "invocations.log"
    fake = _make_fake_pdf2md(tmp_path, record_invocations=invocations)
    _patch_driver_to_invoke_fake_script(monkeypatch, fake)

    list(
        process_files(
            pdfs,
            output_policy=OutputPolicy.into_directory(tmp_path / "out"),
            options=Options(),
            pdf2md_cmd=str(fake),
        )
    )
    assert invocations.read_text(encoding="utf-8").count("INVOKE") == 1, (
        f"expected 1 pdf2md subprocess for {nfiles} PDFs"
    )

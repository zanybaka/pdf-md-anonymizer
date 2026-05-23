"""Tests for BatchRunController (UI-010)."""

from __future__ import annotations

import asyncio
import types
from pathlib import Path


def _make_fake_process_files(statuses: list[str]):
    """Return a fake process_files that yields FileResult-like objects."""

    def fake_process_files(inputs, *, output_policy, map_policy, options, cancel, on_stage):
        for i, path in enumerate(inputs):
            path = Path(path)
            s = statuses[i] if i < len(statuses) else "done"
            yield types.SimpleNamespace(
                input_path=str(path),
                output_path=str(path.with_suffix(".anon.md")) if s == "done" else None,
                status=s,
                error="simulated error" if s == "failed" else None,
                duration=float(i + 1),
            )

    return fake_process_files


def test_batch_controller_full_run(tmp_path, monkeypatch):
    """Three-file run (done/failed/cancelled) fires correct callback sequence."""
    import anonymizer_ui.batch_controller as _bc
    from anonymizer_ui.batch_controller import BatchRunController

    paths = [tmp_path / f"file{i}.md" for i in range(3)]
    for p in paths:
        p.write_text("text")

    monkeypatch.setattr(
        _bc, "process_files", _make_fake_process_files(["done", "failed", "cancelled"])
    )

    progress_texts: list[str] = []
    file_results: list = []
    done_calls: list[int] = []
    log_lines: list[str] = []

    async def run() -> None:
        loop = asyncio.get_event_loop()
        ctrl = BatchRunController(
            on_progress=progress_texts.append,
            on_file_result=file_results.append,
            on_done=lambda: done_calls.append(1),
            on_log=log_lines.append,
        )
        for p in paths:
            ctrl.add_input(p)

        from anonymizer.batch import OutputPolicy

        ctrl.start(
            output_policy=OutputPolicy.next_to_input(),
            map_policy=None,
            options=object(),
            loop=loop,
        )

        # Drain until the controller is no longer running.
        deadline = loop.time() + 10
        while ctrl.running and loop.time() < deadline:
            await asyncio.sleep(0.01)

    asyncio.run(run())

    assert [r.status for r in file_results] == ["done", "failed", "cancelled"]
    assert done_calls == [1], "on_done must fire exactly once"
    assert len(progress_texts) >= 3, "on_progress fires at least once per file"
    # done file → output_path stored; others → None or absent
    assert file_results[0].status == "done"
    assert file_results[1].status == "failed"
    assert file_results[2].status == "cancelled"


def test_batch_controller_no_toga_import():
    """BatchRunController must not import Toga (core module)."""
    import sys

    # Ensure module is imported
    import anonymizer_ui.batch_controller  # noqa: F401

    src = sys.modules["anonymizer_ui.batch_controller"].__file__ or ""
    # Check source for toga import
    from pathlib import Path as _P  # noqa: N814

    text = _P(src).read_text(encoding="utf-8")
    assert "import toga" not in text


def test_batch_controller_add_input_deduplicates(tmp_path):
    from anonymizer_ui.batch_controller import _PENDING, BatchRunController

    ctrl = BatchRunController(
        on_progress=lambda _: None,
        on_file_result=lambda _: None,
        on_done=lambda: None,
    )
    p = tmp_path / "a.md"
    assert ctrl.add_input(p) is True
    assert ctrl.add_input(p) is False  # duplicate
    assert ctrl.inputs == [p]
    assert ctrl.status[p] == _PENDING


def test_batch_controller_clear_inputs(tmp_path):
    from anonymizer_ui.batch_controller import BatchRunController

    ctrl = BatchRunController(
        on_progress=lambda _: None,
        on_file_result=lambda _: None,
        on_done=lambda: None,
    )
    p = tmp_path / "a.md"
    ctrl.add_input(p)
    ctrl.clear_inputs()
    assert ctrl.inputs == []
    assert ctrl.status == {}
    assert ctrl.output_paths == {}


def test_batch_controller_stage_log_is_newline_terminated(tmp_path, monkeypatch):
    """Stage updates handed to on_log must end with '\\n' (UI-021).

    Drives the controller through a CONVERTING then DETECTING stage update for
    a single file and asserts every captured log line is newline-terminated so
    consecutive stage updates land on separate rows in the UI log sink (which
    simply concatenates strings). Also asserts that progress_text() — which
    embeds the stage label into a single-line status — does NOT contain a raw
    newline, so the fix doesn't regress the status label.
    """
    import anonymizer_ui.batch_controller as _bc
    from anonymizer.batch import Stage
    from anonymizer_ui.batch_controller import BatchRunController

    p = tmp_path / "doc.pdf"
    p.write_text("text")

    captured_progress_during_stage: list[str] = []

    def fake_process_files(inputs, *, output_policy, map_policy, options, cancel, on_stage):
        for path in inputs:
            on_stage(1, 1, Path(path), Stage.CONVERTING)
            on_stage(1, 1, Path(path), Stage.DETECTING)
            yield types.SimpleNamespace(
                input_path=str(path),
                output_path=str(Path(path).with_suffix(".anon.md")),
                status="done",
                error=None,
                duration=1.0,
            )

    monkeypatch.setattr(_bc, "process_files", fake_process_files)

    log_lines: list[str] = []
    done_calls: list[int] = []

    def _on_progress(text: str) -> None:
        captured_progress_during_stage.append(text)

    async def run() -> None:
        loop = asyncio.get_event_loop()
        ctrl = BatchRunController(
            on_progress=_on_progress,
            on_file_result=lambda _r: None,
            on_done=lambda: done_calls.append(1),
            on_log=log_lines.append,
        )
        ctrl.add_input(p)

        from anonymizer.batch import OutputPolicy

        ctrl.start(
            output_policy=OutputPolicy.next_to_input(),
            map_policy=None,
            options=object(),
            loop=loop,
        )

        deadline = loop.time() + 10
        while ctrl.running and loop.time() < deadline:
            await asyncio.sleep(0.01)

    asyncio.run(run())

    assert done_calls == [1]
    # Two stage updates → at least two log lines, both newline-terminated.
    stage_lines = [line for line in log_lines if "doc.pdf" in line]
    assert len(stage_lines) >= 2, f"expected ≥2 stage log lines, got {log_lines!r}"
    for line in stage_lines:
        assert line.endswith("\n"), f"stage log line missing trailing newline: {line!r}"
    # Concatenated log must not glue two stage updates onto a single row.
    concatenated = "".join(stage_lines)
    assert "…[1/1]" not in concatenated, (
        f"stage updates glued together (missing newline boundary): {concatenated!r}"
    )
    # progress_text() must stay single-line — the status label is one row.
    for text in captured_progress_during_stage:
        assert "\n" not in text, f"progress text leaked newline: {text!r}"


def test_batch_controller_cancel(tmp_path, monkeypatch):
    """cancel() sets the CancelToken so remaining files are skipped."""
    import anonymizer_ui.batch_controller as _bc
    from anonymizer_ui.batch_controller import BatchRunController

    paths = [tmp_path / f"file{i}.md" for i in range(2)]
    for p in paths:
        p.write_text("text")

    def _slow_process_files(inputs, *, output_policy, map_policy, options, cancel, on_stage):
        for path in inputs:
            if cancel.cancelled:
                yield types.SimpleNamespace(
                    input_path=str(path),
                    output_path=None,
                    status="cancelled",
                    error=None,
                    duration=0.0,
                )
            else:
                yield types.SimpleNamespace(
                    input_path=str(path),
                    output_path=str(Path(path).with_suffix(".anon.md")),
                    status="done",
                    error=None,
                    duration=1.0,
                )

    monkeypatch.setattr(_bc, "process_files", _slow_process_files)

    file_results: list = []
    done_calls: list[int] = []

    async def run() -> None:
        loop = asyncio.get_event_loop()
        ctrl = BatchRunController(
            on_progress=lambda _: None,
            on_file_result=file_results.append,
            on_done=lambda: done_calls.append(1),
        )
        for p in paths:
            ctrl.add_input(p)

        from anonymizer.batch import OutputPolicy

        ctrl.start(
            output_policy=OutputPolicy.next_to_input(),
            map_policy=None,
            options=object(),
            loop=loop,
        )
        # Cancel immediately after starting
        ctrl.cancel()

        deadline = loop.time() + 10
        while ctrl.running and loop.time() < deadline:
            await asyncio.sleep(0.01)

    asyncio.run(run())

    assert done_calls == [1]
    assert all(r.status in ("done", "cancelled") for r in file_results)

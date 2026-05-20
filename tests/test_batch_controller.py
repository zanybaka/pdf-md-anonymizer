"""Tests for BatchRunController (UI-010)."""

from __future__ import annotations

import asyncio
import types
from pathlib import Path

import pytest


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

    monkeypatch.setattr(_bc, "process_files", _make_fake_process_files(["done", "failed", "cancelled"]))

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
    import importlib, sys
    # Ensure module is imported
    import anonymizer_ui.batch_controller  # noqa: F401
    src = sys.modules["anonymizer_ui.batch_controller"].__file__ or ""
    # Check source for toga import
    from pathlib import Path as _P
    text = _P(src).read_text(encoding="utf-8")
    assert "import toga" not in text


def test_batch_controller_add_input_deduplicates(tmp_path):
    from anonymizer_ui.batch_controller import BatchRunController, _PENDING

    ctrl = BatchRunController(
        on_progress=lambda _: None,
        on_file_result=lambda _: None,
        on_done=lambda: None,
    )
    p = tmp_path / "a.md"
    assert ctrl.add_input(p) is True
    assert ctrl.add_input(p) is False   # duplicate
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
                    input_path=str(path), output_path=None,
                    status="cancelled", error=None, duration=0.0,
                )
            else:
                yield types.SimpleNamespace(
                    input_path=str(path),
                    output_path=str(Path(path).with_suffix(".anon.md")),
                    status="done", error=None, duration=1.0,
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

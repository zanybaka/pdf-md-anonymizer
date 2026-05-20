"""Batch-run orchestration for the anonymizer desktop UI.

``BatchRunController`` owns all batch-run state and drives
``anonymizer.batch.process_files`` off the UI thread.  It communicates
progress back to the caller via narrow callbacks so the UI layer stays
a thin wrapper of widget updates.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from pathlib import Path

from anonymizer.batch import CancelToken, FileStatus, OutputPolicy, Stage, process_files

_PENDING = "pending"


class BatchRunController:
    """Owns batch state and drives process_files in a worker thread.

    Callbacks are always invoked on the asyncio event loop passed to
    :meth:`start`, so widget updates in AnonymizerApp are on the UI thread.
    """

    def __init__(
        self,
        *,
        on_progress: Callable[[str], None],
        on_file_result: Callable[[object], None],
        on_done: Callable[[], None],
        on_log: Callable[[str], None] = lambda _: None,
    ) -> None:
        self._on_progress = on_progress
        self._on_file_result_cb = on_file_result
        self._on_done_cb = on_done
        self._on_log = on_log

        self.inputs: list[Path] = []
        self.status: dict[Path, str] = {}
        self.output_paths: dict[Path, Path | None] = {}
        self.durations: list[float] = []
        self._cancel: CancelToken | None = None
        self.running = False
        self._start_time = 0.0
        self._stage_text = ""
        self._loop: asyncio.AbstractEventLoop | None = None

    # --- input management -----------------------------------------------

    def add_input(self, path: Path) -> bool:
        """Append *path* if not already present.  Returns True when added."""
        if path not in self.inputs:
            self.inputs.append(path)
            self.status[path] = _PENDING
            return True
        return False

    def clear_inputs(self) -> None:
        self.inputs.clear()
        self.status.clear()
        self.output_paths.clear()

    # --- run lifecycle --------------------------------------------------

    def start(
        self,
        *,
        output_policy: OutputPolicy,
        map_policy: OutputPolicy | None,
        options,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Launch the batch worker thread and the progress-tick coroutine."""
        self._loop = loop
        self._cancel = CancelToken()
        self.running = True
        self.durations = []
        self._stage_text = ""
        self.output_paths = {}
        self._start_time = time.monotonic()
        for path in self.inputs:
            self.status[path] = _PENDING

        threading.Thread(
            target=self._worker,
            args=(list(self.inputs), output_policy, map_policy, options, self._cancel),
            daemon=True,
        ).start()
        asyncio.ensure_future(self._tick())

    def cancel(self) -> None:
        """Signal cooperative cancellation."""
        if self._cancel is not None:
            self._cancel.cancel()

    # --- worker (runs off the UI thread) --------------------------------

    def _worker(self, inputs, output_policy, map_policy, options, cancel) -> None:
        def on_stage(index: int, total: int, path: Path, stage: Stage) -> None:
            label = "converting PDF…" if stage == Stage.CONVERTING else "detecting…"
            text = f"[{index}/{total}] {path.name}: {label}"
            self._loop.call_soon_threadsafe(self._on_stage_update, text)

        for result in process_files(
            inputs,
            output_policy=output_policy,
            map_policy=map_policy,
            options=options,
            cancel=cancel,
            on_stage=on_stage,
        ):
            self._loop.call_soon_threadsafe(self._on_file_result, result)
        self._loop.call_soon_threadsafe(self._on_batch_done)

    def _on_file_result(self, result) -> None:
        path = Path(result.input_path)
        self.status[path] = result.status
        if result.status == FileStatus.DONE:
            self.durations.append(result.duration)
            self.output_paths[path] = (
                Path(result.output_path) if result.output_path else None
            )
        self._on_file_result_cb(result)
        self._on_progress(self.progress_text())

    def _on_batch_done(self) -> None:
        self.running = False
        self._stage_text = ""
        self._on_done_cb()

    def _on_stage_update(self, text: str) -> None:
        self._stage_text = text
        self._on_log(text)
        self._on_progress(self.progress_text())

    async def _tick(self) -> None:
        while self.running:
            self._on_progress(self.progress_text())
            await asyncio.sleep(1)

    # --- read-only helpers ----------------------------------------------

    def processed(self) -> int:
        return sum(
            1 for p in self.inputs if self.status.get(p, _PENDING) != _PENDING
        )

    def progress_text(self) -> str:
        total = len(self.inputs)
        done = self.processed()
        elapsed = time.monotonic() - self._start_time if self.running else 0.0
        text = f"{done}/{total} files, elapsed {elapsed:.0f}s"
        if self.durations and done < total:
            avg = sum(self.durations) / len(self.durations)
            text += f", ETA {avg * (total - done):.0f}s"
        if self._stage_text:
            text += f" — {self._stage_text}"
        return text

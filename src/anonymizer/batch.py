"""Batch processing of multiple input files with observable per-file results."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]  # noqa: UP042
        pass


class FileStatus(StrEnum):
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Stage(StrEnum):
    CONVERTING = "converting"
    DETECTING = "detecting"


# Per-file stage callback: receives a Stage value.
StageCallback = Callable[[Stage], None]
# Batch stage callback: receives (index, total, input_path, stage).
BatchStageCallback = Callable[[int, int, Path, Stage], None]

from anonymizer.api import Options, anonymize  # noqa: E402
from anonymizer.convert import (  # noqa: E402
    ConversionCancelled,
    pdf_batch_to_markdown,
    pdf_to_markdown,
)
from anonymizer.mapping import write_map  # noqa: E402


class CancelToken:
    """Cooperative cancellation flag checked between files and between stages."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


class _Cancelled(Exception):  # noqa: N818
    """Internal: raised by anonymize_file when cancel is set between stages."""


@dataclass
class FileResult:
    """Outcome of processing one input file."""

    input_path: Path
    status: FileStatus
    output_path: Path | None = None
    map_path: Path | None = None
    error: str | None = None
    duration: float = 0.0


def read_input(
    path: str | Path,
    pdf2md_cmd: str | None = None,
    on_stage: StageCallback | None = None,
    cancel: CancelToken | None = None,
) -> str:
    """Read an input file as Markdown, converting ``.pdf`` via ``pdf2md``."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        if on_stage is not None:
            on_stage(Stage.CONVERTING)
        return pdf_to_markdown(
            path,
            pdf2md_cmd,
            cancel=(lambda: cancel.cancelled) if cancel is not None else None,
        )
    return path.read_text(encoding="utf-8")


def anonymize_file(
    input_path: str | Path,
    output_path: str | Path,
    map_path: str | Path | None,
    options: Options,
    pdf2md_cmd: str | None = None,
    on_stage: StageCallback | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Anonymize one file, writing the anonymized text and optional map.

    ``on_stage`` is called with each stage name as it begins.
    Raises ``_Cancelled`` if *cancel* is signalled during or between stages.
    """
    try:
        text = read_input(input_path, pdf2md_cmd, on_stage, cancel)
    except ConversionCancelled:
        raise _Cancelled() from None
    if cancel is not None and cancel.cancelled:
        raise _Cancelled()
    if on_stage is not None:
        on_stage(Stage.DETECTING)
    result = anonymize(text, options)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.text, encoding="utf-8")
    if map_path is not None:
        map_path = Path(map_path)
        map_path.parent.mkdir(parents=True, exist_ok=True)
        write_map(map_path, result.mapping)


class OutputPolicy:
    """Determines where each anonymized output file is written."""

    __slots__ = ("_dir", "_next_to")

    def __init__(self, *, _dir: Path | None, _next_to: bool) -> None:
        self._dir = _dir
        self._next_to = _next_to

    @classmethod
    def into_directory(cls, d: str | Path) -> OutputPolicy:
        """Write all outputs into a fixed directory *d*."""
        return cls(_dir=Path(d), _next_to=False)

    @classmethod
    def next_to_input(cls) -> OutputPolicy:
        """Write each output next to its source file."""
        return cls(_dir=None, _next_to=True)

    def resolve(self, input_path: Path) -> Path:
        """Return the output *directory* for *input_path*."""
        if self._next_to:
            return input_path.parent
        assert self._dir is not None  # noqa: S101
        return self._dir


def _anonymize_text_to_disk(
    text: str,
    output_path: Path,
    map_path: Path | None,
    options: Options,
) -> None:
    """Run the anonymize stage on already-converted *text* and persist outputs."""
    result = anonymize(text, options)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.text, encoding="utf-8")
    if map_path is not None:
        map_path.parent.mkdir(parents=True, exist_ok=True)
        write_map(map_path, result.mapping)


def _index_for(group: list[tuple[int, Path]], path: Path) -> int:
    for idx, p in group:
        if p == path:
            return idx
    return -1


def _resolve_paths(
    path: Path, output_policy: OutputPolicy, map_policy: OutputPolicy | None
) -> tuple[Path, Path | None]:
    """Return ``(.anon.md path, .map.json path or None)`` for *path*."""
    out_path = output_policy.resolve(path) / f"{path.name}.anon.md"
    if map_policy is None:
        return out_path, None
    return out_path, map_policy.resolve(path) / f"{path.name}.map.json"


def _handle_group_file(
    *,
    path: Path,
    payload: str | Exception,
    group: list[tuple[int, Path]],
    total: int,
    output_policy: OutputPolicy,
    map_policy: OutputPolicy | None,
    options: Options,
    on_stage: BatchStageCallback | None,
    starts: dict[Path, float],
    results: list[FileResult],
) -> None:
    """Per-file branch invoked as each PDF leaves the batch converter."""
    out_path, map_path = _resolve_paths(path, output_policy, map_policy)
    if isinstance(payload, Exception):
        results.append(
            FileResult(
                path,
                status=FileStatus.FAILED,
                error=str(payload),
                duration=time.monotonic() - starts[path],
            )
        )
        return
    if on_stage is not None:
        on_stage(_index_for(group, path), total, path, Stage.DETECTING)
    try:
        _anonymize_text_to_disk(payload, out_path, map_path, options)
    except Exception as exc:  # noqa: BLE001 -- per-file failure, batch continues
        results.append(
            FileResult(
                path,
                status=FileStatus.FAILED,
                error=str(exc),
                duration=time.monotonic() - starts[path],
            )
        )
        return
    results.append(
        FileResult(
            path,
            status=FileStatus.DONE,
            output_path=out_path,
            map_path=map_path,
            duration=time.monotonic() - starts[path],
        )
    )


def _fill_missing(
    group: list[tuple[int, Path]],
    results: list[FileResult],
    starts: dict[Path, float],
    *,
    status: FileStatus,
    error: str | None = None,
) -> None:
    """Append a *status* result for every file in *group* not already done."""
    done = {r.input_path for r in results}
    for _, p in group:
        if p in done:
            continue
        results.append(
            FileResult(
                p,
                status=status,
                error=error,
                duration=time.monotonic() - starts[p] if error else 0.0,
            )
        )


def _process_pdf_group(
    group: list[tuple[int, Path]],
    *,
    total: int,
    output_policy: OutputPolicy,
    map_policy: OutputPolicy | None,
    options: Options,
    pdf2md_cmd: str | None,
    cancel: CancelToken | None,
    on_stage: BatchStageCallback | None,
) -> list[FileResult]:
    """Convert a run of consecutive PDFs in one ``pdf2md`` subprocess.

    Anonymization, output writing, and per-file timing happen inside the
    ``on_file`` callback as each PDF leaves the converter — so a Cancel
    between files keeps the .anon.md / .map.json already written and marks
    the rest CANCELLED.  A per-file conversion failure is recorded as
    :attr:`FileStatus.FAILED` and does not abort sibling conversions.
    """
    results: list[FileResult] = []
    starts: dict[Path, float] = {p: time.monotonic() for _, p in group}
    if on_stage is not None:
        for idx, p in group:
            on_stage(idx, total, p, Stage.CONVERTING)

    def on_file(path: Path, payload: str | Exception) -> None:
        _handle_group_file(
            path=path,
            payload=payload,
            group=group,
            total=total,
            output_policy=output_policy,
            map_policy=map_policy,
            options=options,
            on_stage=on_stage,
            starts=starts,
            results=results,
        )

    cancel_fn: Callable[[], bool] | None = (
        (lambda: cancel.cancelled) if cancel is not None else None
    )
    try:
        pdf_batch_to_markdown(
            [p for _, p in group],
            command=pdf2md_cmd,
            cancel=cancel_fn,
            on_file=on_file,
        )
    except ConversionCancelled:
        pass
    except Exception as exc:  # noqa: BLE001 -- spawn-level failure
        # The batch driver itself failed to start (e.g. missing executable).
        # Every file in the group that has no result yet becomes FAILED.
        _fill_missing(group, results, starts, status=FileStatus.FAILED, error=str(exc))
    # Any file the subprocess never delivered (Cancel mid-batch) is CANCELLED.
    _fill_missing(group, results, starts, status=FileStatus.CANCELLED)
    return results


def process_files(
    inputs: Iterable[str | Path],
    *,
    output_policy: OutputPolicy,
    map_policy: OutputPolicy | None = None,
    options: Options | None = None,
    pdf2md_cmd: str | None = None,
    cancel: CancelToken | None = None,
    on_stage: BatchStageCallback | None = None,
) -> Iterator[FileResult]:
    """Anonymize many files, yielding a :class:`FileResult` as each completes.

    Each input ``report.pdf`` produces ``report.pdf.anon.md`` in the directory
    determined by *output_policy*. A ``report.pdf.map.json`` is written only
    when *map_policy* is given (opt-in). A per-file failure is yielded but does
    not abort the rest. If ``cancel`` is signalled, the remaining files are
    yielded as ``cancelled`` without being processed.

    PDF-004: consecutive ``.pdf`` inputs are converted in **one** ``pdf2md``
    subprocess so the Docling model-init cost is paid once per group rather
    than once per file.  A ``.md`` input or end-of-list flushes the current
    group; results are yielded in input order.
    """
    options = options or Options()
    inputs = list(inputs)
    total = len(inputs)

    pdf_group: list[tuple[int, Path]] = []

    def flush() -> Iterator[FileResult]:
        if not pdf_group:
            return
        results = _process_pdf_group(
            pdf_group,
            total=total,
            output_policy=output_policy,
            map_policy=map_policy,
            options=options,
            pdf2md_cmd=pdf2md_cmd,
            cancel=cancel,
            on_stage=on_stage,
        )
        # Preserve input order: the batch driver emits per-file records in the
        # order files were passed in, so sorting by group index is sufficient.
        order = {p: i for i, (_, p) in enumerate(pdf_group)}
        results.sort(key=lambda r: order.get(r.input_path, 0))
        pdf_group.clear()
        yield from results

    for index, raw in enumerate(inputs, start=1):
        input_path = Path(raw)
        if cancel is not None and cancel.cancelled:
            yield from flush()
            yield FileResult(input_path, status=FileStatus.CANCELLED)
            continue
        if input_path.suffix.lower() == ".pdf":
            pdf_group.append((index, input_path))
            continue
        # A non-PDF input flushes the current group, then is handled the
        # original single-file way (text read + anonymize).
        yield from flush()
        yield _process_single_non_pdf(
            input_path,
            index=index,
            total=total,
            output_policy=output_policy,
            map_policy=map_policy,
            options=options,
            pdf2md_cmd=pdf2md_cmd,
            cancel=cancel,
            on_stage=on_stage,
        )
    # End-of-list: flush any remaining PDF group.
    yield from flush()


def _process_single_non_pdf(
    input_path: Path,
    *,
    index: int,
    total: int,
    output_policy: OutputPolicy,
    map_policy: OutputPolicy | None,
    options: Options,
    pdf2md_cmd: str | None,
    cancel: CancelToken | None,
    on_stage: BatchStageCallback | None,
) -> FileResult:
    """One ``.md`` (or other non-PDF) input — the original single-file path."""
    out_path, map_path = _resolve_paths(input_path, output_policy, map_policy)
    file_stage: StageCallback | None = None
    if on_stage is not None:

        def file_stage(stage: Stage, _i: int = index, _p: Path = input_path) -> None:
            on_stage(_i, total, _p, stage)

    start = time.monotonic()
    try:
        anonymize_file(input_path, out_path, map_path, options, pdf2md_cmd, file_stage, cancel)
    except _Cancelled:
        return FileResult(input_path, status=FileStatus.CANCELLED)
    except Exception as exc:  # noqa: BLE001 - reported per file, batch continues
        return FileResult(
            input_path,
            status=FileStatus.FAILED,
            error=str(exc),
            duration=time.monotonic() - start,
        )
    return FileResult(
        input_path,
        status=FileStatus.DONE,
        output_path=out_path,
        map_path=map_path,
        duration=time.monotonic() - start,
    )

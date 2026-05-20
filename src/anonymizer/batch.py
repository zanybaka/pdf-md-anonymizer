"""Batch processing of multiple input files with observable per-file results."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import auto
from pathlib import Path
from typing import Callable, Iterable, Iterator

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
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

from anonymizer.api import Options, anonymize
from anonymizer.convert import ConversionCancelled, pdf_to_markdown
from anonymizer.mapping import dumps_map


class CancelToken:
    """Cooperative cancellation flag checked between files and between stages."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


class _Cancelled(Exception):
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
            path, pdf2md_cmd,
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
        raise _Cancelled()
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
        map_path.write_text(dumps_map(result.mapping), encoding="utf-8")


class OutputPolicy:
    """Determines where each anonymized output file is written."""

    __slots__ = ("_dir", "_next_to")

    def __init__(self, *, _dir: Path | None, _next_to: bool) -> None:
        self._dir = _dir
        self._next_to = _next_to

    @classmethod
    def into_directory(cls, d: str | Path) -> "OutputPolicy":
        """Write all outputs into a fixed directory *d*."""
        return cls(_dir=Path(d), _next_to=False)

    @classmethod
    def next_to_input(cls) -> "OutputPolicy":
        """Write each output next to its source file."""
        return cls(_dir=None, _next_to=True)

    def resolve(self, input_path: Path) -> Path:
        """Return the output *directory* for *input_path*."""
        if self._next_to:
            return input_path.parent
        assert self._dir is not None
        return self._dir


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
    """
    options = options or Options()
    inputs = list(inputs)
    total = len(inputs)

    for index, raw in enumerate(inputs, start=1):
        input_path = Path(raw)
        if cancel is not None and cancel.cancelled:
            yield FileResult(input_path, status=FileStatus.CANCELLED)
            continue
        out_dir = output_policy.resolve(input_path)
        map_dir_resolved = map_policy.resolve(input_path) if map_policy is not None else None
        out_path = out_dir / f"{input_path.name}.anon.md"
        map_path = (map_dir_resolved / f"{input_path.name}.map.json") if map_dir_resolved is not None else None
        file_stage: StageCallback | None = None
        if on_stage is not None:
            def file_stage(stage: Stage, _i: int = index, _p: Path = input_path) -> None:
                on_stage(_i, total, _p, stage)
        start = time.monotonic()
        try:
            anonymize_file(input_path, out_path, map_path, options, pdf2md_cmd, file_stage, cancel)
        except _Cancelled:
            yield FileResult(input_path, status=FileStatus.CANCELLED)
            continue
        except Exception as exc:  # noqa: BLE001 - reported per file, batch continues
            yield FileResult(
                input_path,
                status=FileStatus.FAILED,
                error=str(exc),
                duration=time.monotonic() - start,
            )
            continue
        yield FileResult(
            input_path,
            status=FileStatus.DONE,
            output_path=out_path,
            map_path=map_path,
            duration=time.monotonic() - start,
        )

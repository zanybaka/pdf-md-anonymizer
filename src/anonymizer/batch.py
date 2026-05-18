"""Batch processing of multiple input files with observable per-file results."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Union

# Per-file stage callback: receives a stage name ("converting", "detecting").
StageCallback = Callable[[str], None]
# Batch stage callback: receives (index, total, input_path, stage).
BatchStageCallback = Callable[[int, int, Path, str], None]

from anonymizer.api import Options, anonymize
from anonymizer.convert import pdf_to_markdown
from anonymizer.mapping import dumps_map


class CancelToken:
    """Cooperative cancellation flag checked between files."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


@dataclass
class FileResult:
    """Outcome of processing one input file."""

    input_path: Path
    status: str  # "done" | "failed" | "cancelled"
    output_path: Path | None = None
    map_path: Path | None = None
    error: str | None = None
    duration: float = 0.0


def read_input(
    path: str | Path,
    pdf2md_cmd: str | None = None,
    on_stage: StageCallback | None = None,
) -> str:
    """Read an input file as Markdown, converting ``.pdf`` via ``pdf2md``."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        if on_stage is not None:
            on_stage("converting")
        return pdf_to_markdown(path, pdf2md_cmd)
    return path.read_text(encoding="utf-8")


def anonymize_file(
    input_path: str | Path,
    output_path: str | Path,
    map_path: str | Path | None,
    options: Options,
    pdf2md_cmd: str | None = None,
    on_stage: StageCallback | None = None,
) -> None:
    """Anonymize one file, writing the anonymized text and optional map.

    ``on_stage`` is called with each stage name as it begins.
    """
    text = read_input(input_path, pdf2md_cmd, on_stage)
    if on_stage is not None:
        on_stage("detecting")
    result = anonymize(text, options)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.text, encoding="utf-8")
    if map_path is not None:
        map_path = Path(map_path)
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(dumps_map(result.mapping), encoding="utf-8")


# output_dir / map_dir accept either a fixed Path or a per-file callable.
OutputDirArg = Union[str, Path, Callable[[Path], Path]]


def _resolve_dir(arg: OutputDirArg, input_path: Path) -> Path:
    return Path(arg(input_path)) if callable(arg) else Path(arg)


def process_files(
    inputs: Iterable[str | Path],
    *,
    output_dir: OutputDirArg,
    map_dir: OutputDirArg | None = None,
    options: Options | None = None,
    pdf2md_cmd: str | None = None,
    cancel: CancelToken | None = None,
    on_stage: BatchStageCallback | None = None,
) -> Iterator[FileResult]:
    """Anonymize many files, yielding a :class:`FileResult` as each completes.

    Each input ``report.pdf`` produces ``report.pdf.anon.md`` in the target
    directory — the original extension is kept so same-stem inputs do not
    collide. A ``report.pdf.map.json`` is written only when ``map_dir`` is
    given (opt-in). A per-file failure is yielded but does not abort the rest.
    If ``cancel`` is signalled, the remaining files are yielded as
    ``cancelled`` without being processed. ``on_stage`` is called as
    ``(index, total, input_path, stage)`` when each stage begins.
    ``output_dir`` and ``map_dir`` may be a callable ``(input_path) -> dir``
    to place each output next to its source.
    """
    options = options or Options()
    inputs = list(inputs)
    total = len(inputs)

    for index, raw in enumerate(inputs, start=1):
        input_path = Path(raw)
        if cancel is not None and cancel.cancelled:
            yield FileResult(input_path, status="cancelled")
            continue
        out_dir = _resolve_dir(output_dir, input_path)
        map_dir_resolved = _resolve_dir(map_dir, input_path) if map_dir is not None else None
        out_path = out_dir / f"{input_path.name}.anon.md"
        map_path = (map_dir_resolved / f"{input_path.name}.map.json") if map_dir_resolved is not None else None
        file_stage: StageCallback | None = None
        if on_stage is not None:
            def file_stage(stage: str, _i: int = index, _p: Path = input_path) -> None:
                on_stage(_i, total, _p, stage)
        start = time.monotonic()
        try:
            anonymize_file(input_path, out_path, map_path, options, pdf2md_cmd, file_stage)
        except Exception as exc:  # noqa: BLE001 - reported per file, batch continues
            yield FileResult(
                input_path,
                status="failed",
                error=str(exc),
                duration=time.monotonic() - start,
            )
            continue
        yield FileResult(
            input_path,
            status="done",
            output_path=out_path,
            map_path=map_path,
            duration=time.monotonic() - start,
        )

"""Subprocess wrapper over the external ``pdf2md`` converter."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path


class ConversionError(RuntimeError):
    """Raised when PDF-to-Markdown conversion fails."""


class ConversionCancelled(ConversionError):  # noqa: N818
    """Raised when pdf conversion is interrupted by a cancel signal."""


# A hyphenated word wrapped across a line by pdf2md: a word character, a
# hyphen, the newline, optional continuation-line indentation, then a word
# character. A space before the newline (a standalone " - " dash) or a
# missing word character (a "- item" list marker, an em-dash bullet) does not
# match, so only true hyphenated words are rejoined.
_HYPHEN_LINEBREAK = re.compile(r"(\w)-\n[^\S\n]*(\w)")


def rejoin_hyphenated_linebreaks(markdown: str) -> str:
    """Rejoin words split across a line break by a trailing hyphen.

    ``pdf2md`` wraps a hyphenated word across two lines (``Сло-\\nво``);
    left alone, NER tags it across the newline and one entity becomes two
    tokens. Collapsing it here makes the cleaned Markdown the canonical text
    that ``anonymize`` and ``restore`` both operate on.
    """
    return _HYPHEN_LINEBREAK.sub(r"\1-\2", markdown)


# A hyphen padded with at least one inline space — pdf2md space-pads
# punctuation, so a hyphenated name written "Слово-Слово" arrives as
# "Слово - Слово" or, inconsistently, "Слово -Слово". A word character
# is required on both sides, so a list marker or an em-dash bullet is left
# alone; a genuine joined compound ("кто-то", "e-mail") has no padding and is
# untouched.
_PADDED_HYPHEN = re.compile(r"(\w)(?:[^\S\n]+-[^\S\n]*|[^\S\n]*-[^\S\n]+)(\w)")


def normalize_hyphen_spacing(markdown: str) -> str:
    """Collapse a space-padded hyphen to a consistent ``word - word`` form.

    ``pdf2md`` pads the hyphen inside a hyphenated name with spaces, and does
    so inconsistently (``Слово - Слово`` vs ``Слово -Слово``). Natasha tags the
    two spellings differently — for the glued variant it misses the second
    half entirely. Normalizing every padded hyphen to ``" - "`` makes NER tag
    each occurrence the same way; the NER layer then merges the two halves back
    into one entity (a real ``слово - слово`` separator stays split because its
    right half is not an entity). Genuine joined compounds have no padding and
    are left alone.
    """
    return _PADDED_HYPHEN.sub(r"\1 - \2", markdown)


def _user_backend_pdf2md() -> Path:
    """Return the expected pdf2md path in the first-use-installed backend venv.

    The desktop ``.app`` installs the PDF backend on first use into a
    user-writable support directory (ADR-0008 / UI-002). This function returns
    the expected script location so :func:`default_pdf2md_command` can include
    it in the resolution chain.
    """
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "pdf-md-anonymizer"
        / "pdf-backend"
        / "bin"
        / "pdf2md"
    )


def default_pdf2md_command() -> str:
    """Resolve the default ``pdf2md`` executable.

    Resolution order (first match wins):

    1. Env-local: ``pdf2md`` alongside the running interpreter — the ``[pdf]``
       extra lands in this same venv / ``uv tool`` env, so a system-wide
       ``pdf2md`` is never picked up.
    2. First-use-installed backend: the venv the desktop ``.app`` creates on
       first PDF use in the user Application Support directory (ADR-0008).
    3. ``PATH``: final fallback for PDF-001 ``pdf2md``-on-PATH behaviour.
    """
    env_local = Path(sys.prefix) / "bin" / "pdf2md"
    if env_local.is_file():
        return str(env_local)
    user_backend = _user_backend_pdf2md()
    if user_backend.is_file():
        return str(user_backend)
    return "pdf2md"


def _spawn_pdf2md(command: str, path: str | Path) -> subprocess.Popen[str]:
    try:
        return subprocess.Popen(
            [command, str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise ConversionError(f"failed to run {command!r}: {exc}") from exc


def _wait_for_pdf2md(
    proc: subprocess.Popen[str],
    command: str,
    path: str | Path,
    cancel: Callable[[], bool] | None,
) -> str:
    try:
        while True:
            try:
                stdout, _ = proc.communicate(timeout=0.2)
                return stdout
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel():
                    proc.kill()
                    proc.communicate()
                    msg = f"{command!r} cancelled for {Path(path).name}"
                    raise ConversionCancelled(msg) from None
    except ConversionCancelled:
        raise
    except OSError as exc:
        raise ConversionError(f"failed to run {command!r}: {exc}") from exc


def pdf_to_markdown(
    path: str | Path,
    command: str | None = None,
    cancel: Callable[[], bool] | None = None,
) -> str:
    """Convert a PDF file to Markdown by running the external ``pdf2md`` CLI.

    ``command`` overrides the executable name; when omitted the env-local
    ``pdf2md`` is preferred (see :func:`default_pdf2md_command`). A missing
    executable or a non-zero exit raises :class:`ConversionError` naming the
    command. If ``cancel`` is provided it is polled every 200 ms; when it
    returns ``True`` the subprocess is killed and :class:`ConversionCancelled`
    is raised.
    """
    if command is None:
        command = default_pdf2md_command()
    if shutil.which(command) is None:
        raise ConversionError(
            f"pdf2md executable not found: {command!r} (install it or pass --pdf2md-cmd)"
        )
    proc = _spawn_pdf2md(command, path)
    stdout = _wait_for_pdf2md(proc, command, path, cancel)
    if proc.returncode != 0:
        raise ConversionError(
            f"{command!r} exited with code {proc.returncode} for {Path(path).name}"
        )
    return _postprocess_markdown(stdout)


def _postprocess_markdown(markdown: str) -> str:
    """Apply PDF-003 hyphen post-processing to one converted Markdown string."""
    return normalize_hyphen_spacing(rejoin_hyphenated_linebreaks(markdown))


# --- PDF-004: batched conversion ------------------------------------------
#
# The driver is a tiny Python program that runs inside the same interpreter
# that ships ``pdf2md`` (resolved from the script's shebang). It builds **one**
# Docling ``DocumentConverter`` (via ``pdf_to_markdown.cli.create_docling_converter``)
# and reuses it for every PDF, paying the model-initialisation cost just once.
#
# The driver writes one Markdown file per input into a caller-provided temp
# directory and emits one JSON manifest line per file to stdout as each
# conversion finishes (or fails). The parent process reads stdout line by
# line, opens the per-file Markdown, runs PDF-003 post-processing, and hands
# the result to ``on_file`` — so cancellation between files and per-file
# error reporting both work without buffering the whole batch.
#
# Note: the import statement below is constructed at runtime as a string
# (it lives in the driver, not in this module). ``src/anonymizer/`` itself
# performs no ``import pdf_to_markdown`` — ADR-0002's subprocess boundary
# stays intact.
_PDF2MD_PKG = "pdf_to_markdown"

_BATCH_DRIVER_TEMPLATE = """\
import json, sys
from pathlib import Path
from {pkg}.cli import create_docling_converter, convert_with_converter

out_dir = Path(sys.argv[1])
paths = [Path(p) for p in sys.argv[2:]]
converter = create_docling_converter()
for i, p in enumerate(paths):
    out = out_dir / (str(i) + ".md")
    try:
        md = convert_with_converter(p, converter)
    except BaseException as exc:
        rec = {{"index": i, "path": str(p), "status": "error",
                "error": type(exc).__name__ + ": " + str(exc)}}
    else:
        out.write_text(md, encoding="utf-8")
        rec = {{"index": i, "path": str(p), "status": "ok", "output": str(out)}}
    sys.stdout.write(json.dumps(rec) + chr(10))
    sys.stdout.flush()
"""


_PATCHED_SYSPATH_RE = re.compile(
    r"sys\.path\.insert\(\s*0\s*,\s*['\"]([^'\"]+)['\"]\)\s*#\s*_pdf_md_anon"
)


def _parse_shebang_interp(first_line: bytes) -> str | None:
    """Extract the Python interpreter from a ``#!`` shebang line, or return None."""
    if not first_line.startswith(b"#!"):
        return None
    try:
        line = first_line[2:].decode("utf-8", errors="replace").strip()
    except UnicodeError:
        return None
    parts = line.split()
    if not parts:
        return None
    interp = parts[0]
    if interp.endswith("env") and len(parts) >= 2:
        interp = parts[1]
    return interp if "python" in Path(interp).name else None


def _scan_extra_paths(lines: list[bytes]) -> list[str]:
    """Return paths from ``# _pdf_md_anon`` sys.path.insert sentinels in *lines*."""
    paths: list[str] = []
    for raw in lines:
        m = _PATCHED_SYSPATH_RE.search(raw.decode("utf-8", errors="replace"))
        if m:
            paths.append(m.group(1))
    return paths


def _resolve_pdf2md_python(command: str) -> tuple[str, list[str]] | None:
    """Return ``(interpreter, extra_sys_paths)`` for *command*, or ``None``.

    Reads the shebang of the resolved *command* script to find the Python
    interpreter.  Also scans the first 20 lines for ``sys.path.insert``
    sentinels added by ``_patch_pdf2md_script`` so the batch driver can
    find ``pdf_to_markdown`` when it is installed to a non-standard prefix
    (e.g. the first-use backend in Application Support).
    """
    resolved = shutil.which(command)
    if resolved is None:
        return None
    try:
        with open(resolved, "rb") as fh:  # noqa: PTH123
            header = fh.read(4096)
    except OSError:
        return None
    lines = header.split(b"\n", 20)
    interp = _parse_shebang_interp(lines[0]) if lines else None
    if interp is None:
        return None
    return interp, _scan_extra_paths(lines[1:])


def _spawn_batch_driver(
    pdf2md_python: str,
    extra_sys_paths: list[str],
    out_dir: Path,
    paths: Sequence[Path],
) -> subprocess.Popen[str]:
    script = _BATCH_DRIVER_TEMPLATE.format(pkg=_PDF2MD_PKG)
    cmd = [pdf2md_python, "-c", script, str(out_dir), *(str(p) for p in paths)]
    env: dict[str, str] | None = None
    if extra_sys_paths:
        parts = (
            [*extra_sys_paths, os.environ["PYTHONPATH"]]
            if "PYTHONPATH" in os.environ
            else extra_sys_paths
        )
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(parts)}
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered so the parent sees per-file records ASAP
            env=env,
        )
    except OSError as exc:
        raise ConversionError(f"failed to run pdf2md batch driver: {exc}") from exc


def _parse_record(line: str, n_paths: int) -> dict[str, object] | None:
    """Parse one manifest line; return None if it is unusable."""
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    if not isinstance(rec, dict):
        return None
    idx = rec.get("index")
    if not isinstance(idx, int) or idx < 0 or idx >= n_paths:
        return None
    return rec


def _deliver_record(
    rec: dict[str, object],
    path: Path,
    on_file: Callable[[Path, str | Exception], None],
) -> None:
    """Hand one parsed manifest record to *on_file* (success or failure)."""
    if rec.get("status") == "ok":
        output = rec.get("output")
        if not isinstance(output, str):
            on_file(path, ConversionError("pdf2md batch returned no output path"))
            return
        out_path = Path(output)
        try:
            raw = out_path.read_text(encoding="utf-8")
        except OSError as exc:
            on_file(path, ConversionError(f"failed to read batch output: {exc}"))
            return
        with contextlib.suppress(OSError):
            out_path.unlink()
        on_file(path, _postprocess_markdown(raw))
    else:
        err = rec.get("error", "unknown error")
        on_file(path, ConversionError(f"pdf2md batch failed for {path.name}: {err}"))


def _finalize_proc(proc: subprocess.Popen[str]) -> None:
    """Drain remaining stderr/exit code; kill if it does not exit promptly."""
    try:
        proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()


def _process_one_line(
    line: str,
    paths: Sequence[Path],
    on_file: Callable[[Path, str | Exception], None] | None,
) -> bool:
    """Parse + dispatch one manifest line. Return True if it counted as a record."""
    rec = _parse_record(line, len(paths))
    if rec is None:
        return False
    idx = rec["index"]
    assert isinstance(idx, int)  # noqa: S101 -- guaranteed by _parse_record
    path = paths[idx]
    if on_file is not None:
        _deliver_record(rec, path, on_file)
    return True


def _drain_batch(
    proc: subprocess.Popen[str],
    paths: Sequence[Path],
    out_dir: Path,
    cancel: Callable[[], bool] | None,
    on_file: Callable[[Path, str | Exception], None] | None,
) -> int:
    """Read one JSON record per finished PDF, dispatch to *on_file*.

    Returns the number of records consumed.  Honours *cancel* between files —
    when it fires, the subprocess is killed and the loop exits.  Per-file
    errors are reported via ``on_file(path, exception)`` and do not abort the
    rest of the batch (CLI-001).
    """
    assert proc.stdout is not None  # noqa: S101 -- Popen() configured it above
    consumed = 0
    cancelled = cancel if cancel is not None else (lambda: False)
    for raw_line in proc.stdout:
        line = raw_line.strip()
        if not line:
            continue
        if cancelled():
            proc.kill()
            break
        if _process_one_line(line, paths, on_file):
            consumed += 1
        if cancelled():
            proc.kill()
            break
    _finalize_proc(proc)
    return consumed


def pdf_batch_to_markdown(
    paths: Sequence[str | Path],
    command: str | None = None,
    cancel: Callable[[], bool] | None = None,
    on_file: Callable[[Path, str | Exception], None] | None = None,
) -> None:
    """Convert several PDFs in one ``pdf2md`` subprocess.

    The Docling model is loaded **once** in the child process and reused for
    every input, so a batch of ``N`` PDFs costs roughly
    ``init + N × per_file_convert`` wall-clock instead of
    ``N × (init + per_file_convert)``.

    Per-file Markdown is post-processed with
    :func:`rejoin_hyphenated_linebreaks` + :func:`normalize_hyphen_spacing`
    and handed to *on_file* as each PDF finishes — the caller writes outputs
    incrementally, which is what makes cancellation and per-file failure
    handling work.

    If *on_file* is omitted the conversions still run; results are simply
    discarded.  Per-file failures inside the batch subprocess are reported via
    ``on_file(path, exception)`` and do **not** abort the remaining files
    (CLI-001 invariant).  When ``cancel()`` returns ``True`` between files the
    subprocess is killed and the function returns; outputs already passed to
    *on_file* are kept by the caller.

    If the resolved ``pdf2md`` cannot host the batch driver (no Python shebang,
    older build without ``create_docling_converter``), the function falls back
    to a per-file loop calling :func:`pdf_to_markdown` so callers always make
    progress.
    """
    pdf_paths = [Path(p) for p in paths]
    if not pdf_paths:
        return
    if command is None:
        command = default_pdf2md_command()
    if shutil.which(command) is None:
        raise ConversionError(
            f"pdf2md executable not found: {command!r} (install it or pass --pdf2md-cmd)"
        )
    resolved = _resolve_pdf2md_python(command)
    if resolved is None:
        _pdf_batch_fallback(pdf_paths, command, cancel, on_file)
        return
    pdf2md_python, extra_sys_paths = resolved

    with tempfile.TemporaryDirectory(prefix="pdf2md-batch-") as tmp:
        out_dir = Path(tmp)
        proc = _spawn_batch_driver(pdf2md_python, extra_sys_paths, out_dir, pdf_paths)
        try:
            consumed = _drain_batch(proc, pdf_paths, out_dir, cancel, on_file)
        except BaseException:
            proc.kill()
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                proc.communicate(timeout=5)
            raise
    # If the driver could not start (e.g. older pdf2md without
    # create_docling_converter) it exits non-zero before any record is emitted.
    # Detect this and fall back per-file so the caller still gets results.
    if consumed == 0 and proc.returncode not in (0, -9, -15):
        _pdf_batch_fallback(pdf_paths, command, cancel, on_file)


def _pdf_batch_fallback(
    paths: Sequence[Path],
    command: str,
    cancel: Callable[[], bool] | None,
    on_file: Callable[[Path, str | Exception], None] | None,
) -> None:
    """Per-file fallback when the batch driver is unavailable.

    Iterates *paths*, calling :func:`pdf_to_markdown` on each and forwarding
    the result (or exception) to *on_file*.  Honours *cancel* between files;
    a per-file failure is reported and does not abort the rest.
    """
    for path in paths:
        if cancel is not None and cancel():
            return
        try:
            md = pdf_to_markdown(path, command=command, cancel=cancel)
        except ConversionCancelled:
            return
        except Exception as exc:  # noqa: BLE001 -- reported per file
            if on_file is not None:
                on_file(path, exc)
            continue
        if on_file is not None:
            on_file(path, md)

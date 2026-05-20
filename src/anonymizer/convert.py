"""Subprocess wrapper over the external ``pdf2md`` converter."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable


class ConversionError(RuntimeError):
    """Raised when PDF-to-Markdown conversion fails."""


class ConversionCancelled(ConversionError):
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
_PADDED_HYPHEN = re.compile(
    r"(\w)(?:[^\S\n]+-[^\S\n]*|[^\S\n]*-[^\S\n]+)(\w)"
)


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
    try:
        proc = subprocess.Popen(
            [command, str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise ConversionError(f"failed to run {command!r}: {exc}") from exc
    stdout = stderr = ""
    try:
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel():
                    proc.kill()
                    proc.communicate()
                    raise ConversionCancelled(f"{command!r} cancelled for {Path(path).name}")
    except ConversionCancelled:
        raise
    except OSError as exc:
        raise ConversionError(f"failed to run {command!r}: {exc}") from exc
    if proc.returncode != 0:
        raise ConversionError(
            f"{command!r} exited with code {proc.returncode} for {Path(path).name}"
        )
    return normalize_hyphen_spacing(rejoin_hyphenated_linebreaks(stdout))

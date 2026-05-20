"""First-use install of the pdf-to-markdown backend for the desktop .app.

The desktop ``.app`` ships lean — the docling stack is not bundled (ADR-0008).
When the user opens a PDF and no usable ``pdf2md`` is found, this module
installs the backend on demand into
``~/Library/Application Support/pdf-md-anonymizer/pdf-backend/``.

Install strategy
----------------
:func:`install` and :func:`update` both run ``pip install --prefix <dir>``.
:func:`install` installs from the git reference; :func:`update` adds
``--upgrade`` to pull the latest revision.

Inside a Briefcase ``.app``, ``sys.executable`` is the Cocoa launcher and
cannot be used as a Python interpreter.  ``pdf-to-markdown`` is built from
source (no PyPI wheel), so pip needs a real Python for build isolation.
:func:`_find_build_python` locates a system ``python3`` outside the bundle and
:class:`SubprocessPipRunner` runs pip as an **external subprocess** using that
interpreter — the entire pip session (including build isolation) runs in one
consistent Python version with no conflicts.

In a dev venv ``sys.executable`` is already a real interpreter, so pip is
called in-process (loaded from ``ensurepip``'s bundled wheel) for speed.

A system Python (Homebrew or Xcode CLT) is required for install/update inside
the ``.app``.  After install all PDF conversions run fully offline.
"""

from __future__ import annotations

import contextlib
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

# Same git reference as [project.optional-dependencies].pdf in pyproject.toml.
_PDF_BACKEND_URL = (
    "pdf-to-markdown"
    " @ git+https://github.com/zanybaka/pdf-to-markdown@backend/docling"
)

_PACKAGE_NAME = "pdf-to-markdown"


def backend_dir() -> Path:
    """Return the user-writable install prefix for the first-use PDF backend."""
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "pdf-md-anonymizer"
        / "pdf-backend"
    )


def pdf2md_path() -> Path:
    """Return the expected ``pdf2md`` script path inside the backend prefix."""
    return backend_dir() / "bin" / "pdf2md"


def is_installed() -> bool:
    """Return ``True`` if the PDF backend is installed and ``pdf2md`` is present."""
    return pdf2md_path().is_file()


def can_install() -> bool:
    """Return ``True`` when a suitable Python is available to run pip.

    Inside a Briefcase ``.app`` a system Python ≥ 3.11 is required.
    Outside the bundle (dev venv, CLI install) ``sys.executable`` is usable
    directly, so pip is always available.
    """
    return _find_build_python() is not None or ".app/Contents/MacOS/" not in sys.executable


def needs_setuptools_repair() -> bool:
    """Return ``True`` when the backend is installed but missing setuptools.

    Called once at startup to decide whether to run the repair thread.
    """
    return is_installed() and not _has_setuptools()


def installed_version() -> str | None:
    """Return the installed ``pdf-to-markdown`` version string, or ``None``."""
    sp = _find_site_packages(backend_dir())
    if sp is None:
        return None
    for d in sp.glob("pdf_to_markdown-*.dist-info"):
        # name format: pdf_to_markdown-{version}.dist-info
        stem = d.name[: -len(".dist-info")]
        parts = stem.split("-", 1)
        if len(parts) == 2:
            return parts[1]
    return None


def _has_setuptools() -> bool:
    """Return True if setuptools (which provides pkg_resources) is in the prefix."""
    sp = _find_site_packages(backend_dir())
    if sp is None:
        return False
    return any(sp.glob("setuptools-*.dist-info"))


def ensure_setuptools() -> None:
    """Install setuptools into the backend prefix if it is missing.

    Older installs predate the setuptools requirement; this repairs them
    silently at app startup without a full Update.
    """
    if not is_installed() or _has_setuptools():
        return
    prefix = backend_dir()
    pip_args = ["install", "--prefix", str(prefix), "--no-cache-dir", "setuptools"]
    _make_runner().run(pip_args, on_line=None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MIN_PYTHON = (3, 11)  # pdf-to-markdown requires-python = ">=3.11"


def _find_build_python() -> str | None:
    """Return a real Python interpreter (>= 3.11) for running pip.

    Returns ``None`` when ``sys.executable`` is already a real interpreter
    (dev venv, CLI install).  Inside a Briefcase ``.app`` ``sys.executable``
    is the Cocoa launcher; this function searches PATH and common macOS
    install locations for a suitable Python, skipping any version below
    ``_MIN_PYTHON`` (e.g. the macOS system Python 3.9 from Xcode CLT).
    """
    if ".app/Contents/MacOS/" not in sys.executable:
        return None

    candidates = [
        shutil.which("python3"),
        "/opt/homebrew/bin/python3",   # Apple-Silicon Homebrew
        "/usr/local/bin/python3",      # Intel Homebrew / manual install
        "/usr/bin/python3",            # macOS system Python (Xcode CLT) — often 3.9
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and _python_version_ok(candidate):
            return candidate
    return None


def _python_version_ok(python: str) -> bool:
    """Return True if *python* reports a version >= ``_MIN_PYTHON``."""
    import subprocess
    try:
        out = subprocess.check_output(
            [python, "-c",
             f"import sys; exit(0 if sys.version_info >= {_MIN_PYTHON!r} else 1)"],
            timeout=5,
        )
        return True
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return False


def _find_pip_wheel() -> str:
    """Return the path to the pip wheel bundled inside ``ensurepip``."""
    import ensurepip  # noqa: PLC0415

    bundled = Path(ensurepip.__file__).parent / "_bundled"
    wheels = sorted(bundled.glob("pip-*.whl"))
    if not wheels:
        raise RuntimeError(
            "No pip wheel found in ensurepip._bundled. "
            "This Python installation does not include ensurepip."
        )
    return str(wheels[-1])


class _LineWriter:
    """Write-only file-like object that forwards complete lines to a callback."""

    def __init__(self, callback: Callable[[str], None]) -> None:
        self._cb = callback
        self._buf = ""

    def write(self, text: str) -> int:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._cb(line)
        return len(text)

    def flush(self) -> None:
        if self._buf:
            self._cb(self._buf)
            self._buf = ""

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        raise OSError("_LineWriter has no fileno")


def resolve_cert() -> Path | None:
    """Return a CA bundle path for pip SSL verification, or ``None``."""
    system_cert = Path("/etc/ssl/cert.pem")
    if system_cert.exists():
        return system_cert
    try:
        import certifi  # noqa: PLC0415
        return Path(certifi.where())
    except ImportError:
        return None


def _ssl_cert_args() -> list[str]:
    cert = resolve_cert()
    return ["--cert", str(cert)] if cert else []


# ---------------------------------------------------------------------------
# PipRunner protocol and implementations
# ---------------------------------------------------------------------------

@runtime_checkable
class PipRunner(Protocol):
    def run(
        self, args: list[str], on_line: Callable[[str], None] | None
    ) -> None: ...


class InProcessPipRunner:
    """Runs pip in-process using the ensurepip bundled wheel."""

    def __init__(self) -> None:
        self._path_patched = False

    def run(
        self, args: list[str], on_line: Callable[[str], None] | None = None
    ) -> None:
        if not self._path_patched:
            pip_wheel = _find_pip_wheel()
            if pip_wheel not in sys.path:
                sys.path.insert(0, pip_wheel)
            self._path_patched = True

        from pip._internal.cli.main import main as _pip_main  # noqa: PLC0415

        full_args = args + _ssl_cert_args()
        if on_line:
            writer = _LineWriter(on_line)
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                exit_code = _pip_main(full_args)
            writer.flush()
        else:
            exit_code = _pip_main(full_args)
        if exit_code != 0:
            raise RuntimeError(f"pip exited with code {exit_code}")


class SubprocessPipRunner:
    """Runs pip as an external subprocess via a given Python interpreter."""

    def __init__(self, python_path: str) -> None:
        self._python = python_path

    def run(
        self, args: list[str], on_line: Callable[[str], None] | None = None
    ) -> None:
        import subprocess  # noqa: PLC0415

        cmd = [self._python, "-m", "pip"] + args + _ssl_cert_args()
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
        except OSError as exc:
            raise RuntimeError(f"failed to run pip: {exc}") from exc
        if proc.stdout:
            for line in proc.stdout:
                if on_line:
                    on_line(line.rstrip())
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"pip exited with code {proc.returncode}")


def _make_runner() -> InProcessPipRunner | SubprocessPipRunner:
    """Return the appropriate pip runner for this environment."""
    build_python = _find_build_python()
    if build_python is None and ".app/Contents/MacOS/" in sys.executable:
        raise RuntimeError(
            "No Python 3 interpreter found outside the app bundle. "
            "Install Python via Homebrew (brew install python3) or https://python.org."
        )
    if build_python:
        return SubprocessPipRunner(build_python)
    return InProcessPipRunner()


# ---------------------------------------------------------------------------
# Backend-specific install / update helpers
# ---------------------------------------------------------------------------

def install_backend(
    runner: PipRunner, on_line: Callable[[str], None] | None = None
) -> None:
    """Install the pdf-to-markdown backend using *runner*."""
    prefix = backend_dir()
    prefix.mkdir(parents=True, exist_ok=True)
    if on_line:
        on_line(f"Installing {_PACKAGE_NAME} (this may take a few minutes)…")
    pip_args = [
        "install", "--prefix", str(prefix), "--no-cache-dir",
        "setuptools", _PDF_BACKEND_URL,
    ]
    runner.run(pip_args, on_line)
    _finalize_install(prefix, on_line)


def update_backend(
    runner: PipRunner, on_line: Callable[[str], None] | None = None
) -> None:
    """Update the pdf-to-markdown backend using *runner*."""
    prefix = backend_dir()
    prefix.mkdir(parents=True, exist_ok=True)
    if on_line:
        on_line(f"Updating {_PACKAGE_NAME} (this may take a few minutes)…")
    pip_args = [
        "install", "--prefix", str(prefix), "--no-cache-dir", "--upgrade",
        "setuptools", _PDF_BACKEND_URL,
    ]
    runner.run(pip_args, on_line)
    _finalize_install(prefix, on_line)


def _finalize_install(prefix: Path, on_line: Callable[[str], None] | None) -> None:
    """Post-install cleanup + smoke-test-driven script patching.

    Runs in this order:
    1. Strip orphan ``lib/pythonX.Y/`` directories left behind by previous
       installs against now-uninstalled Python versions (e.g. after a Homebrew
       upgrade of ``python3``). Without this, every system-Python bump leaves
       a stale empty subtree in the backend prefix forever.
    2. Write the minimal ``sys.path.insert`` patch into ``pdf2md`` so it can
       find the freshly installed packages.
    3. Run a tiny in-process conversion smoke test. If it fails on the docling
       MPS+float64 limitation, rewrite the script with the MPS-disable shim
       added — otherwise leave the script clean so an upstream fix would
       restore GPU acceleration automatically.
    """
    _clean_orphan_python_dirs(prefix, on_line)
    _patch_pdf2md_script(prefix, with_mps_shim=False)
    if on_line:
        on_line("Verifying PDF conversion…")
    ok, reason = _smoke_test(prefix)
    if not ok:
        if on_line:
            on_line(f"Smoke test failed ({reason}); enabling CPU shim in pdf2md")
        _patch_pdf2md_script(prefix, with_mps_shim=True)
    elif on_line:
        on_line("Smoke test passed; pdf2md left at default (GPU-enabled if available)")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def install(on_line: Callable[[str], None] | None = None) -> None:
    """Install the pdf-to-markdown backend from git."""
    install_backend(_make_runner(), on_line)


def update(on_line: Callable[[str], None] | None = None) -> None:
    """Update the PDF backend to the latest revision from git."""
    update_backend(_make_runner(), on_line)


def _find_site_packages(prefix: Path) -> Path | None:
    """Return the site-packages directory under the install prefix, or None.

    Prefers the directory that actually contains the ``pdf_to_markdown`` package
    so an update that installs to a different Python version is handled correctly.
    Falls back to the highest-version directory if none holds the package yet.
    """
    lib = prefix / "lib"
    if not lib.is_dir():
        return None
    candidates = [
        child / "site-packages"
        for child in sorted(lib.iterdir(), reverse=True)
        if (child / "site-packages").is_dir()
    ]
    for sp in candidates:
        if any(sp.glob("pdf_to_markdown*")):
            return sp
    return candidates[0] if candidates else None


_PATCH_SENTINEL = "  # _pdf_md_anon"


def _patch_pdf2md_script(prefix: Path, *, with_mps_shim: bool) -> None:
    """Rewrite ``pdf2md``'s injected prelude.

    Always injects a ``sys.path.insert`` so the shebang Python finds the
    packages laid down by ``pip install --prefix``.  When *with_mps_shim* is
    ``True`` also monkey-patches ``torch.backends.mps.is_available`` to
    ``False`` — needed on Apple Silicon when the installed docling+torch
    combination hits the MPS float64 limitation in the layout model.

    Idempotent: all previously injected lines (identified by ``_PATCH_SENTINEL``,
    plus the older non-sentinel ``sys.path.insert`` form) are stripped before
    new ones are written, so re-running after an update does not accumulate
    stale lines and the MPS shim can be toggled off on next run.
    """
    script = prefix / "bin" / "pdf2md"
    if not script.is_file():
        return
    sp = _find_site_packages(prefix)
    if sp is None:
        return
    content = script.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    lines = [
        ln for ln in lines
        if not ln.rstrip("\n").endswith(_PATCH_SENTINEL)
        and not ln.startswith("import sys; sys.path.insert(0, ")
    ]
    insert_pos = 1 if lines and lines[0].startswith("#!") else 0
    patch_lines = [
        f"import sys; sys.path.insert(0, {str(sp)!r}){_PATCH_SENTINEL}\n",
    ]
    if with_mps_shim:
        patch_lines.append(
            f"import torch; torch.backends.mps.is_available = lambda: False{_PATCH_SENTINEL}\n"
        )
    patched = "".join(lines[:insert_pos] + patch_lines + lines[insert_pos:])
    script.write_text(patched, encoding="utf-8")


def _clean_orphan_python_dirs(
    prefix: Path, on_line: Callable[[str], None] | None
) -> None:
    """Delete ``lib/pythonX.Y/`` subtrees that do not hold ``pdf_to_markdown``.

    ``pip install --prefix`` lays packages under ``lib/pythonX.Y/site-packages``
    where ``X.Y`` is the running pip's Python.  When the system ``python3``
    moves (e.g. Homebrew bumps ``3.12`` → ``3.14``) a subsequent install
    creates a new subtree and leaves the old one orphaned forever.  This sweeps
    those orphans, keying off the active site-packages found by
    :func:`_find_site_packages`.
    """
    lib = prefix / "lib"
    if not lib.is_dir():
        return
    active = _find_site_packages(prefix)
    if active is None:
        return
    active_dir = active.parent
    for child in lib.iterdir():
        if child.is_dir() and child.resolve() != active_dir.resolve():
            if on_line:
                on_line(f"Removing orphan {child.name} from previous Python version")
            shutil.rmtree(child, ignore_errors=True)


def _minimal_pdf() -> bytes:
    """Build a tiny well-formed single-page PDF in pure bytes.

    Used only for the post-install smoke test, so generating it deterministically
    in code keeps the repo free of binary fixtures and the byte offsets honest
    no matter what Python writes the bytes.
    """
    body_objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length 44>>\nstream\n"
        b"BT /F1 12 Tf 100 700 Td (Hello World) Tj ET\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(body_objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(out)
    n = len(body_objects) + 1
    out += b"xref\n" + f"0 {n}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += b"trailer\n" + f"<</Size {n}/Root 1 0 R>>\n".encode()
    out += b"startxref\n" + f"{xref_offset}\n".encode() + b"%%EOF\n"
    return out


def _smoke_test(prefix: Path) -> tuple[bool, str]:
    """Run ``pdf2md`` on a tiny embedded PDF; return ``(ok, reason)``.

    A 120-second timeout is generous enough for model load on first use yet
    short enough that a hung subprocess does not freeze the Update flow.
    The reason string is included in the result for surfacing to the user
    (e.g. ``"MPS float64"`` vs ``"timeout"`` vs ``"exit 1"``).
    """
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    script = prefix / "bin" / "pdf2md"
    if not script.is_file():
        return False, "pdf2md script missing"
    pdf_path = Path(tempfile.mkstemp(suffix=".pdf")[1])
    try:
        pdf_path.write_bytes(_minimal_pdf())
        try:
            proc = subprocess.run(
                [str(script), str(pdf_path)],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except OSError as exc:
            return False, f"spawn failed: {exc}"
        if proc.returncode == 0:
            return True, "ok"
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
        reason = "MPS float64" if "float64" in tail[0] and "MPS" in tail[0] else f"exit {proc.returncode}"
        return False, reason
    finally:
        pdf_path.unlink(missing_ok=True)

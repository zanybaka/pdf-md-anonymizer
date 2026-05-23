"""First-use install of the pdf-to-markdown backend for the desktop .app.

The desktop ``.app`` ships lean — the docling stack is not bundled (ADR-0008).
When the user opens a PDF and no usable ``pdf2md`` is found, this module
installs the backend on demand into
``~/Library/Application Support/pdf-md-anonymizer/pdf-backend/``.

Install strategy
----------------
:func:`install` and :func:`update` both run ``pip install --prefix <dir>`` via
:class:`SubprocessPipRunner` — pip is always invoked as an external subprocess
of a real Python interpreter so build isolation, ``sys.path``, and pip's own
plugin loading stay out of our process.

Inside a Briefcase ``.app``, ``sys.executable`` is the Cocoa launcher and
cannot be used as a Python interpreter.  :func:`_find_build_python` locates a
system ``python3`` outside the bundle.  In a dev venv ``sys.executable`` is
already a real interpreter and is used directly.

A system Python (Homebrew or Xcode CLT) is required for install/update inside
the ``.app``.  After install all PDF conversions run fully offline.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

# Same git reference as [project.optional-dependencies].pdf in pyproject.toml.
_PDF_BACKEND_URL = (
    "pdf-to-markdown @ git+https://github.com/zanybaka/pdf-to-markdown@backend/docling"
)

_PACKAGE_NAME = "pdf-to-markdown"


def backend_dir() -> Path:
    """Return the user-writable install prefix for the first-use PDF backend."""
    return Path.home() / "Library" / "Application Support" / "pdf-md-anonymizer" / "pdf-backend"


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
        "/opt/homebrew/bin/python3",  # Apple-Silicon Homebrew
        "/usr/local/bin/python3",  # Intel Homebrew / manual install
        "/usr/bin/python3",  # macOS system Python (Xcode CLT) — often 3.9
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and _python_version_ok(candidate):
            return candidate
    return None


def _python_version_ok(python: str) -> bool:
    """Return True if *python* reports a version >= ``_MIN_PYTHON``."""
    import subprocess

    try:
        subprocess.check_output(
            [python, "-c", f"import sys; exit(0 if sys.version_info >= {_MIN_PYTHON!r} else 1)"],
            timeout=5,
        )
        return True
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return False


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
# PipRunner protocol and implementation
# ---------------------------------------------------------------------------


@runtime_checkable
class PipRunner(Protocol):
    def run(self, args: list[str], on_line: Callable[[str], None] | None) -> None: ...


class SubprocessPipRunner:
    """Run pip as an external subprocess via a given Python interpreter.

    The same shape works for both deployment modes: inside the Briefcase
    ``.app`` we hand it the system ``python3`` found by
    :func:`_find_build_python`; in a dev venv we hand it ``sys.executable``.
    No in-process pip — keeps our process free of pip's import side effects
    (``sys.path``, ``pip._internal`` cache, plugin loading).
    """

    def __init__(self, python_path: str) -> None:
        self._python = python_path

    def run(self, args: list[str], on_line: Callable[[str], None] | None = None) -> None:
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


def _make_runner() -> SubprocessPipRunner:
    """Return a SubprocessPipRunner bound to the right Python for this env.

    Inside a Briefcase ``.app`` we need a real system Python (the Cocoa
    launcher in ``sys.executable`` cannot run pip).  Outside the bundle
    ``sys.executable`` is a real venv interpreter and is used directly.
    """
    build_python = _find_build_python()
    if build_python is None and ".app/Contents/MacOS/" in sys.executable:
        raise RuntimeError(
            "No Python 3 interpreter found outside the app bundle. "
            "Install Python via Homebrew (brew install python3) or https://python.org."
        )
    return SubprocessPipRunner(build_python or sys.executable)


# ---------------------------------------------------------------------------
# Backend-specific install / update helpers
# ---------------------------------------------------------------------------


def install_backend(runner: PipRunner, on_line: Callable[[str], None] | None = None) -> None:
    """Install the pdf-to-markdown backend using *runner*."""
    prefix = backend_dir()
    prefix.mkdir(parents=True, exist_ok=True)
    if on_line:
        on_line(f"Installing {_PACKAGE_NAME} (this may take a few minutes)…")
    pip_args = [
        "install",
        "--prefix",
        str(prefix),
        "--no-cache-dir",
        "setuptools",
        _PDF_BACKEND_URL,
    ]
    runner.run(pip_args, on_line)
    _finalize_install(prefix, on_line)


def update_backend(runner: PipRunner, on_line: Callable[[str], None] | None = None) -> None:
    """Update the pdf-to-markdown backend using *runner*."""
    prefix = backend_dir()
    prefix.mkdir(parents=True, exist_ok=True)
    if on_line:
        on_line(f"Updating {_PACKAGE_NAME} (this may take a few minutes)…")
    pip_args = [
        "install",
        "--prefix",
        str(prefix),
        "--no-cache-dir",
        "--upgrade",
        "setuptools",
        _PDF_BACKEND_URL,
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


# ---------------------------------------------------------------------------
# Site-packages resolution (kept here so test monkeypatches of
# ``pdf_backend._python_lib_tag`` keep intercepting inner calls).
# ---------------------------------------------------------------------------


def _resolve_via_shebang(prefix: Path, lib: Path) -> Path | None:
    """Resolve site-packages from ``bin/pdf2md``'s shebang Python.

    Returns ``None`` when the script, its shebang, the Python it points to,
    or the resulting ``lib/pythonX.Y/site-packages`` directory is absent —
    in which case the caller falls back to a directory-listing heuristic.
    """
    script = prefix / "bin" / "pdf2md"
    if not script.is_file():
        return None
    try:
        first_line = script.read_text(encoding="utf-8").splitlines()[0]
    except OSError:
        return None
    if not first_line.startswith("#!"):
        return None
    tag = _python_lib_tag(first_line[2:].strip())
    if tag is None:
        return None
    sp = lib / tag / "site-packages"
    return sp if sp.is_dir() else None


def _find_site_packages(prefix: Path) -> Path | None:
    """Return the site-packages directory under the install prefix, or None.

    Uses ``bin/pdf2md``'s shebang (the Python that pip used to install) as the
    source of truth: pip with ``--prefix`` lays packages under
    ``lib/pythonX.Y/site-packages`` where X.Y matches the running pip.  Querying
    the shebang Python for its ``sys.version_info`` gives the exact directory,
    even when several ``lib/pythonX.Y/`` subtrees coexist after a Python-version
    bump (the stale ones might still hold a copy of the package and would beat
    the fresh dir under a naive name-sort).

    Falls back to "any site-packages holding ``pdf_to_markdown``" → "highest
    version" only when the script is absent or its shebang Python is missing,
    so pre-install and ``installed_version`` checks still work.
    """
    lib = prefix / "lib"
    if not lib.is_dir():
        return None
    resolved = _resolve_via_shebang(prefix, lib)
    if resolved is not None:
        return resolved
    candidates = [
        child / "site-packages"
        for child in sorted(lib.iterdir(), reverse=True)
        if (child / "site-packages").is_dir()
    ]
    for sp in candidates:
        if any(sp.glob("pdf_to_markdown*")):
            return sp
    return candidates[0] if candidates else None


def _python_lib_tag(python_path: str) -> str | None:
    """Return ``"pythonX.Y"`` for *python_path*, or ``None`` if unavailable."""
    if not python_path or not Path(python_path).is_file():
        return None
    import subprocess  # noqa: PLC0415

    try:
        out = subprocess.check_output(
            [
                python_path,
                "-c",
                "import sys; print(f'python{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            timeout=5,
            text=True,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


def _clean_orphan_python_dirs(prefix: Path, on_line: Callable[[str], None] | None) -> None:
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


# ---------------------------------------------------------------------------
# Re-exports from focused submodules (split out for file-size reasons; the
# names stay accessible as ``pdf_backend.X`` so callers and tests are unaffected).
# ---------------------------------------------------------------------------

from ._script_patch import _PATCH_SENTINEL, _patch_pdf2md_script  # noqa: E402, F401
from ._smoke import _minimal_pdf, _smoke_test  # noqa: E402, F401

"""Rewrite the ``pdf2md`` shebang script's injected sys.path / MPS shim."""

from __future__ import annotations

from pathlib import Path

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
    # Late import to avoid a circular dependency with the package __init__,
    # which re-exports this function.
    from . import _find_site_packages  # noqa: PLC0415

    script = prefix / "bin" / "pdf2md"
    if not script.is_file():
        return
    sp = _find_site_packages(prefix)
    if sp is None:
        return
    content = script.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    lines = [
        ln
        for ln in lines
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

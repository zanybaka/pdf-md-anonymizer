"""Drag-and-drop overlay setup for the anonymizer desktop UI.

``setup`` is the single entry point: it wraps ``appkit_bridge.setup_drag_drop``
and filters the file list to accepted extensions before passing paths to the
caller's callback.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from anonymizer_ui import appkit_bridge

_ACCEPT_EXTS = frozenset({".pdf", ".md"})


def setup(
    window,
    on_paths: Callable[[list[Path]], None],
    on_highlight: Callable[[bool], None],
    on_error: Callable[[str], None] | None = None,
) -> object:
    """Register a drag-and-drop overlay on *window*.

    *on_paths* receives only ``.pdf`` / ``.md`` paths.
    *on_highlight* is called with ``True`` on drag-enter and ``False`` on exit.
    *on_error* receives error messages if drag operation fails unexpectedly.
    Returns the overlay object — caller must hold a reference to keep it alive.
    """

    def _filtered(raw_paths: list[str]) -> None:
        accepted = [Path(p) for p in raw_paths if Path(p).suffix.lower() in _ACCEPT_EXTS]
        if accepted:
            on_paths(accepted)

    return appkit_bridge.setup_drag_drop(
        window, on_paths=_filtered, on_highlight=on_highlight, on_error=on_error
    )

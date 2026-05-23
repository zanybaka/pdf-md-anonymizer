"""Force a Toga widget to become the window's first responder.

Toga's ``Widget.focus()`` is a best-effort hint that the AppKit backend may
or may not honour on window open — the NSWindow defaults its initial first
responder to whichever focusable view appears first in the view tree, which
in our header layout is the GitHub icon button (added before the file row).
We override that by calling NSWindow.makeFirstResponder_ directly on the
target widget's native peer.
"""

from __future__ import annotations

from ._common import AppKitError


def make_first_responder(toga_widget) -> None:
    """Make *toga_widget*'s native peer the first responder of its window.

    No-op when the widget has no native peer yet (called before layout).
    """
    try:
        native = toga_widget._impl.native
        window = native.window
        if window is None:
            return
        window.makeFirstResponder_(native)
    except Exception as exc:
        raise AppKitError("make_first_responder failed") from exc

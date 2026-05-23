"""Activation policy and window foregrounding helpers."""

from __future__ import annotations

from ._common import AppKitError, _appkit


def set_dock_visible(visible: bool) -> None:
    """Set the app activation policy (Regular=dock visible, Accessory=hidden)."""
    try:
        ObjCClass = _appkit()
        policy = 0 if visible else 2  # NSApplicationActivationPolicyRegular/Accessory
        ObjCClass("NSApplication").sharedApplication.setActivationPolicy_(policy)
    except Exception as exc:
        raise AppKitError(f"set_dock_visible({visible}) failed") from exc


def activate_app(*, ignoring_other: bool = True) -> None:
    """Bring the app to the foreground.

    Uses the legacy ``activateIgnoringOtherApps_:`` API on purpose: the macOS 14+
    ``activate()`` is policy-respecting and no-ops right after an Accessory →
    Regular transition, which makes the first "Show Window" click fail to yank
    focus.  The aggressive legacy form works on the first click.
    """
    try:
        ObjCClass = _appkit()
        ns_app = ObjCClass("NSApplication").sharedApplication
        ns_app.activateIgnoringOtherApps_(ignoring_other)
    except Exception as exc:
        raise AppKitError("activate_app failed") from exc


def bring_window_to_front(window) -> None:
    """Make *window* key and bring it to the front."""
    try:
        window._impl.native.makeKeyAndOrderFront_(None)
    except Exception as exc:
        raise AppKitError("bring_window_to_front failed") from exc

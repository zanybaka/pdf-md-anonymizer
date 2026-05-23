"""macOS user-notification delivery."""

from __future__ import annotations

from ._common import AppKitError


def deliver_notification(title: str, body: str) -> None:
    """Send a macOS user notification."""
    try:
        from rubicon.objc.runtime import load_library  # noqa: PLC0415

        load_library("Foundation")
        from rubicon.objc import ObjCClass  # noqa: PLC0415

        n = ObjCClass("NSUserNotification").alloc().init()
        n.title = title
        n.informativeText = body
        ObjCClass("NSUserNotificationCenter").defaultUserNotificationCenter.deliverNotification_(n)
    except Exception as exc:
        raise AppKitError("deliver_notification failed") from exc

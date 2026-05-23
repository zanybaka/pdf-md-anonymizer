"""Accessibility permission probe + synthetic Cmd+C keystroke."""

from __future__ import annotations

from ._common import AppKitError


def is_accessibility_trusted() -> bool:
    """Return True if the app has macOS Accessibility permission granted.

    Accessibility is required for ``NSEvent.addGlobalMonitorForEventsMatchingMask:``
    to receive key events from other apps, and for ``CGEventPost`` to synthesize
    keyboard input (Cmd+C).  Without it both silently no-op.
    """
    try:
        import ctypes  # noqa: PLC0415

        services = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        services.AXIsProcessTrusted.restype = ctypes.c_bool
        services.AXIsProcessTrusted.argtypes = []
        return bool(services.AXIsProcessTrusted())
    except Exception as exc:
        raise AppKitError(f"is_accessibility_trusted failed: {type(exc).__name__}: {exc}") from exc


def send_cmd_c() -> None:
    """Synthesize a Cmd+C keyboard event via CGEventPost.

    Requires Accessibility permission (already granted for the global hotkey
    monitor — same TCC service ``kTCCServiceAccessibility``).
    """
    import ctypes  # noqa: PLC0415

    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
        cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        cf.CFRelease.argtypes = [ctypes.c_void_p]

        kVK_ANSI_C = 0x08
        kCGEventFlagMaskCommand = 1 << 20  # 0x100000
        kCGHIDEventTap = 0

        for is_down in (True, False):
            event = cg.CGEventCreateKeyboardEvent(None, kVK_ANSI_C, is_down)
            if not event:
                continue
            cg.CGEventSetFlags(event, kCGEventFlagMaskCommand)
            cg.CGEventPost(kCGHIDEventTap, event)
            cf.CFRelease(event)
    except Exception as exc:
        raise AppKitError(f"send_cmd_c failed: {type(exc).__name__}: {exc}") from exc

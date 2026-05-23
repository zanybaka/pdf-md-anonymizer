"""Hook ``applicationShouldHandleReopen:`` on the NSApplication delegate."""

from __future__ import annotations

import contextlib
from collections.abc import Callable

from ._common import AppKitError, _appkit

# Storage to prevent GC of the C trampoline and Python callback for the
# applicationShouldHandleReopen: hook.  Without this they'd be collected
# and macOS would call into freed memory on the next reopen.
_reopen_trampoline = None
_reopen_callback = None


def install_reopen_handler(on_reopen: Callable[[], None]) -> None:
    """Hook ``applicationShouldHandleReopen:hasVisibleWindows:`` on the current
    NSApplication delegate so *on_reopen* fires when the user re-launches the
    app (Finder double-click, Spotlight, etc.) while it's still running in the
    menu bar.

    Idempotent — calling twice replaces the previous callback but only adds the
    ObjC method once.
    """
    global _reopen_trampoline, _reopen_callback
    _reopen_callback = on_reopen
    if _reopen_trampoline is not None:
        return  # already installed
    try:
        import ctypes  # noqa: PLC0415

        from rubicon.objc.runtime import libobjc  # noqa: PLC0415

        ObjCClass = _appkit()
        delegate = ObjCClass("NSApplication").sharedApplication.delegate
        if delegate is None:
            raise AppKitError("install_reopen_handler: no NSApplication delegate")

        # Resolve the delegate's class pointer for class_addMethod.
        delegate_class = libobjc.object_getClass(
            delegate.ptr if hasattr(delegate, "ptr") else delegate
        )

        CFUNC = ctypes.CFUNCTYPE(
            ctypes.c_bool,  # BOOL return
            ctypes.c_void_p,  # self
            ctypes.c_void_p,  # _cmd (SEL)
            ctypes.c_void_p,  # NSApplication *sender
            ctypes.c_bool,  # BOOL hasVisibleWindows
        )

        def _shim(self_, _cmd, sender, has_visible_windows) -> bool:
            with contextlib.suppress(Exception):
                if _reopen_callback is not None:
                    _reopen_callback()
            return True

        trampoline = CFUNC(_shim)
        _reopen_trampoline = (trampoline, _shim)  # keep strong refs

        sel_name = b"applicationShouldHandleReopen:hasVisibleWindows:"
        sel = libobjc.sel_registerName(sel_name)
        # Type encoding: B@:@B → BOOL (id self, SEL _cmd, id sender, BOOL flag)
        libobjc.class_addMethod(delegate_class, sel, trampoline, b"B@:@B")
    except AppKitError:
        raise
    except Exception as exc:
        raise AppKitError(f"install_reopen_handler failed: {type(exc).__name__}: {exc}") from exc

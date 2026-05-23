"""System-wide and in-app NSEvent monitors for a keyboard shortcut."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from ctypes import c_void_p

# Top-level rubicon import — needed because Block resolves string annotations
# (PEP 563) against module __globals__ via typing.get_type_hints().
try:
    from rubicon.objc import Block, ObjCInstance  # noqa: F401
except ImportError:  # pragma: no cover — rubicon-objc is required for UI
    Block = ObjCInstance = None  # type: ignore[assignment]

from ._common import AppKitError, _appkit

# Default shortcut: ⌃⌥⌘C
# NSEventModifierFlagControl = 1 << 18 = 262144
# NSEventModifierFlagOption  = 1 << 19 = 524288
# NSEventModifierFlagCommand = 1 << 20 = 1048576
# Combined: 262144 | 524288 | 1048576 = 1835008
HOTKEY_DEFAULT_MODIFIER_FLAGS: int = 1835008
# kVK_ANSI_C = 0x08
HOTKEY_DEFAULT_KEY_CODE: int = 0x08


class _HotkeyToken:
    """Opaque token returned by ``register_global_hotkey``.

    Holds strong Python references to BOTH the global and local NSEvent
    monitors and to the Block/handler closures, so the GC does not free the
    Python callable while the ObjC system still holds the block pointer.
    """

    def __init__(
        self,
        global_monitor,
        local_monitor,
        global_block,
        local_block,
        global_handler,
        local_handler,
    ):
        self.global_monitor = global_monitor
        self.local_monitor = local_monitor
        # Keep refs to prevent GC of the Python closures backing the ObjC blocks.
        self._global_block = global_block
        self._local_block = local_block
        self._global_handler = global_handler
        self._local_handler = local_handler


def register_global_hotkey(
    modifier_flags: int,
    key_code: int,
    callback: Callable[[], None],
) -> object:
    """Register a system-wide key-down handler for the given modifier+key combo.

    Registers BOTH ``addGlobalMonitorForEventsMatchingMask:handler:`` (for
    events from other apps — requires Accessibility permission) and
    ``addLocalMonitorForEventsMatchingMask:handler:`` (for events sent to our
    own app — no permission needed).  Without the local monitor the shortcut
    silently does nothing when our window is focused.

    The handler fires on an AppKit (non-asyncio) thread; *callback* must be
    safe to call from that context (typically via ``loop.call_soon_threadsafe``).

    Returns an opaque token that must be passed to ``remove_global_hotkey``
    to unregister both monitors.
    """
    try:
        ObjCClass = _appkit()
        NSEvent = ObjCClass("NSEvent")
        # NSEventMaskKeyDown = 1 << 10 = 1024
        NSEventMaskKeyDown = 1 << 10

        def _matches(event_ptr) -> bool:
            if not event_ptr:
                return False
            event = ObjCInstance(event_ptr)
            event_flags = int(event.modifierFlags) & 0xFFFF0000
            event_key = int(event.keyCode)
            return event_flags == modifier_flags and event_key == key_code

        def _global_handler(event_ptr: c_void_p) -> None:
            with contextlib.suppress(Exception):
                if _matches(event_ptr):
                    callback()

        def _local_handler(event_ptr: c_void_p) -> c_void_p:
            with contextlib.suppress(Exception):
                if _matches(event_ptr):
                    callback()
                    return None  # consume the event
            return event_ptr  # let other handlers / responders process it

        global_block = Block(_global_handler, None, c_void_p)
        local_block = Block(_local_handler, c_void_p, c_void_p)

        global_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown,
            global_block,
        )
        local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown,
            local_block,
        )
        return _HotkeyToken(
            global_monitor,
            local_monitor,
            global_block,
            local_block,
            _global_handler,
            _local_handler,
        )
    except AppKitError:
        raise
    except Exception as exc:
        raise AppKitError(f"register_global_hotkey failed: {type(exc).__name__}: {exc}") from exc


def remove_global_hotkey(monitor: object) -> None:
    """Unregister a token returned by ``register_global_hotkey``."""
    if monitor is None:
        return
    try:
        ObjCClass = _appkit()
        NSEvent = ObjCClass("NSEvent")
        if isinstance(monitor, _HotkeyToken):
            if monitor.global_monitor is not None:
                NSEvent.removeMonitor_(monitor.global_monitor)
            if monitor.local_monitor is not None:
                NSEvent.removeMonitor_(monitor.local_monitor)
        else:
            # Legacy: a bare monitor token from earlier register_global_hotkey signature.
            NSEvent.removeMonitor_(monitor)
    except AppKitError:
        raise
    except Exception as exc:
        raise AppKitError("remove_global_hotkey failed") from exc

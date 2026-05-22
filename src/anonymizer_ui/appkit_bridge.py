"""AppKit ObjC bridge — the single rubicon-objc boundary for anonymizer_ui.

Every ObjCClass call in the UI package must go through this module.
Callers catch ``AppKitError`` at the call site.
Document content must never appear in error messages.
"""

from __future__ import annotations

from collections.abc import Callable
from ctypes import c_ulong, c_void_p
from pathlib import Path

# Top-level rubicon imports — needed because @objc_method and Block resolve
# string annotations (PEP 563) against module __globals__ via
# typing.get_type_hints(); names imported inside functions are invisible there.
try:
    from rubicon.objc import Block, ObjCInstance  # noqa: F401
    from rubicon.objc.runtime import objc_id  # noqa: F401
    from rubicon.objc.types import NSPoint  # noqa: F401
except ImportError:  # pragma: no cover — rubicon-objc is required for UI
    Block = ObjCInstance = objc_id = NSPoint = None  # type: ignore[assignment]


class AppKitError(RuntimeError):
    """Raised when an AppKit / rubicon-objc operation fails."""


def _appkit():
    """Load AppKit and return the ObjCClass factory."""
    from rubicon.objc.runtime import load_library  # noqa: PLC0415
    load_library("AppKit")
    from rubicon.objc import ObjCClass  # noqa: PLC0415
    return ObjCClass


# ---------------------------------------------------------------------------
# Activation / window management
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Pasteboard
# ---------------------------------------------------------------------------

def pasteboard_string(uti: str = "public.utf8-plain-text") -> str | None:
    """Read a string from the general pasteboard, or None if absent."""
    try:
        ObjCClass = _appkit()
        pb = ObjCClass("NSPasteboard").generalPasteboard
        raw = pb.stringForType_(uti)
        return str(raw) if raw is not None else None
    except Exception as exc:
        raise AppKitError("pasteboard_string failed") from exc


def pasteboard_set_string(text: str, uti: str = "public.utf8-plain-text") -> None:
    """Write *text* to the general pasteboard."""
    try:
        ObjCClass = _appkit()
        pb = ObjCClass("NSPasteboard").generalPasteboard
        pb.clearContents()
        pb.setString_forType_(text, uti)
    except Exception as exc:
        raise AppKitError("pasteboard_set_string failed") from exc


def pasteboard_filenames() -> list[str]:
    """Return file paths from the general pasteboard (NSFilenamesPboardType)."""
    try:
        ObjCClass = _appkit()
        pb = ObjCClass("NSPasteboard").generalPasteboard
        files = pb.propertyListForType_("NSFilenamesPboardType")
        if files is None:
            return []
        n = int(files.count)
        return [str(files.objectAtIndex_(i)) for i in range(n)]
    except Exception as exc:
        raise AppKitError("pasteboard_filenames failed") from exc


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def deliver_notification(title: str, body: str) -> None:
    """Send a macOS user notification."""
    try:
        from rubicon.objc.runtime import load_library  # noqa: PLC0415
        load_library("Foundation")
        from rubicon.objc import ObjCClass  # noqa: PLC0415
        n = ObjCClass("NSUserNotification").alloc().init()
        n.title = title
        n.informativeText = body
        ObjCClass(
            "NSUserNotificationCenter"
        ).defaultUserNotificationCenter.deliverNotification_(n)
    except Exception as exc:
        raise AppKitError("deliver_notification failed") from exc


# ---------------------------------------------------------------------------
# File picker
# ---------------------------------------------------------------------------

def pick_file(title: str, allowed_extensions: list[str]) -> Path | None:
    """Show NSOpenPanel modally and return the chosen path, or None.

    Caller must have already switched the activation policy to Regular and
    yielded one run-loop tick so WindowServer registers the app as
    foreground-eligible.  Restores Accessory policy on exit.
    """
    try:
        ObjCClass = _appkit()
        ns_app = ObjCClass("NSApplication").sharedApplication

        # Use the legacy aggressive form for the same reason as activate_app(): the
        # macOS 14+ activate() respects the previously frontmost app and no-ops
        # right after an Accessory→Regular policy flip, which lands NSOpenPanel
        # behind that other app on first menu-bar invocation.
        ns_app.activateIgnoringOtherApps_(True)

        panel = ObjCClass("NSOpenPanel").openPanel()
        panel.title = title
        panel.canChooseFiles = True
        panel.canChooseDirectories = False
        panel.allowsMultipleSelection = False

        try:
            arr = ObjCClass("NSMutableArray").alloc().init()
            for ext in allowed_extensions:
                arr.addObject_(ext)
            panel.allowedFileTypes = arr
        except Exception:
            pass

        try:
            panel.setLevel_(8)          # NSModalPanelWindowLevel
        except Exception:
            pass
        try:
            panel.orderFrontRegardless()
        except Exception:
            pass
        try:
            panel.center()
        except Exception:
            pass

        result = int(panel.runModal())

        try:
            ns_app.setActivationPolicy_(2)  # restore Accessory
        except Exception:
            pass

        if result == 1:             # NSModalResponseOK
            urls = panel.URLs
            if len(urls) > 0:
                return Path(str(urls[0].path))
        return None

    except AppKitError:
        raise
    except Exception as exc:
        raise AppKitError("pick_file failed") from exc


# ---------------------------------------------------------------------------
# Status-bar icon helpers
# ---------------------------------------------------------------------------

def status_icon_resize(status_icon, size: int = 19) -> None:
    """Resize the status-bar button image to *size* × *size* points."""
    try:
        from rubicon.objc.types import NSSize  # noqa: PLC0415
        native = status_icon._impl.native
        existing = native.button.image
        if existing is not None:
            existing.setSize_(NSSize(size, size))
    except Exception as exc:
        raise AppKitError("status_icon_resize failed") from exc


def status_icon_swap_image(
    status_icon,
    busy: bool,
    saved_image_box: list,
) -> None:
    """Swap the status-bar icon between idle and a busy symbol.

    *saved_image_box* is a single-element list ``[None]``.  The original
    image is stored there while busy so it can be restored on idle.
    """
    try:
        from rubicon.objc import ObjCClass  # noqa: PLC0415
        from rubicon.objc.types import NSSize  # noqa: PLC0415
        button = status_icon._impl.native.button
    except Exception as exc:
        raise AppKitError("status_icon_swap_image: cannot reach button") from exc

    if busy:
        if saved_image_box[0] is None:
            try:
                saved_image_box[0] = button.image
            except Exception:
                pass
        try:
            NSImage = ObjCClass("NSImage")
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "hourglass", "Working"
            )
            if img is None:
                img = NSImage.imageNamed_("NSRefreshTemplate")
            if img is not None:
                img.setSize_(NSSize(18, 18))
                img.setTemplate_(True)
                button.setImage_(img)
        except Exception as exc:
            raise AppKitError("status_icon_swap_image(busy=True) failed") from exc
    else:
        if saved_image_box[0] is not None:
            try:
                button.setImage_(saved_image_box[0])
            except Exception as exc:
                raise AppKitError("status_icon_swap_image(busy=False) failed") from exc
            saved_image_box[0] = None


def set_menu_item_checked(status_icon, title_contains: str, *, checked: bool) -> None:
    """Set the native NSMenuItem checkmark for the item whose title contains *title_contains*.

    Uses NSMenuItem.setState_ (NSOnState=1 / NSOffState=0) — the proper macOS
    mechanism for checkmarks, independent of the item's title text.
    """
    _NSOnState = 1
    _NSOffState = 0
    try:
        menu = status_icon._impl.native.menu
        n = int(menu.numberOfItems)
        for i in range(n):
            item = menu.itemAtIndex_(i)
            title = str(item.title) if item.title is not None else ""
            if title_contains in title:
                item.setState_(_NSOnState if checked else _NSOffState)
                return
    except Exception as exc:
        raise AppKitError("set_menu_item_checked failed") from exc


# ---------------------------------------------------------------------------
# Drag-and-drop overlay
# ---------------------------------------------------------------------------

def setup_drag_drop(window, on_paths, on_highlight, on_error=None) -> object:
    """Register a transparent NSView overlay on *window* for file drag-and-drop.

    *on_paths(paths: list[str])* is called with the accepted file paths.
    *on_highlight(show: bool)* is called on drag-enter / drag-exit.
    *on_error(msg: str)* is called on unexpected exceptions (optional).
    Returns the overlay instance — caller must keep a reference alive.
    """
    try:
        from rubicon.objc.runtime import load_library  # noqa: PLC0415
        load_library("AppKit")
        from rubicon.objc import ObjCClass, objc_method  # noqa: PLC0415

        NSView = ObjCClass("NSView")

        class _DropOverlay(NSView):
            """Transparent overlay — passes clicks through, handles file drops."""

            @objc_method
            def hitTest_(self, point: NSPoint) -> objc_id:
                return None  # nil → mouse events fall through to views below

            @objc_method
            def draggingEntered_(self, info) -> c_ulong:
                on_highlight(True)
                return 1  # NSDragOperationCopy

            @objc_method
            def draggingUpdated_(self, info) -> c_ulong:
                return 1

            @objc_method
            def draggingExited_(self, info) -> None:
                on_highlight(False)

            @objc_method
            def prepareForDragOperation_(self, info) -> bool:
                return True

            @objc_method
            def performDragOperation_(self, info) -> bool:
                try:
                    pb = info.draggingPasteboard
                    if pb is not None:
                        # Primary path: NSFilenamesPboardType (macOS < 12 / Finder legacy)
                        files = pb.propertyListForType_("NSFilenamesPboardType")
                        if files is not None:
                            paths = [str(f) for f in files]
                            if paths:
                                on_paths(paths)
                                on_highlight(False)
                                return True
                        # Fallback: public.file-url / NSPasteboardTypeFileURL (macOS 12+)
                        # Use pasteboardItems + stringForType_ to avoid passing ObjC
                        # class objects through rubicon (readObjectsForClasses:options:).
                        from urllib.parse import urlparse, unquote  # noqa: PLC0415
                        items = pb.pasteboardItems
                        if items is not None:
                            paths = []
                            for item in items:
                                url_str = item.stringForType_("public.file-url")
                                if url_str is not None:
                                    path = unquote(urlparse(str(url_str)).path)
                                    if path:
                                        paths.append(path)
                            if paths:
                                on_paths(paths)
                except Exception as _exc:
                    if on_error is not None:
                        on_error(f"drag-and-drop error: {type(_exc).__name__}: {_exc}")
                on_highlight(False)
                return True

            @objc_method
            def concludeDragOperation_(self, info) -> None:
                pass

        ns_window = window._impl.native
        content_view = ns_window.contentView
        overlay = _DropOverlay.alloc().initWithFrame_(content_view.bounds)
        overlay.autoresizingMask = 10   # NSViewWidthSizable | NSViewHeightSizable
        # Register for both types: NSFilenamesPboardType (pre-macOS 12 / legacy
        # Finder) and public.file-url / NSPasteboardTypeFileURL (macOS 12+ Finder
        # primary type).  Without both, draggingEntered_ is never called on
        # macOS 12+ because the registered types don't match.
        drag_types = ObjCClass("NSMutableArray").alloc().init()
        drag_types.addObject_("NSFilenamesPboardType")
        drag_types.addObject_("public.file-url")
        overlay.registerForDraggedTypes_(drag_types)
        content_view.addSubview_(overlay)
        return overlay

    except Exception as exc:
        raise AppKitError(f"setup_drag_drop failed: {type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# Global hotkey (Input Monitoring)
# ---------------------------------------------------------------------------

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

    def __init__(self, global_monitor, local_monitor, global_block, local_block,
                 global_handler, local_handler):
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
            try:
                if _matches(event_ptr):
                    callback()
            except Exception:
                pass

        def _local_handler(event_ptr: c_void_p) -> c_void_p:
            try:
                if _matches(event_ptr):
                    callback()
                    return None  # consume the event
            except Exception:
                pass
            return event_ptr  # let other handlers / responders process it

        global_block = Block(_global_handler, None, c_void_p)
        local_block = Block(_local_handler, c_void_p, c_void_p)

        global_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, global_block,
        )
        local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, local_block,
        )
        return _HotkeyToken(
            global_monitor, local_monitor,
            global_block, local_block,
            _global_handler, _local_handler,
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
        delegate_class = libobjc.object_getClass(delegate.ptr if hasattr(delegate, "ptr") else delegate)

        CFUNC = ctypes.CFUNCTYPE(
            ctypes.c_bool,    # BOOL return
            ctypes.c_void_p,  # self
            ctypes.c_void_p,  # _cmd (SEL)
            ctypes.c_void_p,  # NSApplication *sender
            ctypes.c_bool,    # BOOL hasVisibleWindows
        )

        def _shim(self_, _cmd, sender, has_visible_windows) -> bool:
            try:
                if _reopen_callback is not None:
                    _reopen_callback()
            except Exception:
                pass
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
        raise AppKitError(
            f"install_reopen_handler failed: {type(exc).__name__}: {exc}"
        ) from exc


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
        raise AppKitError(
            f"is_accessibility_trusted failed: {type(exc).__name__}: {exc}"
        ) from exc


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


# ---------------------------------------------------------------------------
# Login item registration (SMAppService / LaunchAgent fallback)
# ---------------------------------------------------------------------------

import platform as _platform
import plistlib as _plistlib
import sys as _sys
from pathlib import Path as _Path


def _macos_version_tuple() -> tuple[int, int]:
    """Return (major, minor) of the running macOS version."""
    ver = _platform.mac_ver()[0]  # e.g. "13.4.1"
    parts = ver.split(".")
    try:
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return (0, 0)


def _launch_agents_dir() -> _Path:
    return _Path("~/Library/LaunchAgents").expanduser()


def _launch_agent_label() -> str:
    return "io.github.zanybaka.pdf-md-anonymizer"


def _launch_agent_plist_path() -> _Path:
    return _launch_agents_dir() / f"{_launch_agent_label()}.plist"


def _current_executable() -> str:
    """Best-effort path to the main executable for the LaunchAgent plist."""
    # Inside a Briefcase .app the executable is the macOS bundle binary.
    # In a dev venv it is the Python interpreter (briefcase run uses __main__).
    exe = _sys.executable
    return exe


def register_login_item(args: list[str]) -> None:
    """Register the app as a macOS login item with *args* passed on launch.

    On macOS 13+ uses ``SMAppService.mainAppService.register()``.
    On older macOS writes a user LaunchAgent plist to
    ``~/Library/LaunchAgents/<bundle-id>.plist`` and loads it via ``launchctl``.

    Raises ``AppKitError`` on failure.
    """
    major, _ = _macos_version_tuple()
    if major >= 13:
        _register_login_item_smappservice(args)
    else:
        _register_login_item_launchagent(args)


def unregister_login_item() -> None:
    """Unregister the login item registered by ``register_login_item``.

    Tries both SMAppService and LaunchAgent paths so either mechanism is
    cleaned up regardless of which macOS version originally registered it.
    """
    major, _ = _macos_version_tuple()
    if major >= 13:
        _unregister_login_item_smappservice()
    else:
        _unregister_login_item_launchagent()


def is_login_item_registered() -> bool:
    """Return True if the app is currently registered as a login item.

    Queries SMAppService on macOS 13+ and checks for the LaunchAgent plist on
    older macOS.  Returns False on any error (caller reconciles with prefs).
    """
    try:
        major, _ = _macos_version_tuple()
        if major >= 13:
            return _is_registered_smappservice()
        else:
            return _launch_agent_plist_path().is_file()
    except Exception:
        return False


# --- SMAppService (macOS 13+) ---


def _register_login_item_smappservice(args: list[str]) -> None:
    """Register via SMAppService.mainAppService (macOS 13+)."""
    try:
        import subprocess  # noqa: PLC0415
        # SMAppService is part of ServiceManagement.framework.  We call it via
        # a short Swift one-liner in a subprocess so we don't require PyObjC.
        # On macOS 13+ `swift` is available via Xcode CLT.  The fallback path
        # is the LaunchAgent approach used on older macOS.
        _register_via_swift()
    except Exception as exc:
        raise AppKitError(
            f"register_login_item (SMAppService) failed: {type(exc).__name__}: {exc}"
        ) from exc


def _register_via_swift() -> None:
    """Use a Python-native ctypes approach to call SMAppService via ObjC."""
    import ctypes  # noqa: PLC0415
    try:
        sm = ctypes.CDLL(
            "/System/Library/Frameworks/ServiceManagement.framework/ServiceManagement"
        )
    except OSError as exc:
        raise AppKitError(f"ServiceManagement.framework not found: {exc}") from exc

    try:
        ObjCClass = _appkit()
        SMAppService = ObjCClass("SMAppService")
        service = SMAppService.mainAppService
        # SMAppServiceStatusEnabled = 1
        if int(service.status) != 1:
            ok = bool(service.registerAndReturnError_(None))
            if not ok:
                raise AppKitError("SMAppService.register() returned NO")
    except AppKitError:
        raise
    except Exception as exc:
        raise AppKitError(
            f"register_login_item (SMAppService ObjC) failed: {type(exc).__name__}: {exc}"
        ) from exc


def _is_registered_smappservice() -> bool:
    try:
        ObjCClass = _appkit()
        SMAppService = ObjCClass("SMAppService")
        service = SMAppService.mainAppService
        # SMAppServiceStatusEnabled = 1
        return int(service.status) == 1
    except Exception:
        return False


def _unregister_login_item_smappservice() -> None:
    try:
        ObjCClass = _appkit()
        SMAppService = ObjCClass("SMAppService")
        service = SMAppService.mainAppService
        status = int(service.status)
        if status == 1:  # SMAppServiceStatusEnabled
            service.unregisterAndReturnError_(None)
    except AppKitError:
        raise
    except Exception as exc:
        raise AppKitError(
            f"unregister_login_item (SMAppService) failed: {type(exc).__name__}: {exc}"
        ) from exc


# --- LaunchAgent fallback (macOS < 13) ---


def _register_login_item_launchagent(args: list[str]) -> None:
    """Write a LaunchAgent plist and load it via launchctl (macOS < 13)."""
    import subprocess  # noqa: PLC0415
    exe = _current_executable()
    plist_data = {
        "Label": _launch_agent_label(),
        "ProgramArguments": [exe] + list(args),
        "RunAtLoad": True,
        "KeepAlive": False,
    }
    plist_path = _launch_agent_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        plist_path.write_bytes(_plistlib.dumps(plist_data))
    except Exception as exc:
        raise AppKitError(f"writing LaunchAgent plist failed: {exc}") from exc

    # Load it so it takes effect immediately (also loads at next login).
    try:
        subprocess.run(
            ["launchctl", "load", str(plist_path)],
            check=False,  # load may fail if already loaded; ignore
            capture_output=True,
        )
    except Exception:
        pass  # launchctl missing or failed — plist still present for next login


def _unregister_login_item_launchagent() -> None:
    """Unload and remove the LaunchAgent plist."""
    import subprocess  # noqa: PLC0415
    plist_path = _launch_agent_plist_path()
    if plist_path.is_file():
        try:
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                check=False,
                capture_output=True,
            )
        except Exception:
            pass
        try:
            plist_path.unlink(missing_ok=True)
        except Exception as exc:
            raise AppKitError(f"removing LaunchAgent plist failed: {exc}") from exc



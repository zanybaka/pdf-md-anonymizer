"""AppKit ObjC bridge — the single rubicon-objc boundary for anonymizer_ui.

Every ObjCClass call in the UI package must go through this module.
Callers catch ``AppKitError`` at the call site.
Document content must never appear in error messages.
"""

from __future__ import annotations

from pathlib import Path


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
    """Bring the app to the foreground."""
    try:
        ObjCClass = _appkit()
        ns_app = ObjCClass("NSApplication").sharedApplication
        try:
            ns_app.activate()           # macOS 14+
        except Exception:
            ns_app.activateIgnoringOtherApps_(ignoring_other)
    except AppKitError:
        raise
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

        try:
            ns_app.activate()           # macOS 14+
        except Exception:
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


# ---------------------------------------------------------------------------
# Drag-and-drop overlay
# ---------------------------------------------------------------------------

def setup_drag_drop(window, on_paths, on_highlight) -> object:
    """Register a transparent NSView overlay on *window* for file drag-and-drop.

    *on_paths(paths: list[str])* is called with the accepted file paths.
    *on_highlight(show: bool)* is called on drag-enter / drag-exit.
    Returns the overlay instance — caller must keep a reference alive.
    """
    try:
        from rubicon.objc.runtime import load_library, objc_id  # noqa: PLC0415
        load_library("AppKit")
        from rubicon.objc import ObjCClass, objc_method  # noqa: PLC0415
        from rubicon.objc.types import NSPoint  # noqa: PLC0415
        from ctypes import c_ulong

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
                        files = pb.propertyListForType_("NSFilenamesPboardType")
                        if files is not None:
                            n = int(files.count)
                            if n > 0:
                                on_paths([str(files.objectAtIndex_(i)) for i in range(n)])
                except Exception:
                    pass
                on_highlight(False)
                return True

            @objc_method
            def concludeDragOperation_(self, info) -> None:
                pass

        ns_window = window._impl.native
        content_view = ns_window.contentView
        overlay = _DropOverlay.alloc().initWithFrame_(content_view.bounds)
        overlay.autoresizingMask = 10   # NSViewWidthSizable | NSViewHeightSizable
        overlay.registerForDraggedTypes_(
            ObjCClass("NSArray").arrayWithObject_("NSFilenamesPboardType")
        )
        content_view.addSubview_(overlay)
        return overlay

    except Exception as exc:
        raise AppKitError("setup_drag_drop failed") from exc

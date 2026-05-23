"""NSView overlay handling file drag-and-drop onto a window."""

from __future__ import annotations

from ctypes import c_ulong

# Top-level rubicon imports — needed because @objc_method resolves string
# annotations (PEP 563) against module __globals__ via typing.get_type_hints();
# names imported inside functions are invisible there.
try:
    from rubicon.objc.runtime import objc_id  # noqa: F401
    from rubicon.objc.types import NSPoint  # noqa: F401
except ImportError:  # pragma: no cover — rubicon-objc is required for UI
    objc_id = NSPoint = None  # type: ignore[assignment]

from ._common import AppKitError


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
                        from urllib.parse import unquote, urlparse  # noqa: PLC0415

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
        overlay.autoresizingMask = 10  # NSViewWidthSizable | NSViewHeightSizable
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

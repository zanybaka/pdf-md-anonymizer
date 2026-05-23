"""NSPasteboard read/write helpers."""

from __future__ import annotations

from ._common import AppKitError, _appkit


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

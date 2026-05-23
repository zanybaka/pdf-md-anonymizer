"""Open a URL via ``NSWorkspace.openURL_``.

Used instead of stdlib ``webbrowser.open`` from inside a Briefcase ``.app``,
where ``webbrowser`` has been observed to silently no-op — NSWorkspace is
the macOS-native path and always honours the user's default browser.
"""

from __future__ import annotations

from ._common import AppKitError


def open_url(url: str) -> None:
    """Open *url* in the user's default browser via NSWorkspace.

    Returns silently if *url* is empty. Raises :class:`AppKitError` if AppKit
    refuses the URL (malformed) or if the workspace call itself fails.
    """
    if not url:
        return
    try:
        from rubicon.objc import ObjCClass  # noqa: PLC0415
        from rubicon.objc.runtime import load_library  # noqa: PLC0415

        load_library("AppKit")
        NSURL = ObjCClass("NSURL")
        NSWorkspace = ObjCClass("NSWorkspace")
        ns_url = NSURL.URLWithString_(url)
        if ns_url is None:
            raise AppKitError("invalid URL")
        ok = NSWorkspace.sharedWorkspace.openURL_(ns_url)
        if not ok:
            raise AppKitError("NSWorkspace.openURL_ returned NO")
    except AppKitError:
        raise
    except Exception as exc:
        raise AppKitError("open_url failed") from exc

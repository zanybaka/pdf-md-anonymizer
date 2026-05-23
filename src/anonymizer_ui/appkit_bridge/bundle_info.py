"""Read values from the running process's NSBundle ``Info.plist``.

Used to recover values that ``importlib.metadata`` cannot see inside a
Briefcase ``.app`` bundle (the package is shipped as plain source files,
no ``dist-info/``). Briefcase writes any keys declared under
``[tool.briefcase.app.X.macOS].info_plist`` straight into the bundle's
``Info.plist`` at build time.
"""

from __future__ import annotations

from ._common import AppKitError


def main_bundle_info_string(key: str) -> str:
    """Return the bundle's ``Info.plist`` value for *key* as a string.

    Empty string when the key is absent. Raises :class:`AppKitError` only if
    the AppKit call itself blows up (missing framework, etc.).
    """
    try:
        from rubicon.objc import ObjCClass  # noqa: PLC0415
        from rubicon.objc.runtime import load_library  # noqa: PLC0415

        load_library("AppKit")
        bundle = ObjCClass("NSBundle").mainBundle
        raw = bundle.objectForInfoDictionaryKey_(key)
        if raw is None:
            return ""
        return str(raw).strip()
    except Exception as exc:
        raise AppKitError(f"main_bundle_info_string({key!r}) failed") from exc


def main_bundle_short_version() -> str:
    """Return ``CFBundleShortVersionString`` of the running process's main bundle.

    In a dev install the main bundle is Python's own ``.app`` bundle and the
    returned value is Python's version (e.g. ``"3.13.5"``) — callers must
    try ``importlib.metadata`` first and only fall through to this when
    that fails.
    """
    return main_bundle_info_string("CFBundleShortVersionString")

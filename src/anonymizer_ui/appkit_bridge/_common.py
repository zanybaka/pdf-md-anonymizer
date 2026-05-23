"""Shared AppKit boundary primitives — error class and ObjC loader."""

from __future__ import annotations


class AppKitError(RuntimeError):
    """Raised when an AppKit / rubicon-objc operation fails."""


def _appkit():
    """Load AppKit and return the ObjCClass factory."""
    from rubicon.objc.runtime import load_library  # noqa: PLC0415

    load_library("AppKit")
    from rubicon.objc import ObjCClass  # noqa: PLC0415

    return ObjCClass

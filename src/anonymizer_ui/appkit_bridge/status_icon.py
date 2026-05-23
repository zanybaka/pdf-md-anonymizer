"""NSStatusItem/NSStatusBarButton icon + menu helpers."""

from __future__ import annotations

import contextlib

from ._common import AppKitError


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
            with contextlib.suppress(Exception):
                saved_image_box[0] = button.image
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

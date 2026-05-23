"""Style a Toga button's underlying NSButton as a round icon control.

Toga 0.5 has no border-radius / cornerRadius styling API. To get a circular
icon button (UI-023) we reach into the NSButton via ``button._impl.native``
and configure its layer directly: borderless, square frame, centered image,
hover-friendly subtle background, fully rounded corners.

The original ``on_press`` wiring stays intact — Toga sets up the NSButton's
target/action when the button is constructed, and re-styling the layer does
not detach it.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from ._common import AppKitError


def style_round_icon_button(
    toga_button,
    image_path: Path | str,
    *,
    size: int = 28,
    image_scale: float = 0.6,
    tooltip: str | None = None,
) -> None:
    """Re-style *toga_button* as a circular icon button.

    *image_path* points to a PNG. *size* is the diameter in points;
    *image_scale* sets the icon size relative to the button. *tooltip* sets the
    NSButton ``toolTip`` (Toga has no tooltip API).
    """
    try:
        from rubicon.objc import ObjCClass  # noqa: PLC0415
        from rubicon.objc.runtime import load_library  # noqa: PLC0415
        from rubicon.objc.types import NSSize  # noqa: PLC0415

        load_library("AppKit")
        NSImage = ObjCClass("NSImage")
        NSColor = ObjCClass("NSColor")

        native = toga_button._impl.native
        native.setTitle_("")
        native.setBordered_(False)
        # NSImageOnly = 1
        native.setImagePosition_(1)
        # NSImageScaleProportionallyDown = 2 (optional, recent macOS)
        with contextlib.suppress(Exception):
            native.setImageScaling_(2)

        # Replace whatever image Toga already set with one resized to fit the
        # round frame nicely. If our PNG can't be loaded, leave Toga's image
        # in place — the button still works, just less polished.
        path = str(Path(image_path))
        img = NSImage.alloc().initWithContentsOfFile_(path)
        if img is not None:
            icon_pt = max(8, int(round(size * image_scale)))
            img.setSize_(NSSize(icon_pt, icon_pt))
            native.setImage_(img)

        # Round layer styling. Toga's pack engine owns the frame; we only
        # style the layer here.
        native.setWantsLayer_(True)
        layer = native.layer
        if layer is not None:
            layer.setCornerRadius_(size / 2.0)
            layer.setMasksToBounds_(True)
            bg = NSColor.colorWithCalibratedWhite_alpha_(0.5, 0.12)
            with contextlib.suppress(Exception):
                layer.setBackgroundColor_(bg.CGColor)

        if tooltip:
            with contextlib.suppress(Exception):
                native.setToolTip_(tooltip)
    except AppKitError:
        raise
    except Exception as exc:
        raise AppKitError("style_round_icon_button failed") from exc

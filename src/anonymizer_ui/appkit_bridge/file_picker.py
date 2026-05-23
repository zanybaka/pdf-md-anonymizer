"""NSOpenPanel-based file-picker dialog."""

from __future__ import annotations

import contextlib
from pathlib import Path

from ._common import AppKitError, _appkit


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

        with contextlib.suppress(Exception):
            arr = ObjCClass("NSMutableArray").alloc().init()
            for ext in allowed_extensions:
                arr.addObject_(ext)
            panel.allowedFileTypes = arr

        with contextlib.suppress(Exception):
            panel.setLevel_(8)  # NSModalPanelWindowLevel
        with contextlib.suppress(Exception):
            panel.orderFrontRegardless()
        with contextlib.suppress(Exception):
            panel.center()

        result = int(panel.runModal())

        with contextlib.suppress(Exception):
            ns_app.setActivationPolicy_(2)  # restore Accessory

        if result == 1:  # NSModalResponseOK
            urls = panel.URLs
            if len(urls) > 0:
                return Path(str(urls[0].path))
        return None

    except AppKitError:
        raise
    except Exception as exc:
        raise AppKitError("pick_file failed") from exc

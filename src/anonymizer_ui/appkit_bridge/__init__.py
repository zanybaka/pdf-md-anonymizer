"""AppKit ObjC bridge — the single rubicon-objc boundary for anonymizer_ui.

Every ObjCClass call in the UI package must go through this package.
Callers catch ``AppKitError`` at the call site.
Document content must never appear in error messages.

The package is split into focused submodules (activation, pasteboard,
status_icon, drag_drop, global_hotkey, login_item, …) but this ``__init__``
re-exports the full public surface so callers keep using
``from anonymizer_ui import appkit_bridge`` and ``appkit_bridge.X``.
"""

from __future__ import annotations

from ._common import AppKitError, _appkit
from .accessibility import is_accessibility_trusted, send_cmd_c
from .activation import activate_app, bring_window_to_front, set_dock_visible
from .bundle_info import main_bundle_info_string, main_bundle_short_version
from .drag_drop import setup_drag_drop
from .file_picker import pick_file
from .first_responder import make_first_responder
from .global_hotkey import (
    HOTKEY_DEFAULT_KEY_CODE,
    HOTKEY_DEFAULT_MODIFIER_FLAGS,
    _HotkeyToken,
    register_global_hotkey,
    remove_global_hotkey,
)
from .login_item import (
    is_login_item_registered,
    register_login_item,
    unregister_login_item,
)
from .notifications import deliver_notification
from .pasteboard import pasteboard_filenames, pasteboard_set_string, pasteboard_string
from .reopen_handler import install_reopen_handler
from .round_button import style_round_icon_button
from .status_icon import set_menu_item_checked, status_icon_resize, status_icon_swap_image
from .url_opener import open_url

__all__ = [
    "HOTKEY_DEFAULT_KEY_CODE",
    "HOTKEY_DEFAULT_MODIFIER_FLAGS",
    "AppKitError",
    "_HotkeyToken",
    "_appkit",
    "activate_app",
    "bring_window_to_front",
    "deliver_notification",
    "install_reopen_handler",
    "is_accessibility_trusted",
    "is_login_item_registered",
    "main_bundle_info_string",
    "make_first_responder",
    "main_bundle_short_version",
    "open_url",
    "pasteboard_filenames",
    "pasteboard_set_string",
    "pasteboard_string",
    "pick_file",
    "register_global_hotkey",
    "register_login_item",
    "remove_global_hotkey",
    "send_cmd_c",
    "set_dock_visible",
    "set_menu_item_checked",
    "setup_drag_drop",
    "status_icon_resize",
    "status_icon_swap_image",
    "style_round_icon_button",
    "unregister_login_item",
]

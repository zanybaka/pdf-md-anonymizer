# Vulture false-positive whitelist for pdf-md-anonymizer.
#
# Vulture scans only the source tree (not tests), and cannot see ObjC selector
# dispatch or Toga command-callback signatures. The names below are real call
# sites that vulture mistakes for dead code. Each block notes the framework
# contract that keeps the name alive.

# ruff: noqa
# pyright: reportMissingImports=false
# mypy: ignore-errors

from anonymizer.detect import ner as _ner
from anonymizer_ui import app as _app
from anonymizer_ui import appkit_bridge as _appkit
from anonymizer_ui import batch_controller as _batch
from anonymizer_ui import menubar_controller as _menubar

# --- Toga / AppKit framework callbacks -----------------------------------
# Toga calls App.startup(); window handler is wired via on_close=.
_app.AnonymizerApp.startup
_app.AnonymizerApp.on_close
# Command callbacks receive (command, **kwargs) per Toga's contract.
_app.AnonymizerApp._show_main_window
_app.AnonymizerApp._cmd_anon_file_to_clipboard
_app.AnonymizerApp._cmd_anon_clipboard_to_clipboard
_app.AnonymizerApp._cmd_quit
_menubar.MenubarController._cmd_toggle_launch_at_login

# --- AppKit ObjC selectors and KVC setters --------------------------------
# Dispatched by the ObjC runtime / set on NSObject via KVC; vulture can't see
# either path.
_appkit.DragView.hitTest_
_appkit.DragView.draggingEntered_
_appkit.DragView.draggingUpdated_
_appkit.DragView.draggingExited_
_appkit.DragView.prepareForDragOperation_
_appkit.DragView.performDragOperation_
_appkit.DragView.concludeDragOperation_

# Strong refs assigned to keep ObjC objects alive across the Python/ObjC boundary.
_appkit.GlobalHotkeyMonitor._global_block
_appkit.GlobalHotkeyMonitor._local_block

# --- Public test API on UI controllers ------------------------------------
# Exercised by tests/ (not scanned by vulture).
_batch.BatchRunController.add_input
_batch.BatchRunController.clear_inputs
_menubar.MenubarController.stay_locked
_menubar.MenubarController.hotkey_monitor

# --- pkg_resources compatibility shim -------------------------------------
# pymorphy2 looks up pkg_resources.WorkingSet().iter_entry_points() via duck
# typing on a module injected into sys.modules at import time.
_ner._get_stoplist
_ner._ensure_pkg_resources

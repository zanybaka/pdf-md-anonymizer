"""Toga desktop UI over the in-process ``anonymizer`` core.

The core is imported directly (no daemon, no IPC) so the Natasha model loads
once inside this process. Batch work runs off the UI thread; per-file results
are delivered back to the event loop as they complete.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import toga
from toga.style.pack import COLUMN, ROW, Pack

from anonymizer.api import Options
from anonymizer.batch import CancelToken, process_files
from anonymizer.convert import default_pdf2md_command

_PENDING = "pending"

_SUPPORT_DIR = Path("~/Library/Application Support/pdf-md-anonymizer").expanduser()
_PREFS_FILE = _SUPPORT_DIR / "prefs.json"

def _load_prefs() -> dict:
    try:
        return json.loads(_PREFS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_prefs(prefs: dict) -> None:
    _SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    _PREFS_FILE.write_text(json.dumps(prefs, indent=2), encoding="utf-8")


def _pdf2md_available() -> bool:
    """Return True if a usable pdf2md executable is currently findable."""
    cmd = default_pdf2md_command()
    p = Path(cmd)
    if p.is_absolute():
        return p.is_file()
    return shutil.which(cmd) is not None


class AnonymizerApp(toga.App):
    def startup(self) -> None:
        self._inputs: list[Path] = []
        self._status: dict[Path, str] = {}
        self._output_paths: dict[Path, Path | None] = {}
        self._output_dir: Path | None = None
        self._cancel: CancelToken | None = None
        self._running = False
        self._start_time = 0.0
        self._durations: list[float] = []
        self._stage_text = ""
        self._setuptools_ready = threading.Event()
        self._setuptools_ready.set()  # assume ready; repaired below if not
        self._status_icon = None
        self._status_commands_added = False
        self._busy_count = 0  # active background tasks (drives status-bar animation)
        self._saved_status_icon_image = None  # original menu-bar icon for restore

        root = toga.Box(style=Pack(direction=COLUMN, margin=10, gap=8))

        file_row = toga.Box(style=Pack(direction=ROW, gap=6))
        file_row.add(toga.Button("Add files…", on_press=self.on_add_files))
        file_row.add(toga.Button("Clear", on_press=self.on_clear))
        file_row.add(toga.Button("Output folder…", on_press=self.on_pick_output))
        root.add(file_row)

        self.output_label = toga.Label("Output: next to each input file")
        root.add(self.output_label)

        self.map_switch = toga.Switch("Save replacement map", value=False)
        root.add(self.map_switch)

        prefs = _load_prefs()
        self.menubar_switch = toga.Switch(
            "Stay in menu bar when window is closed",
            value=prefs.get("stay_in_menubar", False),
            on_change=self._on_menubar_pref_change,
        )
        root.add(self.menubar_switch)

        self.table = toga.Table(
            columns=["File", "Status"],
            data=[],
            style=Pack(flex=1),
            on_activate=self.on_table_activate,
            on_select=self.on_table_select,
        )
        root.add(self.table)

        self.progress = toga.ProgressBar(max=1, value=0, style=Pack(flex=1))
        root.add(self.progress)
        self.status_label = toga.Label("Idle")
        root.add(self.status_label)

        run_row = toga.Box(style=Pack(direction=ROW, gap=6))
        self.run_button = toga.Button("Run", on_press=self.on_run)
        self.cancel_button = toga.Button(
            "Cancel", on_press=self.on_cancel, enabled=False
        )
        self.reveal_button = toga.Button(
            "Reveal in Finder", on_press=self.on_reveal, enabled=False
        )
        self.copy_button = toga.Button(
            "Copy", on_press=self.on_copy, enabled=False
        )
        run_row.add(self.run_button)
        run_row.add(self.cancel_button)
        run_row.add(self.reveal_button)
        run_row.add(self.copy_button)
        root.add(run_row)

        self.result_view = toga.MultilineTextInput(
            readonly=True, style=Pack(flex=1)
        )
        root.add(self.result_view)

        pdf_row = toga.Box(style=Pack(direction=ROW, gap=6))
        self.pdf_version_label = toga.Label("")
        self.pdf_action_button = toga.Button(
            "Install PDF backend", on_press=self.on_pdf_action
        )
        pdf_row.add(self.pdf_version_label)
        pdf_row.add(self.pdf_action_button)
        root.add(pdf_row)
        self._refresh_pdf_row()

        self.main_window = toga.MainWindow(title=self.formal_name)
        self.main_window.content = root

        self.commands.add(
            toga.Command(
                self._on_paste_files,
                text="Paste",
                shortcut=toga.Key.MOD_1 + "v",
                group=toga.Group.EDIT,
            ),
            toga.Command(
                lambda _: webbrowser.open("https://github.com/zanybaka/pdf-md-anonymizer"),
                text="View on GitHub",
                group=toga.Group.HELP,
            ),
        )

        self.main_window.on_close = self._on_window_close
        self.main_window.show()

        if prefs.get("stay_in_menubar", False):
            self._create_status_item()

        self._make_primary_button(self.run_button)
        self._setup_drag_drop()
        threading.Thread(target=self._warmup_ner, daemon=True).start()

        # Repair old installs that are missing setuptools / pkg_resources
        from anonymizer_ui import pdf_backend as _pb
        if _pb.is_installed() and not _pb._has_setuptools():
            self._setuptools_ready.clear()
            threading.Thread(
                target=self._repair_setuptools, daemon=True
            ).start()

    # --- menu-bar resident mode -----------------------------------------

    def _on_menubar_pref_change(self, widget) -> None:
        prefs = _load_prefs()
        prefs["stay_in_menubar"] = widget.value
        _save_prefs(prefs)
        if widget.value:
            self._create_status_item()
        else:
            self._remove_status_item()

    def _on_window_close(self, window) -> bool:
        if self.menubar_switch.value:
            self._hide_to_menubar()
            return False  # prevent close
        return True  # allow close → app quits

    def _log(self, msg: str) -> None:
        """Append a line to the result view (UI-thread safe, best-effort)."""
        try:
            self._prepend_to_result(f"[app] {msg}\n")
        except Exception:
            pass

    def _set_dock_visible(self, visible: bool) -> None:
        try:
            from rubicon.objc.runtime import load_library  # noqa: PLC0415
            load_library("AppKit")
            from rubicon.objc import ObjCClass  # noqa: PLC0415
            policy = 0 if visible else 2  # Regular=0, Accessory=2 (no Dock icon)
            ObjCClass("NSApplication").sharedApplication.setActivationPolicy_(policy)
        except Exception as exc:
            self._log(f"set_dock_visible({visible}) failed: {exc}")

    def _hide_to_menubar(self) -> None:
        self._create_status_item()
        try:
            self.main_window._impl.native.orderOut_(None)
        except Exception as exc:
            self._log(f"orderOut failed: {exc}")
        self._set_dock_visible(False)

    def _show_main_window(self, *args, **kwargs) -> None:
        self._set_dock_visible(True)
        try:
            from rubicon.objc.runtime import load_library  # noqa: PLC0415
            load_library("AppKit")
            from rubicon.objc import ObjCClass  # noqa: PLC0415
            # After leaving accessory mode the app is not frontmost; activate it
            # explicitly so the window comes forward without a Dock click.
            ObjCClass("NSApplication").sharedApplication.activateIgnoringOtherApps_(
                True
            )
            self.main_window._impl.native.makeKeyAndOrderFront_(None)
        except Exception as exc:
            self._log(f"show_main_window failed: {exc}")

    def _create_status_item(self) -> None:
        """Add the menu-bar status icon and its commands (idempotent).

        Uses Toga's native ``MenuStatusIcon`` so command dispatch goes through
        Toga's own command machinery — no hand-rolled NSStatusItem target-action.
        Toga's standard About/Quit commands are dropped so we control ordering;
        Quit sits in its own section to get a separator above it.
        """
        try:
            if self._status_icon is None:
                self._status_icon = toga.MenuStatusIcon(text=self.formal_name)
            if self._status_icon not in self.status_icons:
                self.status_icons.add(self._status_icon)
                self._style_status_icon()
            if not self._status_commands_added:
                # CommandSet resolves .pop() to MutableSet.pop() (no args), so
                # remove Toga's auto-added standard commands by id via __delitem__.
                for _cmd_id in ("about", "request_exit"):
                    try:
                        del self.status_icons.commands[_cmd_id]
                    except KeyError:
                        pass
                self.status_icons.commands.add(
                    toga.Command(
                        self._show_main_window,
                        text="Show Window",
                        group=self._status_icon,
                        section=0,
                        order=0,
                    ),
                    toga.Command(
                        self._cmd_anon_file_to_clipboard,
                        text="Anonymize File to Clipboard…",
                        group=self._status_icon,
                        section=0,
                        order=1,
                    ),
                    toga.Command(
                        self._cmd_anon_clipboard_to_clipboard,
                        text="Anonymize Clipboard",
                        group=self._status_icon,
                        section=0,
                        order=2,
                    ),
                    toga.Command(
                        self._cmd_quit,
                        text="Quit",
                        group=self._status_icon,
                        section=1,
                        order=0,
                    ),
                )
                self._status_commands_added = True
        except Exception as exc:
            self._log(f"create_status_item failed: {exc}")

    def _style_status_icon(self) -> None:
        """Shrink Toga's 22px app-icon image so it sits with padding in the bar."""
        try:
            from rubicon.objc.types import NSSize  # noqa: PLC0415

            native = self._status_icon._impl.native  # NSStatusItem
            existing = native.button.image
            if existing is not None:
                existing.setSize_(NSSize(19, 19))
        except Exception as exc:
            self._log(f"style_status_icon failed: {exc}")

    def _remove_status_item(self) -> None:
        if self._status_icon is None:
            return
        try:
            if self._status_icon in self.status_icons:
                self.status_icons.remove(self._status_icon)
        except Exception as exc:
            self._log(f"remove_status_item failed: {exc}")

    def _cmd_anon_file_to_clipboard(self, command, **kwargs) -> None:
        """Sync handler: flip activation policy in the click event context,
        then defer activate + runModal to the next run-loop tick.

        Root cause of the "panel opens behind other apps" bug on macOS 14/15:
        ``setActivationPolicy(.regular)`` only takes effect after the run loop
        iterates — WindowServer needs that tick to register the app as
        foreground-eligible.  If we call ``runModal`` synchronously in the same
        handler, the panel is shown BEFORE the policy change propagates and
        ends up behind other windows.

        Fix: flip the policy here (sync click context), then schedule the
        activate+runModal on the asyncio loop so it runs on the next tick.
        """
        try:
            from rubicon.objc.runtime import load_library  # noqa: PLC0415
            load_library("AppKit")
            from rubicon.objc import ObjCClass  # noqa: PLC0415
            ObjCClass("NSApplication").sharedApplication.setActivationPolicy_(0)
        except Exception as exc:
            self._log(f"setActivationPolicy failed: {exc}")
        asyncio.ensure_future(self._anon_file_to_clipboard())

    async def _cmd_anon_clipboard_to_clipboard(self, command, **kwargs) -> None:
        await self._anon_clipboard_to_clipboard()

    def _cmd_quit(self, command, **kwargs) -> None:
        self.exit()

    async def _anon_file_to_clipboard(self) -> None:
        """Wait for the run loop to process the policy change, then show panel."""
        # One run-loop yield so the .accessory→.regular policy change reaches
        # WindowServer before the activation request.  50ms is conservative —
        # a single tick is usually enough.
        await asyncio.sleep(0.05)

        path = self._pick_file_and_restore_policy("Select file to anonymize")
        if not path:
            return
        await self._do_anon_file_to_clipboard(path)

    def _pick_file_and_restore_policy(self, title: str) -> "Path | None":
        """Activate the app, show NSOpenPanel modally, then restore Accessory.

        Assumes the activation policy has already been switched to Regular and
        a run-loop tick has happened.  Forces the panel to the front with
        ``orderFrontRegardless`` and a high window level as belt-and-suspenders.
        """
        try:
            from rubicon.objc.runtime import load_library  # noqa: PLC0415
            load_library("AppKit")
            from rubicon.objc import ObjCClass  # noqa: PLC0415

            NSApp = ObjCClass("NSApplication").sharedApplication
            try:
                NSApp.activate()           # macOS 14+
            except Exception:
                NSApp.activateIgnoringOtherApps_(True)  # legacy

            panel = ObjCClass("NSOpenPanel").openPanel()
            panel.title = title
            panel.canChooseFiles = True
            panel.canChooseDirectories = False
            panel.allowsMultipleSelection = False
            try:
                arr = ObjCClass("NSMutableArray").alloc().init()
                arr.addObject_("pdf")
                arr.addObject_("md")
                panel.allowedFileTypes = arr
            except Exception:
                pass

            # Belt-and-suspenders: high level + force front regardless of
            # app-activation state.  Also center on the active screen (without
            # this NSOpenPanel restores the last-used position, which after a
            # menu-bar invocation tends to land in the bottom-left corner).
            try:
                panel.setLevel_(8)  # NSModalPanelWindowLevel
            except Exception:
                pass
            try:
                panel.orderFrontRegardless()
            except Exception:
                pass
            try:
                panel.center()
            except Exception:
                pass

            result = int(panel.runModal())

            # Restore Accessory (this handler is only reachable from the
            # status-bar menu — i.e. menu-bar-resident mode).
            try:
                NSApp.setActivationPolicy_(2)
            except Exception:
                pass

            if result == 1:  # NSModalResponseOK
                urls = panel.URLs
                # NB: rubicon-objc wraps NSArray as ObjCListInstance, so
                # `urls.count` resolves to Python's list.count(value) method,
                # not NSArray's count property — use len()/indexing instead.
                if len(urls) > 0:
                    return Path(str(urls[0].path))
            return None

        except Exception as exc:
            self._log(f"_pick_file_and_restore_policy failed: {exc}")
            return None

    def _set_status_busy(self, busy: bool) -> None:
        """Swap the menu-bar icon to a distinctive symbol while a task runs.

        ``button.title`` alongside an image is unreliable on NSStatusBarButton
        (Toga's MenuStatusIcon forces ``imagePosition = NSImageOnly``), so we
        change the icon image itself — synchronous, immediately visible, and
        does not depend on the asyncio scheduler getting CPU time while a
        background worker thread is hot.

        Uses ``setImage_``/``setTemplate_`` explicitly (rubicon-objc's property
        syntax sometimes silently no-ops on these) and an explicit size so the
        replacement icon visibly differs from the resized 19px app icon.
        """
        if self._status_icon is None:
            return
        try:
            from rubicon.objc import ObjCClass  # noqa: PLC0415
            from rubicon.objc.types import NSSize  # noqa: PLC0415
            button = self._status_icon._impl.native.button
        except Exception as exc:
            self._log(f"_set_status_busy: no button: {exc}")
            return

        if busy:
            if self._saved_status_icon_image is None:
                try:
                    self._saved_status_icon_image = button.image
                except Exception:
                    pass
            try:
                NSImage = ObjCClass("NSImage")
                # Pick a symbol that is obviously different from a circular
                # app icon.  Hourglass reads as "working" at a glance.
                busy_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                    "hourglass", "Working"
                )
                if busy_img is None:
                    # Older API fallback if SF Symbols are unavailable
                    busy_img = NSImage.imageNamed_("NSRefreshTemplate")
                if busy_img is not None:
                    busy_img.setSize_(NSSize(18, 18))
                    busy_img.setTemplate_(True)  # adapts to dark/light menu bar
                    button.setImage_(busy_img)
                else:
                    self._log("_set_status_busy: no busy image available")
            except Exception as exc:
                self._log(f"_set_status_busy(True) failed: {exc}")
        else:
            if self._saved_status_icon_image is not None:
                try:
                    button.setImage_(self._saved_status_icon_image)
                except Exception as exc:
                    self._log(f"_set_status_busy(False) failed: {exc}")
                self._saved_status_icon_image = None

    def _begin_busy(self) -> None:
        """Mark a background task started; swap to busy icon on first call."""
        self._busy_count += 1
        if self._busy_count == 1:
            self._set_status_busy(True)

    def _end_busy(self) -> None:
        """Mark a background task finished; restore the idle icon at zero."""
        if self._busy_count > 0:
            self._busy_count -= 1
        if self._busy_count == 0:
            self._set_status_busy(False)

    async def _do_anon_file_to_clipboard(self, path: Path) -> None:
        """Anonymize *path* in a worker thread and write result to clipboard."""
        self._send_notification("Anonymizing…", path.name)
        self._begin_busy()
        try:
            loop = self.loop
            result_box: list[str | None] = [None]
            error_box: list[str | None] = [None]
            done_event = asyncio.Event()

            def _work() -> None:
                try:
                    from anonymizer.batch import read_input  # noqa: PLC0415
                    from anonymizer.api import anonymize, Options  # noqa: PLC0415
                    text = read_input(path)
                    result_box[0] = anonymize(text, Options()).text
                except Exception as exc:  # noqa: BLE001
                    error_box[0] = str(exc)
                finally:
                    loop.call_soon_threadsafe(done_event.set)

            threading.Thread(target=_work, daemon=True).start()
            await done_event.wait()

            if error_box[0]:
                self._send_notification("Anonymization failed", error_box[0][:120])
            else:
                self._copy_to_clipboard(result_box[0] or "")
                self._send_notification("Anonymized to clipboard", path.name)
        finally:
            self._end_busy()

    async def _anon_clipboard_to_clipboard(self) -> None:
        """Clipboard → clipboard: anonymize clipboard text in-place."""
        text_str = self._read_clipboard()
        if not text_str:
            self._send_notification("Clipboard is empty", "No text found to anonymize")
            return

        self._send_notification("Anonymizing…", "Clipboard text")
        self._begin_busy()
        try:
            loop = self.loop
            result_box: list[str | None] = [None]
            error_box: list[str | None] = [None]
            done_event = asyncio.Event()

            def _work() -> None:
                try:
                    from anonymizer.api import anonymize, Options  # noqa: PLC0415
                    result_box[0] = anonymize(text_str, Options()).text
                except Exception as exc:  # noqa: BLE001
                    error_box[0] = str(exc)
                finally:
                    loop.call_soon_threadsafe(done_event.set)

            threading.Thread(target=_work, daemon=True).start()
            await done_event.wait()

            if error_box[0]:
                self._send_notification("Anonymization failed", error_box[0][:120])
            else:
                self._copy_to_clipboard(result_box[0] or "")
                self._send_notification("Anonymized to clipboard", "Clipboard text anonymized")
        finally:
            self._end_busy()

    def _send_notification(self, title: str, body: str) -> None:
        try:
            from rubicon.objc.runtime import load_library  # noqa: PLC0415
            load_library("Foundation")
            from rubicon.objc import ObjCClass  # noqa: PLC0415
            n = ObjCClass("NSUserNotification").alloc().init()
            n.title = title
            n.informativeText = body
            ObjCClass(
                "NSUserNotificationCenter"
            ).defaultUserNotificationCenter.deliverNotification_(n)
        except Exception:
            pass

    # --- file selection -------------------------------------------------

    def _add_inputs(self, paths) -> None:
        """Append paths to the input list, filtering to .pdf/.md and deduplicating."""
        changed = False
        for raw in paths:
            p = Path(raw)
            if p.suffix.lower() in {".pdf", ".md"} and p not in self._inputs:
                self._inputs.append(p)
                self._status[p] = _PENDING
                changed = True
        if changed:
            self._refresh_table()

    async def on_add_files(self, widget) -> None:
        try:
            paths = await self.main_window.dialog(
                toga.OpenFileDialog(
                    "Select PDF or Markdown files",
                    file_types=["pdf", "md"],
                    multiple_select=True,
                )
            )
        except ValueError:
            paths = None
        if paths:
            self._add_inputs(paths)

    async def on_clear(self, widget) -> None:
        if self._running:
            return
        self._inputs.clear()
        self._status.clear()
        self._output_paths.clear()
        self._refresh_table()
        self.result_view.value = ""
        self.reveal_button.enabled = False
        self.copy_button.enabled = False

    async def on_pick_output(self, widget) -> None:
        folder = await self.main_window.dialog(
            toga.SelectFolderDialog("Select output folder")
        )
        if folder:
            self._output_dir = Path(folder)
            self.output_label.text = f"Output: {self._output_dir}"

    # --- run / cancel ---------------------------------------------------

    def _show_drop_highlight(self, show: bool) -> None:
        if self._running:
            return
        self.status_label.text = "Drop files here…" if show else "Ready"

    def _on_paste_files(self, widget) -> None:
        """Paste files copied from Finder (Cmd+V → NSFilenamesPboardType)."""
        try:
            from rubicon.objc.runtime import load_library  # noqa: PLC0415
            load_library("AppKit")
            from rubicon.objc import ObjCClass  # noqa: PLC0415
            pb = ObjCClass("NSPasteboard").generalPasteboard
            files = pb.propertyListForType_("NSFilenamesPboardType")
            if files is not None:
                n = int(files.count)
                if n > 0:
                    self._add_inputs(
                        [str(files.objectAtIndex_(i)) for i in range(n)]
                    )
        except Exception:
            pass

    def _setup_drag_drop(self) -> None:
        """Add a transparent NSView overlay that accepts file drag-and-drop."""
        try:
            from rubicon.objc.runtime import load_library, objc_id  # noqa: PLC0415
            load_library("AppKit")
            from rubicon.objc import ObjCClass, objc_method  # noqa: PLC0415
            from rubicon.objc.types import NSPoint  # noqa: PLC0415
            from ctypes import c_ulong

            NSView = ObjCClass("NSView")
            app = self

            class _AnonymDropOverlay(NSView):
                """Transparent overlay — passes clicks through, handles file drops."""

                @objc_method
                def hitTest_(self, point: NSPoint) -> objc_id:
                    return None  # nil → mouse events fall through to views below

                @objc_method
                def draggingEntered_(self, info) -> c_ulong:
                    app._show_drop_highlight(True)
                    return 1  # NSDragOperationCopy

                @objc_method
                def draggingUpdated_(self, info) -> c_ulong:
                    return 1  # NSDragOperationCopy

                @objc_method
                def draggingExited_(self, info) -> None:
                    app._show_drop_highlight(False)

                @objc_method
                def prepareForDragOperation_(self, info) -> bool:
                    return True

                @objc_method
                def performDragOperation_(self, info) -> bool:
                    try:
                        pb = info.draggingPasteboard
                        if pb is not None:
                            files = pb.propertyListForType_("NSFilenamesPboardType")
                            if files is not None:
                                n = int(files.count)
                                if n > 0:
                                    app._add_inputs(
                                        [str(files.objectAtIndex_(i)) for i in range(n)]
                                    )
                    except Exception:
                        pass
                    app._show_drop_highlight(False)
                    return True

                @objc_method
                def concludeDragOperation_(self, info) -> None:
                    pass

            self._drop_overlay_class = _AnonymDropOverlay  # keep Python class alive

            ns_window = self.main_window._impl.native
            content_view = ns_window.contentView

            overlay = _AnonymDropOverlay.alloc().initWithFrame_(content_view.bounds)
            # NSViewWidthSizable (2) | NSViewHeightSizable (8) → fills superview
            overlay.autoresizingMask = 10
            overlay.registerForDraggedTypes_(
                ObjCClass("NSArray").arrayWithObject_("NSFilenamesPboardType")
            )
            content_view.addSubview_(overlay)
            self._drop_overlay = overlay  # keep ObjC instance alive

        except Exception:
            pass

    @staticmethod
    def _make_primary_button(button: toga.Button) -> None:
        """Make *button* the default (blue, Enter-key) button on macOS Cocoa."""
        try:
            button._impl.native.keyEquivalent = "\r"
        except AttributeError:
            pass

    def _warmup_ner(self) -> None:
        self.loop.call_soon_threadsafe(self._on_warmup_start)

        def on_step(msg: str) -> None:
            self.loop.call_soon_threadsafe(self._on_warmup_step, msg)

        try:
            from anonymizer.detect.ner import warmup
            warmup(on_step=on_step)
        except Exception:
            pass
        finally:
            self.loop.call_soon_threadsafe(self._on_warmup_done)

    def _on_warmup_start(self) -> None:
        if self._running:
            return
        self.progress.max = None
        self.progress.start()
        self.status_label.text = "Loading NER model…"

    def _on_warmup_step(self, msg: str) -> None:
        if self._running:
            return
        self.status_label.text = f"Loading NER model: {msg}"

    def _on_warmup_done(self) -> None:
        if self._running:
            return
        self.progress.stop()
        self.progress.max = 1
        self.progress.value = 0
        self.status_label.text = "Ready"

    def _repair_setuptools(self) -> None:
        try:
            from anonymizer_ui import pdf_backend
            pdf_backend.ensure_setuptools()
        except Exception:
            pass
        finally:
            self._setuptools_ready.set()

    async def on_run(self, widget) -> None:
        if self._running or not self._inputs:
            if not self._inputs:
                self.status_label.text = "No files selected"
            return

        has_pdf = any(p.suffix.lower() == ".pdf" for p in self._inputs)
        if has_pdf and not _pdf2md_available():
            await self._handle_missing_pdf_backend()

        if has_pdf and not self._setuptools_ready.is_set():
            self.status_label.text = "Finishing backend setup…"
            await asyncio.get_event_loop().run_in_executor(
                None, self._setuptools_ready.wait
            )

        self._begin_run()

    async def _handle_missing_pdf_backend(self) -> None:
        await self.on_pdf_action(None)


    def _begin_run(self) -> None:
        """Start the batch anonymization run (called from on_run)."""
        output_dir = self._output_dir if self._output_dir else (lambda p: p.parent)
        map_dir = (self._output_dir if self._output_dir else (lambda p: p.parent)) if self.map_switch.value else None
        options = Options()
        self._cancel = CancelToken()
        self._running = True
        self._durations = []
        self._stage_text = ""
        self._output_paths = {}
        self._start_time = time.monotonic()
        for path in self._inputs:
            self._status[path] = _PENDING
        self._refresh_table()

        self.result_view.value = ""
        self.progress.max = len(self._inputs)
        self.progress.value = 0
        self.run_button.enabled = False
        self.cancel_button.enabled = True
        self.map_switch.enabled = False

        threading.Thread(
            target=self._worker,
            args=(list(self._inputs), output_dir, map_dir, options, self._cancel),
            daemon=True,
        ).start()
        asyncio.create_task(self._tick())

    async def on_cancel(self, widget) -> None:
        if self._cancel is not None:
            self._cancel.cancel()
        self.cancel_button.enabled = False
        self.status_label.text = "Cancelling…"

    # --- worker (off the UI thread) -------------------------------------

    def _worker(self, inputs, output_dir, map_dir, options, cancel) -> None:
        def on_stage(index: int, total: int, path: Path, stage: str) -> None:
            label = "converting PDF…" if stage == "converting" else "detecting…"
            self.loop.call_soon_threadsafe(
                self._on_stage_update, f"[{index}/{total}] {path.name}: {label}"
            )

        for result in process_files(
            inputs,
            output_dir=output_dir,
            map_dir=map_dir,
            options=options,
            cancel=cancel,
            on_stage=on_stage,
        ):
            self.loop.call_soon_threadsafe(self._on_file_result, result)
        self.loop.call_soon_threadsafe(self._on_batch_done)

    def _on_file_result(self, result) -> None:
        path = Path(result.input_path)
        self._status[path] = result.status
        if result.status == "done":
            self._durations.append(result.duration)
            self._output_paths[path] = (
                Path(result.output_path) if result.output_path else None
            )
            self._prepend_to_result(f"✓ {path.name} ({result.duration:.1f}s)\n")
        elif result.status == "failed" and result.error:
            self._prepend_to_result(f"✗ {path.name}: {result.error}\n")
        self.progress.value = self._processed()
        self._refresh_table()
        self.status_label.text = self._progress_text()

    def _on_batch_done(self) -> None:
        self._running = False
        self._stage_text = ""
        self.run_button.enabled = True
        self.cancel_button.enabled = False
        self.map_switch.enabled = True
        self.status_label.text = self._progress_text() + " — finished"

    async def _tick(self) -> None:
        while self._running:
            self.status_label.text = self._progress_text()
            await asyncio.sleep(1)

    # --- helpers --------------------------------------------------------

    # --- PDF backend helpers --------------------------------------------

    def _refresh_pdf_row(self) -> None:
        from anonymizer_ui import pdf_backend
        installed = pdf_backend.is_installed()
        ver = pdf_backend.installed_version() if installed else None
        has_build_python = (
            pdf_backend._find_build_python() is not None
            or ".app/Contents/MacOS/" not in sys.executable
        )
        if installed:
            self.pdf_version_label.text = f"PDF backend: v{ver}" if ver else "PDF backend: installed"
            self.pdf_action_button.text = "Update"
        else:
            self.pdf_version_label.text = "PDF backend: not installed"
            self.pdf_action_button.text = "Install PDF backend"
        self.pdf_action_button.enabled = has_build_python

    async def on_pdf_action(self, widget) -> None:
        from anonymizer_ui import pdf_backend
        has_build_python = (
            pdf_backend._find_build_python() is not None
            or ".app/Contents/MacOS/" not in sys.executable
        )
        if not has_build_python:
            await self.main_window.dialog(toga.InfoDialog(
                "Python 3 required",
                "Installing or updating the PDF backend requires Python 3 "
                "outside the app bundle.\n\n"
                "Install it with Homebrew:\n"
                "    brew install python3\n\n"
                "Or download from https://python.org",
            ))
            return
        installed = pdf_backend.is_installed()
        title = "Update PDF backend" if installed else "Install PDF backend"
        body = (
            "This will download pdf-to-markdown from git (needs network).\n\n"
            + ("Update to the latest revision?" if installed else "Install now?")
        )
        if not await self.main_window.dialog(toga.QuestionDialog(title, body)):
            return
        await self._run_pdf_backend_action(upgrade=installed)

    async def _run_pdf_backend_action(self, *, upgrade: bool) -> None:
        self.pdf_action_button.enabled = False
        verb = "Updating" if upgrade else "Installing"
        self.result_view.value = f"{verb} PDF backend…\n"
        self.status_label.text = f"{verb} PDF backend…"

        self.progress.max = None
        self.progress.start()

        loop = self.loop
        done: asyncio.Event = asyncio.Event()
        success_box = [False]

        def _on_line(line: str) -> None:
            loop.call_soon_threadsafe(self._prepend_to_result, line + "\n")

        def _work() -> None:
            try:
                from anonymizer_ui import pdf_backend
                if upgrade:
                    pdf_backend.update(on_line=_on_line)
                else:
                    pdf_backend.install(on_line=_on_line)
                success_box[0] = True
            except Exception as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(
                    self._prepend_to_result, f"\n{verb} failed: {exc}\n"
                )
            finally:
                loop.call_soon_threadsafe(done.set)

        threading.Thread(target=_work, daemon=True).start()
        await done.wait()

        self.progress.stop()
        self.progress.max = 1
        self.progress.value = 0

        self._refresh_pdf_row()
        if success_box[0]:
            self.status_label.text = f"PDF backend {verb.lower()[:-3]}ed."
            self._prepend_to_result(f"PDF backend {verb.lower()[:-3]}ed successfully.\n\n")
        else:
            self.status_label.text = f"{verb} failed."

    def _append_to_result(self, text: str) -> None:
        self.result_view.value = (self.result_view.value or "") + text

    def _prepend_to_result(self, text: str) -> None:
        self.result_view.value = text + (self.result_view.value or "")

    def _processed(self) -> int:
        return sum(
            1 for p in self._inputs if self._status.get(p, _PENDING) != _PENDING
        )

    def _on_stage_update(self, text: str) -> None:
        self._stage_text = text
        self.status_label.text = self._progress_text()
        self._prepend_to_result(text + "\n")

    def _progress_text(self) -> str:
        total = len(self._inputs)
        done = self._processed()
        elapsed = time.monotonic() - self._start_time if self._running else 0.0
        text = f"{done}/{total} files, elapsed {elapsed:.0f}s"
        if self._durations and done < total:
            avg = sum(self._durations) / len(self._durations)
            text += f", ETA {avg * (total - done):.0f}s"
        if self._stage_text:
            text += f" — {self._stage_text}"
        return text

    def _selected_output(self) -> Path | None:
        """Return the output path for the currently selected done row, or None."""
        row = self.table.selection
        if row is None:
            return None
        for i, item in enumerate(self.table.data):
            if item is row and i < len(self._inputs):
                out = self._output_paths.get(self._inputs[i])
                return out if out and out.is_file() else None
        return None

    def on_table_select(self, widget) -> None:
        has_output = self._selected_output() is not None
        self.reveal_button.enabled = has_output
        self.copy_button.enabled = has_output

    def on_table_activate(self, widget, row) -> None:
        for i, item in enumerate(widget.data):
            if item is row:
                if i < len(self._inputs):
                    out = self._output_paths.get(self._inputs[i])
                    if out and out.is_file():
                        subprocess.run(["open", "-R", str(out)])
                return

    def on_reveal(self, widget) -> None:
        out = self._selected_output()
        if out:
            subprocess.run(["open", "-R", str(out)])

    def on_copy(self, widget) -> None:
        out = self._selected_output()
        if out:
            self._copy_to_clipboard(out.read_text(encoding="utf-8"))

    @staticmethod
    def _read_clipboard() -> "str | None":
        try:
            from rubicon.objc.runtime import load_library  # noqa: PLC0415
            load_library("AppKit")
            from rubicon.objc import ObjCClass  # noqa: PLC0415
            pb = ObjCClass("NSPasteboard").generalPasteboard
            raw = pb.stringForType_("public.utf8-plain-text")
            return str(raw) if raw is not None else None
        except Exception:
            try:
                result = subprocess.run(["pbpaste"], capture_output=True, text=True)
                return result.stdout or None
            except Exception:
                return None

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        try:
            from rubicon.objc.runtime import load_library  # noqa: PLC0415
            load_library("AppKit")
            from rubicon.objc import ObjCClass  # noqa: PLC0415
            pb = ObjCClass("NSPasteboard").generalPasteboard
            pb.clearContents()
            pb.setString_forType_(text, "public.utf8-plain-text")
        except Exception:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"))

    def _refresh_table(self) -> None:
        def _status_label(p: Path) -> str:
            s = self._status.get(p, _PENDING)
            return "📂 done" if s == "done" else s

        self.table.data = [
            (p.name, _status_label(p)) for p in self._inputs
        ]


def main() -> AnonymizerApp:
    return AnonymizerApp("PDF-MD Anonymizer", "ru.ati.anonymizer")

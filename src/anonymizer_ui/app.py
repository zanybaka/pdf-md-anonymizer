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
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path

import toga
from toga.style.pack import COLUMN, ROW, Pack

from anonymizer.api import Options
from anonymizer.batch import CancelToken, FileStatus, OutputPolicy, process_files
from anonymizer.convert import default_pdf2md_command
from anonymizer_ui import appkit_bridge
from anonymizer_ui import drag_drop_overlay
from anonymizer_ui.batch_controller import BatchRunController
from anonymizer_ui.menubar_controller import MenuBarController
from anonymizer_ui.pdf_backend_controller import PdfBackendController

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
        self._batch = BatchRunController(
            on_progress=self._on_batch_progress,
            on_file_result=self._on_batch_file_result,
            on_done=self._on_batch_done,
            on_log=self._prepend_to_result,
        )
        # PdfBackendController is set up after widgets exist (needs label/button refs)
        self._pdf_ctrl: PdfBackendController | None = None
        self._menubar = MenuBarController(self)
        self._output_dir: Path | None = None

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
            self._menubar.create_status_item()

        # Set up PDF backend controller (needs widget refs to be ready)
        self._pdf_ctrl = PdfBackendController(
            on_version_label=lambda t: setattr(self.pdf_version_label, "text", t),
            on_action_button=lambda t, e: (
                setattr(self.pdf_action_button, "text", t),
                setattr(self.pdf_action_button, "enabled", e),
            ),
            on_log=self._prepend_to_result,
            on_progress_start=self._pdf_progress_start,
            on_progress_stop=self._pdf_progress_stop,
            on_status=lambda t: setattr(self.status_label, "text", t),
            loop=self.loop,
        )
        self._pdf_ctrl.refresh_row()
        self._setuptools_ready = self._pdf_ctrl.start_setuptools_repair_if_needed()

        self._make_primary_button(self.run_button)
        self._setup_drag_drop()
        threading.Thread(target=self._warmup_ner, daemon=True).start()

    # --- forwarding properties (backward compat with SimpleNamespace tests) -

    @property
    def _inputs(self) -> list[Path]:
        return self._batch.inputs

    @property
    def _status(self) -> dict[Path, str]:
        return self._batch.status

    @property
    def _output_paths(self) -> dict[Path, Path | None]:
        return self._batch.output_paths

    @property
    def _running(self) -> bool:
        return self._batch.running

    # --- menu-bar resident mode -----------------------------------------

    def _on_menubar_pref_change(self, widget) -> None:
        prefs = _load_prefs()
        prefs["stay_in_menubar"] = widget.value
        _save_prefs(prefs)
        if widget.value:
            self._menubar.create_status_item()
        else:
            self._menubar.remove_status_item()

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

    def _hide_to_menubar(self) -> None:
        self._menubar.hide_window_to_menubar()

    def _show_main_window(self, *args, **kwargs) -> None:
        self._menubar.show_main_window()

    def _create_status_item(self) -> None:
        self._menubar.create_status_item()

    def _remove_status_item(self) -> None:
        self._menubar.remove_status_item()

    def _cmd_anon_file_to_clipboard(self, command, **kwargs) -> None:
        try:
            appkit_bridge.set_dock_visible(True)  # switch to Regular policy
        except appkit_bridge.AppKitError as exc:
            self._log(str(exc))
        asyncio.ensure_future(self._anon_file_to_clipboard())

    async def _cmd_anon_clipboard_to_clipboard(self, command, **kwargs) -> None:
        await self._anon_clipboard_to_clipboard()

    def _cmd_quit(self, command, **kwargs) -> None:
        self.exit()

    async def _anon_file_to_clipboard(self) -> None:
        await asyncio.sleep(0.05)
        path = self._pick_file_and_restore_policy("Select file to anonymize")
        if not path:
            return
        await self._do_anon_file_to_clipboard(path)

    def _pick_file_and_restore_policy(self, title: str) -> "Path | None":
        try:
            return appkit_bridge.pick_file(title, ["pdf", "md"])
        except appkit_bridge.AppKitError as exc:
            self._log(str(exc))
            return None

    def _begin_busy(self) -> None:
        self._menubar.begin_busy()

    def _end_busy(self) -> None:
        self._menubar.end_busy()

    async def _do_anon_file_to_clipboard(self, path: Path) -> None:
        from anonymizer.batch import read_input  # noqa: PLC0415
        await self._anonymize_in_thread(
            source=lambda: read_input(path),
            busy_title="Anonymizing…",
            busy_body=path.name,
            done_title="Anonymized to clipboard",
            done_body=path.name,
        )

    async def _anon_clipboard_to_clipboard(self) -> None:
        await self._anonymize_in_thread(
            source=lambda: self._read_clipboard() or "",
            busy_title="Anonymizing…",
            busy_body="Clipboard text",
            done_title="Anonymized to clipboard",
            done_body="Clipboard text anonymized",
        )

    async def _anonymize_in_thread(
        self,
        *,
        source: Callable[[], str],
        busy_title: str,
        busy_body: str,
        done_title: str,
        done_body: str,
    ) -> None:
        self._send_notification(busy_title, busy_body)
        self._begin_busy()
        try:
            loop = self.loop
            result_box: list[str | None] = [None]
            error_box: list[str | None] = [None]
            empty_box: list[bool] = [False]
            done_event = asyncio.Event()

            def _work() -> None:
                try:
                    text = source()
                    if not text:
                        empty_box[0] = True
                        return
                    from anonymizer.api import anonymize, Options  # noqa: PLC0415
                    result_box[0] = anonymize(text, Options()).text
                except Exception as exc:  # noqa: BLE001
                    error_box[0] = str(exc)
                finally:
                    loop.call_soon_threadsafe(done_event.set)

            threading.Thread(target=_work, daemon=True).start()
            await done_event.wait()

            if empty_box[0]:
                self._send_notification("Clipboard is empty", "No text found to anonymize")
            elif error_box[0]:
                self._send_notification("Anonymization failed", error_box[0][:120])
            else:
                self._copy_to_clipboard(result_box[0] or "")
                self._send_notification(done_title, done_body)
        finally:
            self._end_busy()

    def _send_notification(self, title: str, body: str) -> None:
        try:
            appkit_bridge.deliver_notification(title, body)
        except appkit_bridge.AppKitError:
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
        try:
            filenames = appkit_bridge.pasteboard_filenames()
            if filenames:
                self._add_inputs(filenames)
        except appkit_bridge.AppKitError:
            pass

    def _setup_drag_drop(self) -> None:
        try:
            self._drop_overlay = drag_drop_overlay.setup(
                self.main_window,
                on_paths=self._add_inputs,
                on_highlight=self._show_drop_highlight,
            )
        except appkit_bridge.AppKitError:
            pass

    @staticmethod
    def _make_primary_button(button: toga.Button) -> None:
        try:
            button._impl.native.keyEquivalent = "\r"
        except AttributeError:
            pass

    def _warmup_ner(self) -> None:
        self.loop.call_soon_threadsafe(self._on_warmup_start)

        def on_step(msg: str) -> None:
            self.loop.call_soon_threadsafe(self._on_warmup_step, msg)

        try:
            from anonymizer.detect.ner import warmup  # noqa: PLC0415
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
        if self._output_dir:
            output_policy = OutputPolicy.into_directory(self._output_dir)
        else:
            output_policy = OutputPolicy.next_to_input()
        map_policy: OutputPolicy | None = None
        if self.map_switch.value:
            map_policy = output_policy
        options = Options()

        self.result_view.value = ""
        self.progress.max = len(self._inputs)
        self.progress.value = 0
        self.run_button.enabled = False
        self.cancel_button.enabled = True
        self.map_switch.enabled = False

        self._batch.start(
            output_policy=output_policy,
            map_policy=map_policy,
            options=options,
            loop=self.loop,
        )

    async def on_cancel(self, widget) -> None:
        self._batch.cancel()
        self.cancel_button.enabled = False
        self.status_label.text = "Cancelling…"

    # --- batch callbacks (called by BatchRunController on the UI thread) -

    def _on_batch_progress(self, text: str) -> None:
        self.status_label.text = text

    def _on_batch_file_result(self, result) -> None:
        path = Path(result.input_path)
        if result.status == FileStatus.DONE:
            self._prepend_to_result(f"✓ {path.name} ({result.duration:.1f}s)\n")
        elif result.status == FileStatus.FAILED and result.error:
            self._prepend_to_result(f"✗ {path.name}: {result.error}\n")
        self.progress.value = self._batch.processed()
        self._refresh_table()

    def _on_batch_done(self) -> None:
        self.run_button.enabled = True
        self.cancel_button.enabled = False
        self.map_switch.enabled = True
        self.status_label.text = self._batch.progress_text() + " — finished"

    # --- PDF backend helpers --------------------------------------------

    def _pdf_progress_start(self) -> None:
        self.result_view.value = ""
        self.progress.max = None
        self.progress.start()

    def _pdf_progress_stop(self) -> None:
        self.progress.stop()
        self.progress.max = 1
        self.progress.value = 0

    async def on_pdf_action(self, widget) -> None:
        from anonymizer_ui import pdf_backend  # noqa: PLC0415
        if not pdf_backend.can_install():
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
        assert self._pdf_ctrl is not None
        await self._pdf_ctrl.run_action(upgrade=installed)

    # --- helpers --------------------------------------------------------

    def _append_to_result(self, text: str) -> None:
        self.result_view.value = (self.result_view.value or "") + text

    def _prepend_to_result(self, text: str) -> None:
        self.result_view.value = text + (self.result_view.value or "")

    def _selected_output(self) -> Path | None:
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
            return appkit_bridge.pasteboard_string()
        except appkit_bridge.AppKitError:
            try:
                result = subprocess.run(["pbpaste"], capture_output=True, text=True)
                return result.stdout or None
            except Exception:
                return None

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        try:
            appkit_bridge.pasteboard_set_string(text)
        except appkit_bridge.AppKitError:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"))

    def _refresh_table(self) -> None:
        def _status_label(p: Path) -> str:
            s = self._status.get(p, _PENDING)
            return "📂 done" if s == FileStatus.DONE else s

        self.table.data = [
            (p.name, _status_label(p)) for p in self._inputs
        ]


def main() -> AnonymizerApp:
    return AnonymizerApp("PDF-MD Anonymizer", "ru.ati.anonymizer")

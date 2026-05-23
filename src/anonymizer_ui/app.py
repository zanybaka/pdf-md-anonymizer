"""Toga desktop UI over the in-process ``anonymizer`` core.

The core is imported directly (no daemon, no IPC) so the Natasha model loads
once inside this process. Batch work runs off the UI thread; per-file results
are delivered back to the event loop as they complete.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import json
import shutil
import subprocess
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

import toga

from anonymizer.api import Options
from anonymizer.batch import FileStatus, OutputPolicy, process_files  # noqa: F401
from anonymizer.convert import default_pdf2md_command
from anonymizer_ui import appkit_bridge, clipboard_ops, drag_drop_overlay
from anonymizer_ui.batch_controller import BatchRunController
from anonymizer_ui.main_window_layout import build_main_layout
from anonymizer_ui.menubar_controller import MenuBarController
from anonymizer_ui.pdf_backend_controller import PdfBackendController

_PENDING = "pending"

# Last-resort fallback for the project repo URL. Same value as
# ``[project.urls] Homepage`` and ``[tool.briefcase].url`` in pyproject.toml;
# kept here so the GitHub click always works even when neither the package
# metadata nor the bundle's Info.plist surfaces the URL (real bug observed
# in bundled .apps where Briefcase did not refresh Info.plist on rebuild).
_REPO_URL_FALLBACK = "https://github.com/zanybaka/pdf-md-anonymizer"

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


def _resolve_app_version() -> str:
    """Resolve the running app's version string, across dev and bundled .app.

    Order:
      1. ``importlib.metadata`` — works for ``pip install -e .`` / ``uv tool
         install`` (the dev install ships ``pdf-md-anonymizer-*.dist-info/``).
      2. NSBundle's ``CFBundleShortVersionString`` — the canonical version
         inside a Briefcase ``.app`` bundle, where the package is shipped as
         plain source files (no ``dist-info/``) and ``importlib.metadata``
         raises ``PackageNotFoundError``. Briefcase writes the value from
         ``pyproject.toml`` ``[tool.briefcase] version``.
    Returns empty string when neither source is available; callers treat that
    as "skip the version suffix" rather than crash.
    """
    with contextlib.suppress(Exception):
        v = importlib.metadata.version("pdf-md-anonymizer").strip()
        if v:
            return v
    with contextlib.suppress(appkit_bridge.AppKitError):
        v = appkit_bridge.main_bundle_short_version()
        if v:
            return v
    return ""


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

        prefs = _load_prefs()
        root = self._build_main_layout(prefs)
        self.main_window = toga.MainWindow(title=self._window_title())
        self.main_window.content = root
        self.main_window.on_close = self._on_window_close

        self._register_global_commands()
        self._apply_initial_window_prefs(prefs)
        self._install_macos_hooks()
        self._setup_pdf_controller()

        self._make_primary_button(self.run_button)
        self._setup_drag_drop()
        threading.Thread(target=self._warmup_ner, daemon=True).start()

    def _window_title(self) -> str:
        """Return the main-window title, including the running app version.

        Tries ``self.version`` (Toga/Briefcase) first, then a shared resolver
        that covers both the dev install (``importlib.metadata``) and the
        bundled ``.app`` (NSBundle ``CFBundleShortVersionString``). Falls
        back to the bare ``formal_name`` when no version is resolvable.
        """
        version = ""
        with contextlib.suppress(Exception):
            version = (getattr(self, "version", "") or "").strip()
        if not version:
            version = _resolve_app_version()
        if version:
            return f"{self.formal_name} {version}"
        return self.formal_name

    @staticmethod
    def _repository_url() -> str:
        """Resolve the project repository URL.

        Order:
          1. ``importlib.metadata`` PEP 621 ``[project.urls] Homepage`` (the
             dev install ships dist-info with this).
          2. Older ``Home-page`` metadata field.
          3. NSBundle ``ProjectHomepageURL`` from the bundle's ``Info.plist``
             — the canonical source inside a Briefcase ``.app``, where the
             package ships as plain source (no ``dist-info/``) and
             ``importlib.metadata`` raises ``PackageNotFoundError``. The key
             is declared under ``[tool.briefcase.app.X.macOS].info_plist``
             in pyproject.toml.
        Returns empty string when no source is available; callers treat that
        as "do nothing" so a packaging regression never crashes the UI.
        """
        try:
            md = importlib.metadata.metadata("pdf-md-anonymizer")
            for raw in md.get_all("Project-URL") or []:
                label, _, url = raw.partition(",")
                if label.strip().lower() == "homepage" and url.strip():
                    return url.strip()
            home_page = (md.get("Home-page") or "").strip()
            if home_page:
                return home_page
        except importlib.metadata.PackageNotFoundError:
            pass
        with contextlib.suppress(appkit_bridge.AppKitError):
            url = appkit_bridge.main_bundle_info_string("ProjectHomepageURL")
            if url:
                return url
        return _REPO_URL_FALLBACK

    async def _on_open_repository(self, widget) -> None:
        """Open the project repository in the user's default browser.

        Uses NSWorkspace inside the Briefcase ``.app`` (``webbrowser.open``
        has been observed to silently no-op there) with a stdlib fallback
        for non-macOS Toga backends. Async because every other on_press
        handler in this app is async; Toga's button dispatch would not
        await a sync handler. No-op when the URL is empty (partial install).
        """
        url = self._repository_url()
        if not url:
            self._log("GitHub: no repository URL in package metadata")
            return
        try:
            appkit_bridge.open_url(url)
        except appkit_bridge.AppKitError as exc:
            self._log(f"GitHub: NSWorkspace failed ({exc}); falling back to webbrowser")
            webbrowser.open(url)

    def _build_main_layout(self, prefs: dict) -> toga.Box:
        """Construct the root layout and bind widget references on ``self``."""
        root, widgets = build_main_layout(self, prefs)
        self.output_label = widgets.output_label
        self.map_switch = widgets.map_switch
        self.menubar_switch = widgets.menubar_switch
        self.table = widgets.table
        self.progress = widgets.progress
        self.status_label = widgets.status_label
        self.run_button = widgets.run_button
        self.cancel_button = widgets.cancel_button
        self.reveal_button = widgets.reveal_button
        self.copy_button = widgets.copy_button
        self.result_view = widgets.result_view
        self.pdf_version_label = widgets.pdf_version_label
        self.pdf_action_button = widgets.pdf_action_button
        self.github_button = widgets.github_button
        self.add_files_button = widgets.add_files_button
        return root

    def _register_global_commands(self) -> None:
        self.commands.add(
            toga.Command(
                self._on_paste_files,
                text="Paste",
                shortcut=toga.Key.MOD_1 + "v",
                group=toga.Group.EDIT,
            ),
            toga.Command(
                self._on_open_repository,
                text="View on GitHub",
                group=toga.Group.HELP,
            ),
        )

    def _apply_initial_window_prefs(self, prefs: dict) -> None:
        # Suppress the main window when launched at login (launch_at_login
        # pref is True).  SMAppService on macOS 13+ cannot pass CLI args, so
        # we cannot rely on --background being in sys.argv.  Checking the pref
        # is the only reliable mechanism on both macOS versions.
        if not prefs.get("launch_at_login", False):
            self.main_window.show()

            # Put initial keyboard focus on "Add files…" — the most common
            # first action. Toga's ``focus()`` is a hint the AppKit backend
            # often ignores when the window's NSWindow already chose its own
            # initial first responder (header button, in our layout). Force
            # it via NSWindow.makeFirstResponder_; deferred a bit so the
            # call lands after the window is fully on screen.
            def _set_initial_focus() -> None:
                with contextlib.suppress(appkit_bridge.AppKitError):
                    appkit_bridge.make_first_responder(self.add_files_button)

            with contextlib.suppress(Exception):
                self.loop.call_later(0.1, _set_initial_focus)

        if prefs.get("stay_in_menubar", False):
            self._menubar.create_status_item()
            # Toga builds NSMenu after startup() returns; defer checkmark sync.
            with contextlib.suppress(Exception):
                self.loop.call_soon(self._menubar._sync_launch_at_login_checkmark)

        # Apply Stay-lock if Launch at Login is enabled (keeps Stay forced ON
        # and greyed out while the login item is registered).
        if prefs.get("launch_at_login", False):
            self._menubar._apply_stay_lock(True)
            # Window was suppressed; switch to Accessory policy so the Dock
            # icon is also hidden (same effect as closing the window normally).
            try:
                appkit_bridge.set_dock_visible(False)
            except appkit_bridge.AppKitError as exc:
                self._log(str(exc))

    def _install_macos_hooks(self) -> None:
        # Show the main window when the user re-launches the app while it's
        # already running in the menu bar (Finder double-click / Spotlight).
        try:
            appkit_bridge.install_reopen_handler(self._menubar.show_main_window)
        except appkit_bridge.AppKitError as exc:
            self._log(f"reopen handler not installed: {exc}")

    def _setup_pdf_controller(self) -> None:
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
            # Sync the native checkmark after menu is fully built.
            self._menubar._sync_launch_at_login_checkmark()
        else:
            self._menubar.remove_status_item()

    def _on_window_close(self, window) -> bool:
        if self.menubar_switch.value:
            self._hide_to_menubar()
            return False  # prevent close
        return True  # allow close → app quits

    def _log(self, msg: str) -> None:
        """Append a line to the result view (UI-thread safe, best-effort)."""
        with contextlib.suppress(Exception):
            self._prepend_to_result(f"[app] {msg}\n")

    def _hide_to_menubar(self) -> None:
        self._menubar.hide_window_to_menubar()

    def _show_main_window(self, *args, **kwargs) -> None:
        self._menubar.show_main_window()

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

    def _pick_file_and_restore_policy(self, title: str) -> Path | None:
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

        await self._run_anonymize(
            source=lambda: read_input(path),
            busy_body=path.name,
            done_body=path.name,
        )

    async def _anon_clipboard_to_clipboard(self) -> None:
        await self._run_anonymize(
            source=lambda: clipboard_ops.read_clipboard() or "",
            busy_body="Clipboard text",
            done_body="Clipboard text anonymized",
        )

    async def _anon_selection_to_clipboard(self) -> None:
        """Copy current selection (Cmd+C), then anonymize the clipboard.

        Wired to the global ⌃⌥⌘C hotkey: works in any focused app.
        """
        before = clipboard_ops.read_clipboard() or ""
        try:
            appkit_bridge.send_cmd_c()
        except appkit_bridge.AppKitError as exc:
            clipboard_ops.send_notification("Cmd+C failed", str(exc)[:120])
            return
        # Give the OS a moment to update the pasteboard from the foreign app.
        await asyncio.sleep(0.15)
        after = clipboard_ops.read_clipboard() or ""
        if after == before:
            clipboard_ops.send_notification(
                "No text selected", "Select text first, then press ⌃⌥⌘C"
            )
            return
        await self._run_anonymize(
            source=lambda: after,
            busy_body="Selected text",
            done_body="Selection anonymized — paste with ⌘V",
        )

    async def _run_anonymize(
        self,
        *,
        source: Callable[[], str],
        busy_body: str,
        done_body: str,
    ) -> None:
        await clipboard_ops.run_anonymize_to_clipboard(
            source=source,
            loop=self.loop,
            on_busy_begin=self._begin_busy,
            on_busy_end=self._end_busy,
            busy_title="Anonymizing…",
            busy_body=busy_body,
            done_title="Anonymized to clipboard",
            done_body=done_body,
        )

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
        folder = await self.main_window.dialog(toga.SelectFolderDialog("Select output folder"))
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
                on_error=self._log,
            )
        except appkit_bridge.AppKitError as exc:
            self._log(f"drag-drop setup failed: {exc}")

    @staticmethod
    def _make_primary_button(button: toga.Button) -> None:
        with contextlib.suppress(AttributeError):
            button._impl.native.keyEquivalent = "\r"

    def _warmup_ner(self) -> None:
        self.loop.call_soon_threadsafe(self._on_warmup_start)

        def on_step(msg: str) -> None:
            self.loop.call_soon_threadsafe(self._on_warmup_step, msg)

        try:
            from anonymizer.detect.ner import warmup  # noqa: PLC0415

            warmup(on_step=on_step)
        except Exception:  # noqa: S110
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
        if self._running:
            return
        if not self._inputs:
            self.status_label.text = "No files selected"
            return
        if any(p.suffix.lower() == ".pdf" for p in self._inputs):
            await self._ensure_pdf_backend_ready()
        self._begin_run()

    async def _ensure_pdf_backend_ready(self) -> None:
        if not _pdf2md_available():
            await self._handle_missing_pdf_backend()
        if not self._setuptools_ready.is_set():
            self.status_label.text = "Finishing backend setup…"
            await asyncio.get_event_loop().run_in_executor(None, self._setuptools_ready.wait)

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
            await self.main_window.dialog(
                toga.InfoDialog(
                    "Python 3 required",
                    "Installing or updating the PDF backend requires Python 3 "
                    "outside the app bundle.\n\n"
                    "Install it with Homebrew:\n"
                    "    brew install python3\n\n"
                    "Or download from https://python.org",
                )
            )
            return
        installed = pdf_backend.is_installed()
        title = "Update PDF backend" if installed else "Install PDF backend"
        body = "This will download pdf-to-markdown from git (needs network).\n\n" + (
            "Update to the latest revision?" if installed else "Install now?"
        )
        if not await self.main_window.dialog(toga.QuestionDialog(title, body)):
            return
        assert self._pdf_ctrl is not None  # noqa: S101
        await self._pdf_ctrl.run_action(upgrade=installed)

    # --- helpers --------------------------------------------------------

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
            clipboard_ops.write_clipboard(out.read_text(encoding="utf-8"))

    def _refresh_table(self) -> None:
        def _status_label(p: Path) -> str:
            s = self._status.get(p, _PENDING)
            return "📂 done" if s == FileStatus.DONE else s

        self.table.data = [(p.name, _status_label(p)) for p in self._inputs]


def main() -> AnonymizerApp:
    version = _resolve_app_version()
    return AnonymizerApp("PDF-MD Anonymizer", "ru.ati.anonymizer", version=version or None)

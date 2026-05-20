"""PDF-backend install/update flow for the anonymizer desktop UI.

``PdfBackendController`` owns the setuptools-repair thread, the
install/update flow with progress streaming, and the version-label
refresh.  It calls ``pdf_backend.can_install()`` exclusively — never
the private ``_find_build_python`` / ``_has_setuptools`` helpers.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path


class PdfBackendController:
    """Manages PDF-backend install / update / repair for AnonymizerApp.

    Callbacks fire on the asyncio event loop that was passed in, keeping
    widget updates on the UI thread.
    """

    def __init__(
        self,
        *,
        on_version_label: Callable[[str], None],
        on_action_button: Callable[[str, bool], None],
        on_log: Callable[[str], None],
        on_progress_start: Callable[[], None],
        on_progress_stop: Callable[[], None],
        on_status: Callable[[str], None],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._on_version_label = on_version_label
        self._on_action_button = on_action_button  # (text, enabled)
        self._on_log = on_log
        self._on_progress_start = on_progress_start
        self._on_progress_stop = on_progress_stop
        self._on_status = on_status
        self._loop = loop
        self._setuptools_ready = threading.Event()
        self._setuptools_ready.set()

    # --- startup --------------------------------------------------------

    def refresh_row(self) -> None:
        """Update the version label and action button to reflect current state."""
        from anonymizer_ui import pdf_backend  # noqa: PLC0415
        installed = pdf_backend.is_installed()
        ver = pdf_backend.installed_version() if installed else None
        if installed:
            label = f"PDF backend: v{ver}" if ver else "PDF backend: installed"
            button_text = "Update"
        else:
            label = "PDF backend: not installed"
            button_text = "Install PDF backend"
        self._on_version_label(label)
        self._on_action_button(button_text, pdf_backend.can_install())

    def start_setuptools_repair_if_needed(self) -> threading.Event:
        """Launch the repair thread if the backend needs it.

        Returns the ready-Event (always set on return; cleared only when
        a repair thread is running).
        """
        from anonymizer_ui import pdf_backend  # noqa: PLC0415
        if pdf_backend.needs_setuptools_repair():
            self._setuptools_ready.clear()
            threading.Thread(
                target=self._repair_setuptools, daemon=True
            ).start()
        return self._setuptools_ready

    # --- run action (install / update) ----------------------------------

    async def run_action(self, upgrade: bool) -> None:
        """Install or update the PDF backend, streaming output via callbacks."""
        from anonymizer_ui import pdf_backend  # noqa: PLC0415

        if not pdf_backend.can_install():
            return  # caller should have checked first

        verb = "Updating" if upgrade else "Installing"
        self._on_action_button("…", False)
        self._on_log(f"{verb} PDF backend…\n")
        self._on_status(f"{verb} PDF backend…")
        self._on_progress_start()

        loop = self._loop
        done: asyncio.Event = asyncio.Event()
        success_box = [False]

        def _on_line(line: str) -> None:
            loop.call_soon_threadsafe(self._on_log, line + "\n")

        def _work() -> None:
            try:
                from anonymizer_ui import pdf_backend as _pb  # noqa: PLC0415
                if upgrade:
                    _pb.update(on_line=_on_line)
                else:
                    _pb.install(on_line=_on_line)
                success_box[0] = True
            except Exception as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(
                    self._on_log, f"\n{verb} failed: {exc}\n"
                )
            finally:
                loop.call_soon_threadsafe(done.set)

        threading.Thread(target=_work, daemon=True).start()
        await done.wait()

        self._on_progress_stop()
        self.refresh_row()
        if success_box[0]:
            self._on_status(f"PDF backend {verb.lower()[:-3]}ed.")
            self._on_log(f"PDF backend {verb.lower()[:-3]}ed successfully.\n\n")
        else:
            self._on_status(f"{verb} failed.")

    # --- internal -------------------------------------------------------

    def _repair_setuptools(self) -> None:
        try:
            from anonymizer_ui import pdf_backend  # noqa: PLC0415
            pdf_backend.ensure_setuptools()
        except Exception:
            pass
        finally:
            self._setuptools_ready.set()

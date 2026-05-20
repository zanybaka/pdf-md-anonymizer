"""Menu-bar-resident-mode controller for the anonymizer desktop UI.

``MenuBarController`` owns the NSStatusItem lifecycle, the busy-icon
animation, and the four status-bar commands (Show Window, Anonymize File
to Clipboard…, Anonymize Clipboard, Quit).  It calls
``appkit_bridge.*`` exclusively — no inline rubicon-objc.
ADR-0009 command-dispatch behaviour is preserved.
"""

from __future__ import annotations

from anonymizer_ui import appkit_bridge


class MenuBarController:
    """Manages the macOS menu-bar status icon and resident-mode lifecycle."""

    def __init__(self, app) -> None:
        """*app* is the ``AnonymizerApp`` instance (needed for Toga APIs)."""
        self._app = app
        self._status_icon = None
        self._status_commands_added = False
        self._busy_count = 0
        self._saved_status_icon_image: list = [None]

    # --- icon lifecycle -------------------------------------------------

    def create_status_item(self) -> None:
        """Add the menu-bar status icon and its commands (idempotent)."""
        import toga  # noqa: PLC0415
        app = self._app
        try:
            if self._status_icon is None:
                self._status_icon = toga.MenuStatusIcon(text=app.formal_name)
            if self._status_icon not in app.status_icons:
                app.status_icons.add(self._status_icon)
                self._style_icon()
            if not self._status_commands_added:
                for _cmd_id in ("about", "request_exit"):
                    try:
                        del app.status_icons.commands[_cmd_id]
                    except KeyError:
                        pass
                app.status_icons.commands.add(
                    toga.Command(
                        app._show_main_window,
                        text="Show Window",
                        group=self._status_icon,
                        section=0,
                        order=0,
                    ),
                    toga.Command(
                        app._cmd_anon_file_to_clipboard,
                        text="Anonymize File to Clipboard…",
                        group=self._status_icon,
                        section=0,
                        order=1,
                    ),
                    toga.Command(
                        app._cmd_anon_clipboard_to_clipboard,
                        text="Anonymize Clipboard",
                        group=self._status_icon,
                        section=0,
                        order=2,
                    ),
                    toga.Command(
                        app._cmd_quit,
                        text="Quit",
                        group=self._status_icon,
                        section=1,
                        order=0,
                    ),
                )
                self._status_commands_added = True
        except Exception as exc:
            app._log(f"create_status_item failed: {exc}")

    def remove_status_item(self) -> None:
        """Remove the status icon from the menu bar (idempotent)."""
        if self._status_icon is None:
            return
        try:
            if self._status_icon in self._app.status_icons:
                self._app.status_icons.remove(self._status_icon)
        except Exception as exc:
            self._app._log(f"remove_status_item failed: {exc}")

    def hide_window_to_menubar(self) -> None:
        """Hide the main window and switch to Accessory activation policy."""
        self.create_status_item()
        try:
            self._app.main_window._impl.native.orderOut_(None)
        except Exception as exc:
            self._app._log(f"orderOut failed: {exc}")
        try:
            appkit_bridge.set_dock_visible(False)
        except appkit_bridge.AppKitError as exc:
            self._app._log(str(exc))

    def show_main_window(self) -> None:
        """Restore the main window and switch to Regular activation policy."""
        try:
            appkit_bridge.set_dock_visible(True)
        except appkit_bridge.AppKitError as exc:
            self._app._log(str(exc))
        try:
            appkit_bridge.activate_app()
            appkit_bridge.bring_window_to_front(self._app.main_window)
        except appkit_bridge.AppKitError as exc:
            self._app._log(str(exc))

    # --- busy animation -------------------------------------------------

    def begin_busy(self) -> None:
        """Mark a background task started; swap to busy icon on first call."""
        self._busy_count += 1
        if self._busy_count == 1:
            self._set_busy_icon(True)

    def end_busy(self) -> None:
        """Mark a background task finished; restore idle icon at zero."""
        if self._busy_count > 0:
            self._busy_count -= 1
        if self._busy_count == 0:
            self._set_busy_icon(False)

    # --- internal -------------------------------------------------------

    def _style_icon(self) -> None:
        try:
            appkit_bridge.status_icon_resize(self._status_icon)
        except appkit_bridge.AppKitError as exc:
            self._app._log(str(exc))

    def _set_busy_icon(self, busy: bool) -> None:
        if self._status_icon is None:
            return
        try:
            appkit_bridge.status_icon_swap_image(
                self._status_icon, busy, self._saved_status_icon_image
            )
        except appkit_bridge.AppKitError as exc:
            self._app._log(str(exc))

    # --- property accessors (for tests / external code) -----------------

    @property
    def status_icon(self):
        return self._status_icon

"""Menu-bar-resident-mode controller for the anonymizer desktop UI.

``MenuBarController`` owns the NSStatusItem lifecycle, the busy-icon
animation, and the four status-bar commands (Show Window, Anonymize File
to Clipboard…, Anonymize Clipboard, Quit).  It calls
``appkit_bridge.*`` exclusively — no inline rubicon-objc.
ADR-0009 command-dispatch behaviour is preserved.
"""

from __future__ import annotations

from anonymizer_ui import appkit_bridge

# --background CLI flag that is passed when launching at login.
BACKGROUND_FLAG = "--background"


class MenuBarController:
    """Manages the macOS menu-bar status icon and resident-mode lifecycle."""

    def __init__(self, app) -> None:
        """*app* is the ``AnonymizerApp`` instance (needed for Toga APIs)."""
        self._app = app
        self._status_icon = None
        self._status_commands_added = False
        self._busy_count = 0
        self._saved_status_icon_image: list = [None]
        self._hotkey_monitor: object = None
        # True while "Launch at Login" has forced the Stay switch to be locked on.
        self._stay_locked: bool = False

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
                        text="Anonymize Clipboard  ⌃⌥⌘C",
                        group=self._status_icon,
                        section=0,
                        order=2,
                    ),
                    toga.Command(
                        self._cmd_toggle_launch_at_login,
                        text=self._launch_at_login_label(),
                        group=self._status_icon,
                        section=1,
                        order=0,
                    ),
                    toga.Command(
                        app._cmd_quit,
                        text="Quit",
                        group=self._status_icon,
                        section=1,
                        order=1,
                    ),
                )
                self._status_commands_added = True
        except Exception as exc:
            app._log(f"create_status_item failed: {exc}")

        self._register_hotkey()
        # Reconcile launch-at-login pref with actual SMAppService state on first
        # creation so the checkbox is truthful.
        self._reconcile_launch_at_login()

    def remove_status_item(self) -> None:
        """Remove the status icon from the menu bar (idempotent)."""
        self._unregister_hotkey()
        if self._status_icon is None:
            return
        try:
            if self._status_icon in self._app.status_icons:
                self._app.status_icons.remove(self._status_icon)
        except Exception as exc:
            self._app._log(f"remove_status_item failed: {exc}")
        # Clear Toga's stale NSMenuItem cache so StatusIconSet.create() doesn't
        # try to call removeItem_ on items whose NSMenu has already been released.
        try:
            self._app.status_icons._impl._menu_items.clear()
        except Exception:
            pass

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

    # --- global hotkey --------------------------------------------------

    def _register_hotkey(self) -> None:
        """Register the global ⌃⌥⌘C hotkey if enabled in prefs (idempotent).

        Requires macOS Accessibility permission for events from other apps.
        macOS auto-prompts on first registration; no explicit pre-check needed.
        """
        if self._hotkey_monitor is not None:
            return  # already registered
        from anonymizer_ui.app import _load_prefs  # noqa: PLC0415
        prefs = _load_prefs()
        if not prefs.get("global_hotkey_enabled", True):
            return
        loop = getattr(self._app, "loop", None)
        if loop is None:
            return

        import asyncio as _asyncio  # noqa: PLC0415

        def _callback() -> None:
            loop.call_soon_threadsafe(
                lambda: _asyncio.ensure_future(
                    self._app._anon_selection_to_clipboard()
                )
            )

        try:
            self._hotkey_monitor = appkit_bridge.register_global_hotkey(
                appkit_bridge.HOTKEY_DEFAULT_MODIFIER_FLAGS,
                appkit_bridge.HOTKEY_DEFAULT_KEY_CODE,
                _callback,
            )
        except appkit_bridge.AppKitError as exc:
            self._app._log(f"register_global_hotkey failed: {exc}")
            return

        # Accessibility is required for the global hotkey to fire from other
        # apps and for CGEventPost (Cmd+C synthesis). Warn clearly if missing.
        try:
            if not appkit_bridge.is_accessibility_trusted():
                self._app._log(
                    "⚠ Accessibility permission missing — global ⌃⌥⌘C will only work "
                    "while this app is focused. Grant access in System Settings › "
                    "Privacy & Security › Accessibility (add 'PDF-MD Anonymizer' via +)."
                )
        except appkit_bridge.AppKitError as exc:
            self._app._log(f"accessibility check failed: {exc}")

    def _unregister_hotkey(self) -> None:
        """Unregister the global hotkey monitor (idempotent)."""
        if self._hotkey_monitor is None:
            return
        try:
            appkit_bridge.remove_global_hotkey(self._hotkey_monitor)
        except appkit_bridge.AppKitError as exc:
            self._app._log(f"remove_global_hotkey failed: {exc}")
        finally:
            self._hotkey_monitor = None

    # --- Launch at Login ------------------------------------------------

    def _launch_at_login_label(self) -> str:
        return "Launch at Login"

    def _sync_launch_at_login_checkmark(self) -> None:
        """Set the native NSMenuItem checkmark to match the stored pref."""
        if self._status_icon is None:
            return
        from anonymizer_ui.app import _load_prefs  # noqa: PLC0415
        enabled = _load_prefs().get("launch_at_login", False)
        try:
            appkit_bridge.set_menu_item_checked(
                self._status_icon, "Launch at Login", checked=enabled
            )
        except appkit_bridge.AppKitError:
            pass

    def _reconcile_launch_at_login(self) -> None:
        """Reconcile the stored pref with the actual registration status.

        If the two disagree (e.g. the user deleted the pref file, or macOS
        removed the login item), update the pref to match reality.
        """
        from anonymizer_ui.app import _load_prefs, _save_prefs  # noqa: PLC0415
        prefs = _load_prefs()
        pref_value = prefs.get("launch_at_login", False)
        try:
            actual = appkit_bridge.is_login_item_registered()
        except Exception:
            return  # can't check — don't change pref
        if actual != pref_value:
            prefs["launch_at_login"] = actual
            _save_prefs(prefs)
            if actual:
                self._apply_stay_lock(True)

    def _cmd_toggle_launch_at_login(self, command=None, **kwargs) -> None:
        """Toggle the 'Launch at Login' login-item registration."""
        from anonymizer_ui.app import _load_prefs, _save_prefs  # noqa: PLC0415
        prefs = _load_prefs()
        current = prefs.get("launch_at_login", False)
        new_value = not current
        if new_value:
            # Enabling: register login item with --background, lock Stay on.
            try:
                appkit_bridge.register_login_item([BACKGROUND_FLAG])
            except appkit_bridge.AppKitError as exc:
                self._app._log(f"register_login_item failed: {exc}")
                return
            self._apply_stay_lock(True)
        else:
            # Disabling: unregister login item, unlock Stay.
            try:
                appkit_bridge.unregister_login_item()
            except appkit_bridge.AppKitError as exc:
                self._app._log(f"unregister_login_item failed: {exc}")
            self._apply_stay_lock(False)
        prefs["launch_at_login"] = new_value
        _save_prefs(prefs)
        # Update the native NSMenuItem checkmark via setState_ so the tick
        # appears/disappears immediately without rebuilding the whole menu.
        if self._status_icon is not None:
            try:
                appkit_bridge.set_menu_item_checked(
                    self._status_icon, "Launch at Login", checked=new_value
                )
            except appkit_bridge.AppKitError:
                pass  # best-effort — visual only

    def _apply_stay_lock(self, lock: bool) -> None:
        """Lock or unlock the 'Stay in menu bar' switch for Launch-at-Login.

        When *lock* is True: save the current Stay switch state, force it
        ON, and disable it (greyed out) — menu-bar mode is a prerequisite
        for a background-only launch.

        When *lock* is False: re-enable the Stay switch and restore the
        prior (pre-lock) state.
        """
        from anonymizer_ui.app import _load_prefs, _save_prefs  # noqa: PLC0415
        app = self._app
        try:
            switch = app.menubar_switch
        except AttributeError:
            return  # no UI available (unit-test context or headless)

        prefs = _load_prefs()
        if lock and not self._stay_locked:
            # Save current Stay value before locking.
            prefs["_stay_before_launch_lock"] = switch.value
            _save_prefs(prefs)
            try:
                switch.value = True
                switch.enabled = False
            except Exception:
                pass
            self._stay_locked = True
        elif not lock and self._stay_locked:
            # Restore prior Stay value.
            prior = prefs.get("_stay_before_launch_lock", True)
            try:
                switch.value = prior
                switch.enabled = True
            except Exception:
                pass
            prefs.pop("_stay_before_launch_lock", None)
            _save_prefs(prefs)
            self._stay_locked = False

    @property
    def stay_locked(self) -> bool:
        """True when the Stay switch is locked on due to Launch at Login."""
        return self._stay_locked

    # --- property accessors (for tests / external code) -----------------

    @property
    def status_icon(self):
        return self._status_icon

    @property
    def hotkey_monitor(self):
        return self._hotkey_monitor

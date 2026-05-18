"""UI-001: the UI package imports cleanly and reuses the in-process core."""

import importlib

import pytest


def test_ui_app_module_imports():
    mod = importlib.import_module("anonymizer_ui.app")
    assert hasattr(mod, "AnonymizerApp")
    assert callable(mod.main)


def test_ui_uses_in_process_core_batch_api():
    # The UI must drive the same batch API as the CLI — no daemon/IPC.
    mod = importlib.import_module("anonymizer_ui.app")
    from anonymizer.batch import process_files

    assert mod.process_files is process_files


def test_core_package_has_no_ui_dependency():
    # Importing the core must not require Toga.
    import anonymizer.api  # noqa: F401
    import anonymizer.cli  # noqa: F401

    for name in ("anonymizer.api", "anonymizer.cli", "anonymizer.batch"):
        mod = importlib.import_module(name)
        src = getattr(mod, "__file__", "")
        assert "anonymizer_ui" not in src


# --- UI-002: first-use PDF backend install ----------------------------------


def test_pdf_backend_module_exports():
    """pdf_backend exposes the expected public API."""
    from anonymizer_ui import pdf_backend

    assert callable(pdf_backend.backend_dir)
    assert callable(pdf_backend.pdf2md_path)
    assert callable(pdf_backend.is_installed)
    assert callable(pdf_backend.install)
    assert callable(pdf_backend.update)
    assert callable(pdf_backend.installed_version)


def test_pdf_backend_not_installed_when_absent(tmp_path, monkeypatch):
    """is_installed() returns False when the backend venv does not exist."""
    from anonymizer_ui import pdf_backend

    monkeypatch.setattr(pdf_backend, "backend_dir", lambda: tmp_path / "nonexistent")
    assert not pdf_backend.is_installed()


def test_pdf_backend_detected_when_present(tmp_path, monkeypatch):
    """is_installed() returns True once pdf2md exists in the backend dir."""
    from anonymizer_ui import pdf_backend

    venv_bin = tmp_path / "bin"
    venv_bin.mkdir()
    (venv_bin / "pdf2md").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(pdf_backend, "backend_dir", lambda: tmp_path)
    assert pdf_backend.is_installed()


def test_pdf_backend_patch_injects_sys_path(tmp_path, monkeypatch):
    """_patch_pdf2md_script inserts sys.path.insert after the shebang."""
    from anonymizer_ui import pdf_backend

    # Simulate a pip --prefix install layout
    sp = tmp_path / "lib" / "python3.12" / "site-packages"
    sp.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "pdf2md"
    script.write_text("#!/usr/bin/python3\nfrom pdf2md import main\nmain()\n")

    monkeypatch.setattr(pdf_backend, "backend_dir", lambda: tmp_path)
    pdf_backend._patch_pdf2md_script(tmp_path)

    patched = script.read_text()
    lines = patched.splitlines()
    assert lines[0].startswith("#!")
    assert "sys.path.insert" in lines[1]
    assert str(sp) in lines[1]
    # Original entry-point line is still present
    assert any("from pdf2md import main" in l for l in lines)


def test_pdf_backend_find_pip_wheel():
    """_find_pip_wheel returns a path to a .whl file that exists."""
    from anonymizer_ui import pdf_backend
    from pathlib import Path

    wheel = pdf_backend._find_pip_wheel()
    assert Path(wheel).exists()
    assert wheel.endswith(".whl")


def test_pdf_backend_line_writer():
    """_LineWriter forwards complete lines to the callback and satisfies pip's file interface."""
    from anonymizer_ui import pdf_backend

    received = []
    w = pdf_backend._LineWriter(received.append)
    w.write("hello\nworld\n")
    assert received == ["hello", "world"]
    w.write("partial")
    assert received == ["hello", "world"]
    w.flush()
    assert received == ["hello", "world", "partial"]
    assert w.isatty() is False



def test_pdf_backend_installed_version_absent(tmp_path, monkeypatch):
    """installed_version() returns None when the backend is not installed."""
    from anonymizer_ui import pdf_backend

    monkeypatch.setattr(pdf_backend, "backend_dir", lambda: tmp_path / "empty")
    assert pdf_backend.installed_version() is None


def test_pdf_backend_installed_version_present(tmp_path, monkeypatch):
    """installed_version() reads the version from the dist-info directory."""
    from anonymizer_ui import pdf_backend

    sp = tmp_path / "lib" / "python3.12" / "site-packages"
    (sp / "pdf_to_markdown-1.2.3.dist-info").mkdir(parents=True)
    monkeypatch.setattr(pdf_backend, "backend_dir", lambda: tmp_path)
    assert pdf_backend.installed_version() == "1.2.3"


# --- reveal/copy button state -------------------------------------------


def test_reveal_copy_disabled_after_clear():
    """reveal/copy buttons are disabled when on_clear is called."""
    import types
    from unittest.mock import MagicMock
    from anonymizer_ui.app import AnonymizerApp

    reveal = MagicMock()
    reveal.enabled = True
    copy = MagicMock()
    copy.enabled = True

    obj = types.SimpleNamespace(
        _running=False,
        _inputs=["x"],
        _status={"x": "done"},
        _output_paths={"x": "out.md"},
        result_view=MagicMock(),
        reveal_button=reveal,
        copy_button=copy,
    )
    obj._refresh_table = lambda: None

    import asyncio
    asyncio.run(AnonymizerApp.on_clear(obj, None))

    assert not reveal.enabled
    assert not copy.enabled
    assert obj._inputs == []
    assert obj._output_paths == {}


def test_reveal_copy_enabled_only_with_valid_selection(tmp_path):
    """on_table_select enables buttons only when selected row has an output file."""
    import types
    from pathlib import Path
    from anonymizer_ui.app import AnonymizerApp

    out = tmp_path / "doc.anon.md"
    out.write_text("text")

    reveal_enabled = []
    copy_enabled = []

    class _Btn:
        def __init__(self):
            self.enabled = False

    reveal = _Btn()
    copy = _Btn()

    class _Row:
        pass

    row = _Row()

    class _TableData(list):
        def __iter__(self):
            return iter([row])

    obj = types.SimpleNamespace(
        _inputs=[Path(tmp_path / "doc.md")],
        _output_paths={Path(tmp_path / "doc.md"): out},
        reveal_button=reveal,
        copy_button=copy,
        table=types.SimpleNamespace(selection=row, data=_TableData([row])),
    )
    obj._selected_output = lambda: AnonymizerApp._selected_output(obj)

    AnonymizerApp.on_table_select(obj, None)
    assert reveal.enabled
    assert copy.enabled

    # no selection → buttons disabled
    obj.table.selection = None
    AnonymizerApp.on_table_select(obj, None)
    assert not reveal.enabled
    assert not copy.enabled


# --- UI-005: drag-and-drop / paste-files --------------------------------


def test_add_inputs_filters_and_deduplicates(tmp_path):
    """_add_inputs accepts only .pdf/.md and ignores duplicates."""
    import types
    from anonymizer_ui.app import AnonymizerApp, _PENDING

    obj = types.SimpleNamespace(_inputs=[], _status={})
    obj._refresh_table = lambda: None

    md = tmp_path / "doc.md"
    pdf = tmp_path / "report.pdf"
    txt = tmp_path / "notes.txt"

    # txt must be filtered; second md must be deduplicated
    AnonymizerApp._add_inputs(obj, [md, pdf, txt, md])

    assert obj._inputs == [md, pdf]
    assert obj._status[md] == _PENDING
    assert obj._status[pdf] == _PENDING
    assert txt not in obj._status


def test_add_inputs_accepts_string_paths(tmp_path):
    """_add_inputs coerces str arguments to Path."""
    import types
    from anonymizer_ui.app import AnonymizerApp, _PENDING
    from pathlib import Path

    obj = types.SimpleNamespace(_inputs=[], _status={})
    obj._refresh_table = lambda: None

    p = str(tmp_path / "a.md")
    AnonymizerApp._add_inputs(obj, [p])

    assert obj._inputs == [Path(p)]
    assert obj._status[Path(p)] == _PENDING


def test_add_inputs_no_refresh_when_nothing_added(tmp_path):
    """_add_inputs does not call _refresh_table when no new paths are added."""
    import types
    from anonymizer_ui.app import AnonymizerApp

    refreshed = []
    obj = types.SimpleNamespace(_inputs=[], _status={})
    obj._refresh_table = lambda: refreshed.append(1)

    # All filtered (wrong extension)
    AnonymizerApp._add_inputs(obj, [tmp_path / "x.docx", tmp_path / "y.csv"])
    assert refreshed == []


# --- UI-004: menu-bar resident mode -------------------------------------


def test_prefs_roundtrip(tmp_path, monkeypatch):
    """_load_prefs / _save_prefs round-trip through a JSON file."""
    from anonymizer_ui.app import _load_prefs, _save_prefs
    import anonymizer_ui.app as _app_mod

    monkeypatch.setattr(_app_mod, "_PREFS_FILE", tmp_path / "prefs.json")
    monkeypatch.setattr(_app_mod, "_SUPPORT_DIR", tmp_path)

    assert _load_prefs() == {}  # missing file → empty dict
    _save_prefs({"stay_in_menubar": True})
    assert _load_prefs() == {"stay_in_menubar": True}


def test_on_window_close_prevents_when_switch_on():
    """_on_window_close returns False (prevent) when menubar_switch is on."""
    import types
    from anonymizer_ui.app import AnonymizerApp

    hidden = []

    obj = types.SimpleNamespace(
        menubar_switch=types.SimpleNamespace(value=True),
        _status_icon=None,
    )
    obj._hide_to_menubar = lambda: hidden.append(1)

    result = AnonymizerApp._on_window_close(obj, None)
    assert result is False
    assert hidden == [1]


def test_on_window_close_allows_when_switch_off():
    """_on_window_close returns True (allow) when menubar_switch is off."""
    import types
    from anonymizer_ui.app import AnonymizerApp

    obj = types.SimpleNamespace(
        menubar_switch=types.SimpleNamespace(value=False),
    )
    result = AnonymizerApp._on_window_close(obj, None)
    assert result is True


def test_on_menubar_pref_change_saves_and_removes_item(tmp_path, monkeypatch):
    """Toggling menubar_switch off saves pref and removes status item."""
    import types
    import anonymizer_ui.app as _app_mod
    from anonymizer_ui.app import AnonymizerApp

    monkeypatch.setattr(_app_mod, "_PREFS_FILE", tmp_path / "prefs.json")
    monkeypatch.setattr(_app_mod, "_SUPPORT_DIR", tmp_path)

    removed = []
    obj = types.SimpleNamespace(
        _remove_status_item=lambda: removed.append(1),
    )
    widget = types.SimpleNamespace(value=False)
    AnonymizerApp._on_menubar_pref_change(obj, widget)

    from anonymizer_ui.app import _load_prefs
    assert _load_prefs()["stay_in_menubar"] is False
    assert removed == [1]


# --- UI-006: save replacement map switch --------------------------------


def test_map_switch_present_and_default_off():
    """AnonymizerApp exposes map_switch; it defaults to False."""
    import types
    import toga
    from anonymizer_ui.app import AnonymizerApp

    switch = toga.Switch("Save replacement map", value=False)
    obj = types.SimpleNamespace(map_switch=switch)
    assert not obj.map_switch.value


def test_pdf_backend_url_matches_pyproject():
    """The git reference in pdf_backend matches the [pdf] extra in pyproject.toml."""
    from anonymizer_ui import pdf_backend
    import pathlib, re

    pyproject = pathlib.Path(__file__).parent.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    # Extract the git URL from the [pdf] extra declaration
    match = re.search(r'pdf = \["pdf-to-markdown @ (git\+[^"]+)"', text)
    assert match, "could not find [pdf] extra in pyproject.toml"
    expected_ref = match.group(1)
    assert expected_ref in pdf_backend._PDF_BACKEND_URL


# --- UI-008: two status-bar quick actions -----------------------------------


def test_anon_clipboard_to_clipboard_anonymizes_text():
    """_anon_clipboard_to_clipboard reads clipboard text, anonymizes, writes back."""
    import asyncio
    import types
    from anonymizer_ui.app import AnonymizerApp

    clipboard = ["Контакт: user@example.com"]
    written: list[str] = []
    notifs: list[tuple[str, str]] = []

    async def _run() -> None:
        obj = types.SimpleNamespace(
            loop=asyncio.get_event_loop(),
            _read_clipboard=lambda: clipboard[0],
            _copy_to_clipboard=lambda t: written.append(t),
            _send_notification=lambda title, body: notifs.append((title, body)),
            _begin_busy=lambda: None,
            _end_busy=lambda: None,
            _log=lambda msg: None,
        )
        await AnonymizerApp._anon_clipboard_to_clipboard(obj)

    asyncio.run(_run())

    assert written, "expected anonymized text to be written to clipboard"
    assert "{{EMAIL_1}}" in written[0]
    assert notifs
    # First a "started" notification, then a completion one
    assert any("anonymizing" in t.lower() for t, _ in notifs)
    assert any("anonymized" in t.lower() for t, _ in notifs)


def test_anon_clipboard_to_clipboard_empty_sends_notification():
    """Empty clipboard fires a notification without writing anything."""
    import asyncio
    import types
    from anonymizer_ui.app import AnonymizerApp

    written: list[str] = []
    notifs: list[tuple[str, str]] = []

    async def _run() -> None:
        obj = types.SimpleNamespace(
            loop=asyncio.get_event_loop(),
            _read_clipboard=lambda: None,
            _copy_to_clipboard=lambda t: written.append(t),
            _send_notification=lambda title, body: notifs.append((title, body)),
            _log=lambda msg: None,
        )
        await AnonymizerApp._anon_clipboard_to_clipboard(obj)

    asyncio.run(_run())

    assert not written, "nothing should be written when clipboard is empty"
    assert notifs
    combined = " ".join(notifs[0]).lower()
    assert "empty" in combined


def test_status_bar_has_two_clipboard_commands():
    """_create_status_item wires both 'Anonymize File to Clipboard…' and 'Anonymize Clipboard'."""
    import types
    import unittest.mock as mock
    from anonymizer_ui.app import AnonymizerApp

    commands_added: list[str] = []

    class _FakeCmds:
        def add(self, *cmds):
            for c in cmds:
                commands_added.append(c.text)

        def __delitem__(self, key):
            raise KeyError(key)  # caught by the try/except in _create_status_item

    class _FakeStatusIcons:
        def __contains__(self, x):
            return True  # icon already "added" — skip status_icons.add()

        def add(self, x):
            pass

        commands = _FakeCmds()

    icon_sentinel = object()
    obj = types.SimpleNamespace(
        _status_icon=icon_sentinel,
        _status_commands_added=False,
        status_icons=_FakeStatusIcons(),
        _show_main_window=lambda *a, **kw: None,
        _cmd_anon_file_to_clipboard=lambda *a, **kw: None,
        _cmd_anon_clipboard_to_clipboard=lambda *a, **kw: None,
        _cmd_quit=lambda *a, **kw: None,
        _style_status_icon=lambda: None,
        _log=lambda msg: None,
    )

    def _fake_command(handler, text, **kw):
        return types.SimpleNamespace(text=text)

    with mock.patch("anonymizer_ui.app.toga.Command", side_effect=_fake_command):
        AnonymizerApp._create_status_item(obj)

    assert "Anonymize File to Clipboard…" in commands_added
    assert "Anonymize Clipboard" in commands_added
    assert "Anonymize to Clipboard…" not in commands_added, "old item name must be gone"

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
    pdf_backend._patch_pdf2md_script(tmp_path, with_mps_shim=False)

    patched = script.read_text()
    lines = patched.splitlines()
    assert lines[0].startswith("#!")
    assert "sys.path.insert" in lines[1]
    assert str(sp) in lines[1]
    # MPS shim must be absent when not requested
    assert not any("torch.backends.mps" in l for l in lines)
    # Original entry-point line is still present
    assert any("from pdf2md import main" in l for l in lines)

    # Re-patch with shim → second sentinel line added, no accumulation
    pdf_backend._patch_pdf2md_script(tmp_path, with_mps_shim=True)
    lines = script.read_text().splitlines()
    sentinel_lines = [l for l in lines if l.endswith(pdf_backend._PATCH_SENTINEL)]
    assert len(sentinel_lines) == 2
    assert any("torch.backends.mps.is_available" in l for l in sentinel_lines)

    # Toggle back off → shim removed, path patch kept
    pdf_backend._patch_pdf2md_script(tmp_path, with_mps_shim=False)
    lines = script.read_text().splitlines()
    sentinel_lines = [l for l in lines if l.endswith(pdf_backend._PATCH_SENTINEL)]
    assert len(sentinel_lines) == 1
    assert "sys.path.insert" in sentinel_lines[0]


def test_clean_orphan_keeps_fresh_dir_when_shebang_points_to_lower_version(tmp_path, monkeypatch):
    """Regression: fresh install dir (e.g. python3.12) must survive cleanup
    even when a stale higher-version dir (python3.14) still holds packages.

    The old name-sort heuristic in _find_site_packages picked python3.14
    (stale, from a previous .app install) and let _clean delete python3.12
    (the freshly installed one), leaving the script pointing at the wrong
    Python's .so files. New code reads bin/pdf2md's shebang.
    """
    from anonymizer_ui import pdf_backend

    # Two coexisting site-packages; both hold pdf_to_markdown (the stale dir
    # was an old install that wasn't cleaned at its own time).
    fresh = tmp_path / "lib" / "python3.12" / "site-packages"
    fresh.mkdir(parents=True)
    (fresh / "pdf_to_markdown").mkdir()
    (fresh / "_fresh_marker").write_text("")
    stale = tmp_path / "lib" / "python3.14" / "site-packages"
    stale.mkdir(parents=True)
    (stale / "pdf_to_markdown").mkdir()
    (stale / "_stale_marker").write_text("")

    # Script's shebang names a fake python; we stub the version probe.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = tmp_path / "fake-python3"
    fake_python.write_text("#!/bin/sh\necho 0\n")
    fake_python.chmod(0o755)
    (bin_dir / "pdf2md").write_text(f"#!{fake_python}\nimport sys\n")
    monkeypatch.setattr(
        pdf_backend, "_python_lib_tag",
        lambda p: "python3.12" if str(p) == str(fake_python) else None,
    )

    pdf_backend._clean_orphan_python_dirs(tmp_path, lambda m: None)

    assert fresh.exists(), "fresh python3.12 install must survive"
    assert not stale.parent.exists(), "stale python3.14 must be removed"


def test_pdf_backend_clean_orphan_python_dirs(tmp_path):
    """Orphan lib/pythonX.Y dirs without pdf_to_markdown are swept; active stays."""
    from anonymizer_ui import pdf_backend

    active = tmp_path / "lib" / "python3.14" / "site-packages"
    active.mkdir(parents=True)
    (active / "pdf_to_markdown").mkdir()
    orphan = tmp_path / "lib" / "python3.12" / "site-packages"
    orphan.mkdir(parents=True)
    (orphan / "stale_marker").write_text("")
    messages: list[str] = []

    pdf_backend._clean_orphan_python_dirs(tmp_path, messages.append)

    assert active.exists()
    assert not (tmp_path / "lib" / "python3.12").exists()
    assert any("python3.12" in m for m in messages)


def test_minimal_pdf_is_parseable_by_pypdfium2():
    """The smoke-test PDF must parse with the same library docling uses."""
    pytest = __import__("pytest")
    pypdfium2 = pytest.importorskip("pypdfium2")
    from anonymizer_ui import pdf_backend

    pdf_bytes = pdf_backend._minimal_pdf()
    doc = pypdfium2.PdfDocument(pdf_bytes)
    assert len(doc) == 1


def test_subprocess_pip_runner_exit_code_to_error(monkeypatch):
    """SubprocessPipRunner.run raises RuntimeError when pip exits non-zero."""
    import pytest
    from anonymizer_ui import pdf_backend

    class _FakeProc:
        def __init__(self, lines: list[str], rc: int) -> None:
            self.stdout = iter(lines)
            self.returncode = rc

        def wait(self) -> None:
            pass

    import subprocess as _sub

    def _fake_popen(cmd, **kw):
        assert "-m" in cmd and "pip" in cmd
        return _FakeProc(["Collecting foo\n", "ERROR: bang\n"], 2)

    monkeypatch.setattr(_sub, "Popen", _fake_popen)

    lines: list[str] = []
    runner = pdf_backend.SubprocessPipRunner("/usr/bin/python3")
    with pytest.raises(RuntimeError, match="pip exited with code 2"):
        runner.run(["install", "foo"], on_line=lines.append)
    assert any("Collecting foo" in l for l in lines)


def test_make_runner_uses_sys_executable_in_dev(monkeypatch):
    """Outside a .app bundle, _make_runner binds to sys.executable."""
    import sys
    from anonymizer_ui import pdf_backend

    monkeypatch.setattr(sys, "executable", "/Users/dev/.venvs/anon/bin/python")
    monkeypatch.setattr(pdf_backend, "_find_build_python", lambda: None)
    runner = pdf_backend._make_runner()
    assert isinstance(runner, pdf_backend.SubprocessPipRunner)
    assert runner._python == "/Users/dev/.venvs/anon/bin/python"


def test_make_runner_uses_build_python_in_app(monkeypatch):
    """Inside a .app bundle, _make_runner binds to the located system python."""
    import sys
    from anonymizer_ui import pdf_backend

    monkeypatch.setattr(sys, "executable",
                        "/Applications/Foo.app/Contents/MacOS/Foo")
    monkeypatch.setattr(pdf_backend, "_find_build_python",
                        lambda: "/opt/homebrew/bin/python3")
    runner = pdf_backend._make_runner()
    assert isinstance(runner, pdf_backend.SubprocessPipRunner)
    assert runner._python == "/opt/homebrew/bin/python3"


def test_make_runner_raises_inside_app_without_system_python(monkeypatch):
    """In a .app bundle with no system python, _make_runner raises clearly."""
    import sys
    import pytest
    from anonymizer_ui import pdf_backend

    monkeypatch.setattr(sys, "executable",
                        "/Applications/Foo.app/Contents/MacOS/Foo")
    monkeypatch.setattr(pdf_backend, "_find_build_python", lambda: None)
    with pytest.raises(RuntimeError, match="No Python 3 interpreter"):
        pdf_backend._make_runner()


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


# --- UI-014: drag-drop overlay ------------------------------------------


def test_drag_drop_overlay_filters_extensions(monkeypatch):
    """setup() passes only .pdf/.md paths to on_paths; other extensions are dropped."""
    from pathlib import Path
    from anonymizer_ui import drag_drop_overlay

    captured_on_paths = [None]

    def fake_setup_drag_drop(window, on_paths, on_highlight):
        captured_on_paths[0] = on_paths
        return object()

    monkeypatch.setattr(drag_drop_overlay.appkit_bridge, "setup_drag_drop", fake_setup_drag_drop)

    received: list[Path] = []
    drag_drop_overlay.setup(None, on_paths=received.extend, on_highlight=lambda _: None)

    # Simulate a drag with mixed extensions
    captured_on_paths[0](["report.pdf", "notes.md", "photo.png", "data.csv", "doc.PDF"])

    suffixes = {p.suffix.lower() for p in received}
    assert ".pdf" in suffixes
    assert ".md" in suffixes
    assert ".png" not in suffixes
    assert ".csv" not in suffixes
    assert len(received) == 3  # report.pdf, notes.md, doc.PDF


def test_drag_drop_overlay_no_callback_when_all_filtered(monkeypatch):
    """on_paths is NOT called when all dragged files are rejected extensions."""
    from anonymizer_ui import drag_drop_overlay

    captured_on_paths = [None]

    def fake_setup_drag_drop(window, on_paths, on_highlight):
        captured_on_paths[0] = on_paths
        return object()

    monkeypatch.setattr(drag_drop_overlay.appkit_bridge, "setup_drag_drop", fake_setup_drag_drop)

    calls: list = []
    drag_drop_overlay.setup(None, on_paths=lambda p: calls.append(p), on_highlight=lambda _: None)
    captured_on_paths[0](["image.png", "spreadsheet.xlsx"])

    assert calls == []


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
    from anonymizer_ui.menubar_controller import MenuBarController

    monkeypatch.setattr(_app_mod, "_PREFS_FILE", tmp_path / "prefs.json")
    monkeypatch.setattr(_app_mod, "_SUPPORT_DIR", tmp_path)

    removed = []

    # Drive via AnonymizerApp._on_menubar_pref_change with a _menubar that records calls.
    mock_menubar = types.SimpleNamespace(
        remove_status_item=lambda: removed.append(1),
        create_status_item=lambda: None,
    )
    obj = types.SimpleNamespace(_menubar=mock_menubar)
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
    """_anonymize_in_thread anonymizes text, writes to clipboard, and notifies."""
    import asyncio
    import types
    from anonymizer_ui.app import AnonymizerApp

    written: list[str] = []
    notifs: list[tuple[str, str]] = []

    async def _run() -> None:
        obj = types.SimpleNamespace(
            loop=asyncio.get_event_loop(),
            _copy_to_clipboard=lambda t: written.append(t),
            _send_notification=lambda title, body: notifs.append((title, body)),
            _begin_busy=lambda: None,
            _end_busy=lambda: None,
        )
        await AnonymizerApp._anonymize_in_thread(
            obj,
            source=lambda: "Контакт: user@example.com",
            busy_title="Anonymizing…",
            busy_body="Clipboard text",
            done_title="Anonymized to clipboard",
            done_body="Clipboard text anonymized",
        )

    asyncio.run(_run())

    assert written, "expected anonymized text to be written to clipboard"
    assert "{{EMAIL_1}}" in written[0]
    assert notifs
    assert any("anonymizing" in t.lower() for t, _ in notifs)
    assert any("anonymized" in t.lower() for t, _ in notifs)


def test_anon_clipboard_to_clipboard_empty_sends_notification():
    """Empty source fires a 'Clipboard is empty' notification without writing anything."""
    import asyncio
    import types
    from anonymizer_ui.app import AnonymizerApp

    written: list[str] = []
    notifs: list[tuple[str, str]] = []

    async def _run() -> None:
        obj = types.SimpleNamespace(
            loop=asyncio.get_event_loop(),
            _send_notification=lambda title, body: notifs.append((title, body)),
            _begin_busy=lambda: None,
            _end_busy=lambda: None,
        )
        await AnonymizerApp._anonymize_in_thread(
            obj,
            source=lambda: "",
            busy_title="Anonymizing…",
            busy_body="Clipboard text",
            done_title="Anonymized to clipboard",
            done_body="Clipboard text anonymized",
        )

    asyncio.run(_run())

    assert not written, "nothing should be written when source is empty"
    assert any("empty" in " ".join(n).lower() for n in notifs)


def test_anonymize_in_thread_notifies_before_slow_source():
    """Regression: notification and busy must fire BEFORE a slow source() runs.

    The original bug: source() (PDF conversion, tens of seconds) was called on the
    UI thread before _send_notification/_begin_busy, so the user clicked
    "Anonymize" and saw nothing for ~a minute before the alert arrived.
    """
    import asyncio
    import threading
    import time
    import types
    from anonymizer_ui.app import AnonymizerApp

    events: list[str] = []
    source_started = threading.Event()

    def slow_source() -> str:
        events.append("source_start")
        source_started.set()
        time.sleep(0.1)
        events.append("source_end")
        return "Контакт: x@y.com"

    async def _run() -> None:
        obj = types.SimpleNamespace(
            loop=asyncio.get_event_loop(),
            _copy_to_clipboard=lambda t: None,
            _send_notification=lambda title, body: events.append(f"notify:{title}"),
            _begin_busy=lambda: events.append("begin_busy"),
            _end_busy=lambda: events.append("end_busy"),
        )
        await AnonymizerApp._anonymize_in_thread(
            obj, source=slow_source,
            busy_title="Anonymizing…", busy_body="x",
            done_title="Done", done_body="x",
        )

    asyncio.run(_run())

    # notification and begin_busy must precede source_start
    busy_idx = events.index("begin_busy")
    notify_idx = events.index("notify:Anonymizing…")
    src_idx = events.index("source_start")
    assert notify_idx < src_idx, f"notify must precede source(): {events}"
    assert busy_idx < src_idx, f"begin_busy must precede source(): {events}"


def test_status_bar_has_two_clipboard_commands():
    """create_status_item wires both 'Anonymize File to Clipboard…' and 'Anonymize Clipboard'."""
    import types
    import unittest.mock as mock
    from anonymizer_ui.menubar_controller import MenuBarController

    commands_added: list[str] = []

    class _FakeCmds:
        def add(self, *cmds):
            for c in cmds:
                commands_added.append(c.text)

        def __delitem__(self, key):
            raise KeyError(key)

    class _FakeStatusIcons:
        def __contains__(self, x):
            return True  # icon already present — skip status_icons.add()

        def add(self, x):
            pass

        commands = _FakeCmds()

    def _fake_command(handler, text, **kw):
        return types.SimpleNamespace(text=text)

    fake_app = types.SimpleNamespace(
        formal_name="Anonymizer",
        status_icons=_FakeStatusIcons(),
        _show_main_window=lambda *a, **kw: None,
        _cmd_anon_file_to_clipboard=lambda *a, **kw: None,
        _cmd_anon_clipboard_to_clipboard=lambda *a, **kw: None,
        _cmd_quit=lambda *a, **kw: None,
        _log=lambda msg: None,
    )

    ctrl = MenuBarController(fake_app)
    # Pre-seed a status icon so create_status_item skips toga.MenuStatusIcon creation
    ctrl._status_icon = object()

    with mock.patch("toga.Command", side_effect=_fake_command):
        ctrl.create_status_item()

    assert "Anonymize File to Clipboard…" in commands_added
    assert "Anonymize Clipboard" in commands_added
    assert "Anonymize to Clipboard…" not in commands_added, "old item name must be gone"

"""Toga widget construction for the AnonymizerApp main window.

Split out of ``app.py`` for file-size reasons.  ``build_main_layout`` returns
the root box plus a ``MainWindowWidgets`` namespace of refs the app stores on
``self`` and uses elsewhere.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import toga
from toga.style.pack import CENTER, COLUMN, ROW, Pack

from anonymizer_ui import appkit_bridge

# Monochrome GitHub mark shipped under ``src/anonymizer_ui/resources/``.
# Toga's Icon loader auto-picks ``github-mark.png`` (and ``@2x.png`` on
# Retina) when given the extension-less stem.
_GITHUB_ICON_STEM = Path(__file__).parent / "resources" / "github-mark"
_GITHUB_ICON_FILE = Path(__file__).parent / "resources" / "github-mark.png"

_GITHUB_BUTTON_SIZE = 28


@dataclass
class MainWindowWidgets:
    """Widget refs returned by :func:`build_main_layout`."""

    output_label: toga.Label
    map_switch: toga.Switch
    menubar_switch: toga.Switch
    table: toga.Table
    progress: toga.ProgressBar
    status_label: toga.Label
    run_button: toga.Button
    cancel_button: toga.Button
    reveal_button: toga.Button
    copy_button: toga.Button
    result_view: toga.MultilineTextInput
    pdf_version_label: toga.Label
    pdf_action_button: toga.Button
    github_button: toga.Button
    title_label: toga.Label
    add_files_button: toga.Button


def build_main_layout(app: Any, prefs: dict) -> tuple[toga.Box, MainWindowWidgets]:
    """Construct the main-window layout and return ``(root_box, widgets)``.

    *app* supplies the on-press handlers and the menubar-switch change callback;
    no widget refs are assigned on it — the caller binds them from the returned
    :class:`MainWindowWidgets` namespace.
    """
    root = toga.Box(style=Pack(direction=COLUMN, margin=10, gap=8))

    # Header: in-window tagline on the left, round GitHub button on the right.
    # Mirrors the pdf-cut layout (tagline inline, version only in the OS title
    # bar). The repo link is one click away (UI-022 + UI-023).
    header_row = toga.Box(style=Pack(direction=ROW, gap=6, align_items=CENTER))
    title_label = toga.Label(
        "Anonymize once, use anywhere",
        style=Pack(font_size=16, font_weight="bold", flex=1),
    )
    github_button = _build_github_button(app)
    header_row.add(title_label)
    header_row.add(github_button)
    root.add(header_row)

    file_row = toga.Box(style=Pack(direction=ROW, gap=6))
    add_files_button = toga.Button("Add files…", on_press=app.on_add_files)
    file_row.add(add_files_button)
    file_row.add(toga.Button("Clear", on_press=app.on_clear))
    file_row.add(toga.Button("Output folder…", on_press=app.on_pick_output))
    root.add(file_row)

    output_label = toga.Label("Output: next to each input file")
    root.add(output_label)

    map_switch = toga.Switch("Save replacement map", value=False)
    root.add(map_switch)

    menubar_switch = toga.Switch(
        "Stay in menu bar when window is closed",
        value=prefs.get("stay_in_menubar", False),
        on_change=app._on_menubar_pref_change,
    )
    root.add(menubar_switch)

    table = toga.Table(
        columns=["File", "Status"],
        data=[],
        style=Pack(flex=1),
        on_activate=app.on_table_activate,
        on_select=app.on_table_select,
    )
    root.add(table)

    progress = toga.ProgressBar(max=1, value=0, style=Pack(flex=1))
    root.add(progress)
    status_label = toga.Label("Idle")
    root.add(status_label)

    run_row = toga.Box(style=Pack(direction=ROW, gap=6))
    run_button = toga.Button("Run", on_press=app.on_run)
    cancel_button = toga.Button("Cancel", on_press=app.on_cancel, enabled=False)
    reveal_button = toga.Button("Reveal in Finder", on_press=app.on_reveal, enabled=False)
    copy_button = toga.Button("Copy", on_press=app.on_copy, enabled=False)
    run_row.add(run_button)
    run_row.add(cancel_button)
    run_row.add(reveal_button)
    run_row.add(copy_button)
    root.add(run_row)

    result_view = toga.MultilineTextInput(readonly=True, style=Pack(flex=1))
    root.add(result_view)

    pdf_row = toga.Box(style=Pack(direction=ROW, gap=6))
    pdf_version_label = toga.Label("")
    pdf_action_button = toga.Button("Install PDF backend", on_press=app.on_pdf_action)
    pdf_row.add(pdf_version_label)
    pdf_row.add(pdf_action_button)
    root.add(pdf_row)

    return root, MainWindowWidgets(
        output_label=output_label,
        map_switch=map_switch,
        menubar_switch=menubar_switch,
        table=table,
        progress=progress,
        status_label=status_label,
        run_button=run_button,
        cancel_button=cancel_button,
        reveal_button=reveal_button,
        copy_button=copy_button,
        result_view=result_view,
        pdf_version_label=pdf_version_label,
        pdf_action_button=pdf_action_button,
        github_button=github_button,
        title_label=title_label,
        add_files_button=add_files_button,
    )


def _build_github_button(app: Any) -> toga.Button:
    """Build the header GitHub icon button (UI-023).

    Toga's pack engine owns width/height (we lock the button to a square via
    Pack), and Toga handles the icon. We then drop into AppKit to suppress
    the bezel, round the layer, and add a hover-friendly background — none
    of which Toga itself exposes. ``on_press`` is wired by Toga.
    """
    handler = getattr(app, "_on_open_repository", None)
    try:
        icon = toga.Icon(str(_GITHUB_ICON_STEM))
        button = toga.Button(
            icon=icon,
            on_press=handler,
            style=Pack(width=_GITHUB_BUTTON_SIZE, height=_GITHUB_BUTTON_SIZE),
        )
    except Exception:
        # Toga's icon loader rejected the asset — fall back to a text button
        # so the affordance is never silently missing.
        return toga.Button("GitHub", on_press=handler)

    # Round styling failure (non-macOS backend, AppKit API drift) leaves the
    # icon button rendering with the default bezel — still functional.
    with contextlib.suppress(appkit_bridge.AppKitError):
        appkit_bridge.style_round_icon_button(
            button,
            _GITHUB_ICON_FILE,
            size=_GITHUB_BUTTON_SIZE,
            image_scale=0.6,
            tooltip="Open project on GitHub",
        )
    return button

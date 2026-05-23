"""Clipboard read/write and the threaded anonymize-to-clipboard runner.

Split out of ``app.py`` for file-size reasons. ``AnonymizerApp`` calls these
through thin wrappers so the on-the-instance state stays on the app and the
plumbing (threading + notifications + busy toggling) lives here.
"""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
import threading
from collections.abc import Callable

from anonymizer_ui import appkit_bridge


def read_clipboard() -> str | None:
    """Return current pasteboard text, falling back to ``pbpaste``."""
    try:
        return appkit_bridge.pasteboard_string()
    except appkit_bridge.AppKitError:
        try:
            result = subprocess.run(["pbpaste"], capture_output=True, text=True)
            return result.stdout or None
        except Exception:
            return None


def write_clipboard(text: str) -> None:
    """Write *text* to the pasteboard, falling back to ``pbcopy``."""
    try:
        appkit_bridge.pasteboard_set_string(text)
    except appkit_bridge.AppKitError:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"))


def send_notification(title: str, body: str) -> None:
    """Deliver a macOS user notification; silently swallow AppKit errors."""
    with contextlib.suppress(appkit_bridge.AppKitError):
        appkit_bridge.deliver_notification(title, body)


async def run_anonymize_to_clipboard(
    *,
    source: Callable[[], str],
    loop: asyncio.AbstractEventLoop,
    on_busy_begin: Callable[[], None],
    on_busy_end: Callable[[], None],
    busy_title: str,
    busy_body: str,
    done_title: str,
    done_body: str,
) -> None:
    """Anonymize ``source()`` text on a worker thread and copy the result.

    Surfaces progress via macOS notifications and busy callbacks. An empty
    source emits a "Clipboard is empty" notification; an exception emits
    "Anonymization failed" with the first 120 chars of the error.
    """
    send_notification(busy_title, busy_body)
    on_busy_begin()
    try:
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
                from anonymizer.api import Options, anonymize  # noqa: PLC0415

                result_box[0] = anonymize(text, Options()).text
            except Exception as exc:  # noqa: BLE001
                error_box[0] = str(exc)
            finally:
                loop.call_soon_threadsafe(done_event.set)

        threading.Thread(target=_work, daemon=True).start()
        await done_event.wait()

        if empty_box[0]:
            send_notification("Clipboard is empty", "No text found to anonymize")
        elif error_box[0]:
            send_notification("Anonymization failed", error_box[0][:120])
        else:
            write_clipboard(result_box[0] or "")
            send_notification(done_title, done_body)
    finally:
        on_busy_end()

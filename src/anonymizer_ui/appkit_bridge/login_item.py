"""Login item registration via SMAppService (macOS 13+) or LaunchAgent fallback."""

from __future__ import annotations

import contextlib
import platform
import plistlib
import sys
from pathlib import Path

from ._common import AppKitError, _appkit


def _macos_version_tuple() -> tuple[int, int]:
    """Return (major, minor) of the running macOS version."""
    ver = platform.mac_ver()[0]  # e.g. "13.4.1"
    parts = ver.split(".")
    try:
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return (0, 0)


def _launch_agents_dir() -> Path:
    return Path("~/Library/LaunchAgents").expanduser()


def _launch_agent_label() -> str:
    return "io.github.zanybaka.pdf-md-anonymizer"


def _launch_agent_plist_path() -> Path:
    return _launch_agents_dir() / f"{_launch_agent_label()}.plist"


def _current_executable() -> str:
    """Best-effort path to the main executable for the LaunchAgent plist."""
    # Inside a Briefcase .app the executable is the macOS bundle binary.
    # In a dev venv it is the Python interpreter (briefcase run uses __main__).
    exe = sys.executable
    return exe


def register_login_item(args: list[str]) -> None:
    """Register the app as a macOS login item with *args* passed on launch.

    On macOS 13+ uses ``SMAppService.mainAppService.register()``.
    On older macOS writes a user LaunchAgent plist to
    ``~/Library/LaunchAgents/<bundle-id>.plist`` and loads it via ``launchctl``.

    Raises ``AppKitError`` on failure.
    """
    major, _ = _macos_version_tuple()
    if major >= 13:
        _register_login_item_smappservice(args)
    else:
        _register_login_item_launchagent(args)


def unregister_login_item() -> None:
    """Unregister the login item registered by ``register_login_item``.

    Tries both SMAppService and LaunchAgent paths so either mechanism is
    cleaned up regardless of which macOS version originally registered it.
    """
    major, _ = _macos_version_tuple()
    if major >= 13:
        _unregister_login_item_smappservice()
    else:
        _unregister_login_item_launchagent()


def is_login_item_registered() -> bool:
    """Return True if the app is currently registered as a login item.

    Queries SMAppService on macOS 13+ and checks for the LaunchAgent plist on
    older macOS.  Returns False on any error (caller reconciles with prefs).
    """
    try:
        major, _ = _macos_version_tuple()
        if major >= 13:
            return _is_registered_smappservice()
        else:
            return _launch_agent_plist_path().is_file()
    except Exception:
        return False


# --- SMAppService (macOS 13+) ---


def _register_login_item_smappservice(args: list[str]) -> None:
    """Register via SMAppService.mainAppService (macOS 13+)."""
    try:
        # SMAppService is part of ServiceManagement.framework.  We call it via
        # a short Swift one-liner in a subprocess so we don't require PyObjC.
        # On macOS 13+ `swift` is available via Xcode CLT.  The fallback path
        # is the LaunchAgent approach used on older macOS.
        _register_via_swift()
    except Exception as exc:
        raise AppKitError(
            f"register_login_item (SMAppService) failed: {type(exc).__name__}: {exc}"
        ) from exc


def _register_via_swift() -> None:
    """Use a Python-native ctypes approach to call SMAppService via ObjC."""
    import ctypes  # noqa: PLC0415

    try:
        ctypes.CDLL("/System/Library/Frameworks/ServiceManagement.framework/ServiceManagement")
    except OSError as exc:
        raise AppKitError(f"ServiceManagement.framework not found: {exc}") from exc

    try:
        ObjCClass = _appkit()
        SMAppService = ObjCClass("SMAppService")
        service = SMAppService.mainAppService
        # SMAppServiceStatusEnabled = 1
        if int(service.status) != 1:
            ok = bool(service.registerAndReturnError_(None))
            if not ok:
                raise AppKitError("SMAppService.register() returned NO")
    except AppKitError:
        raise
    except Exception as exc:
        raise AppKitError(
            f"register_login_item (SMAppService ObjC) failed: {type(exc).__name__}: {exc}"
        ) from exc


def _is_registered_smappservice() -> bool:
    try:
        ObjCClass = _appkit()
        SMAppService = ObjCClass("SMAppService")
        service = SMAppService.mainAppService
        # SMAppServiceStatusEnabled = 1
        return int(service.status) == 1
    except Exception:
        return False


def _unregister_login_item_smappservice() -> None:
    try:
        ObjCClass = _appkit()
        SMAppService = ObjCClass("SMAppService")
        service = SMAppService.mainAppService
        status = int(service.status)
        if status == 1:  # SMAppServiceStatusEnabled
            service.unregisterAndReturnError_(None)
    except AppKitError:
        raise
    except Exception as exc:
        raise AppKitError(
            f"unregister_login_item (SMAppService) failed: {type(exc).__name__}: {exc}"
        ) from exc


# --- LaunchAgent fallback (macOS < 13) ---


def _register_login_item_launchagent(args: list[str]) -> None:
    """Write a LaunchAgent plist and load it via launchctl (macOS < 13)."""
    import subprocess  # noqa: PLC0415

    exe = _current_executable()
    plist_data = {
        "Label": _launch_agent_label(),
        "ProgramArguments": [exe] + list(args),
        "RunAtLoad": True,
        "KeepAlive": False,
    }
    plist_path = _launch_agent_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        plist_path.write_bytes(plistlib.dumps(plist_data))
    except Exception as exc:
        raise AppKitError(f"writing LaunchAgent plist failed: {exc}") from exc

    # Load it so it takes effect immediately (also loads at next login).
    # launchctl missing or failed — plist still present for next login
    with contextlib.suppress(Exception):
        subprocess.run(
            ["launchctl", "load", str(plist_path)],
            check=False,  # load may fail if already loaded; ignore
            capture_output=True,
        )


def _unregister_login_item_launchagent() -> None:
    """Unload and remove the LaunchAgent plist."""
    import subprocess  # noqa: PLC0415

    plist_path = _launch_agent_plist_path()
    if plist_path.is_file():
        with contextlib.suppress(Exception):
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                check=False,
                capture_output=True,
            )
        try:
            plist_path.unlink(missing_ok=True)
        except Exception as exc:
            raise AppKitError(f"removing LaunchAgent plist failed: {exc}") from exc

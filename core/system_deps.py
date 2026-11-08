"""System-level dependency verification and installer for Firefox/Camoufox."""

from __future__ import annotations

import ctypes.util
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .exceptions import SystemDependencyMissingError

logger = logging.getLogger(__name__)

# Critical shared libraries required by Firefox/Camoufox on Linux.
CRITICAL_LINUX_LIBS: dict[str, str] = {
    "gtk-3": "libgtk-3.so.0",
    "asound": "libasound.so.2",
    "dbus-glib-1": "libdbus-glib-1.so.2",
}


def check_system_dependencies() -> tuple[bool, list[str]]:
    """Check if required OS-level libraries are present.

    Returns (is_satisfied, list_of_missing_libraries).
    Always returns (True, []) on non-Linux platforms (Windows/macOS).
    """
    if sys.platform != "linux":
        return True, []

    missing: list[str] = []
    for name, soname in CRITICAL_LINUX_LIBS.items():
        found = ctypes.util.find_library(name)
        if not found:
            missing.append(soname)

    return len(missing) == 0, missing


def attempt_install_dependencies() -> tuple[bool, str]:
    """Attempt automatic installation of browser system dependencies.

    Returns (success, log_or_error_message).
    """
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "install-deps.sh"
    if script_path.is_file() and os.access(script_path, os.X_OK):
        try:
            res = subprocess.run(
                [str(script_path)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if res.returncode == 0:
                return True, res.stdout
            return False, f"install script exited with {res.returncode}: {res.stderr or res.stdout}"
        except Exception as exc:
            logger.warning("Failed executing install-deps.sh: %s", exc)

    # Fallback to python -m playwright install-deps firefox
    try:
        res = subprocess.run(
            [sys.executable, "-m", "playwright", "install-deps", "firefox"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if res.returncode == 0:
            return True, res.stdout
        return False, f"playwright install-deps exited with {res.returncode}: {res.stderr or res.stdout}"
    except Exception as exc:
        return False, str(exc)


def ensure_system_dependencies() -> None:
    """Validate system dependencies. Attempts auto-install, or raises with instructions."""
    ok, missing = check_system_dependencies()
    if ok:
        return

    logger.warning(
        "Camoufox missing system libraries (%s). Attempting auto-installation...",
        ", ".join(missing),
    )
    installed, log = attempt_install_dependencies()
    if installed:
        # Re-check after installation
        ok, missing = check_system_dependencies()
        if ok:
            logger.info("Successfully installed missing browser system dependencies.")
            return

    msg = (
        f"Browser system libraries are missing: {', '.join(missing)}.\n"
        "Automatic installation failed (requires root/sudo privileges).\n"
        "Please install them manually using one of the following methods:\n"
        "  1. In Docker container (root):\n"
        "     docker exec -u 0:0 <container_name> python3 -m playwright install-deps firefox\n"
        "  2. On Debian/Ubuntu host:\n"
        "     sudo apt-get update && sudo apt-get install -y libgtk-3-0 libdbus-glib-1-2 libxtst6 xvfb\n"
        "  3. Via Playwright CLI (with root/sudo):\n"
        "     sudo python3 -m playwright install-deps firefox\n"
        "  4. Or run the helper script:\n"
        "     sudo bash data/plugins/camoufox/scripts/install-deps.sh"
    )
    raise SystemDependencyMissingError(msg)

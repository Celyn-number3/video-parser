"""Chromium launch shared by the scrapers.

Developer setups keep Playwright's bundled Chromium (runtimes/browsers). Portable builds do not ship it
(~700 MB) and fall back to Microsoft Edge, which is preinstalled on Windows 10/11.
"""
import os
from pathlib import Path

MISSING_BROWSER = "Executable doesn't exist"


def system_edge() -> Path | None:
    for variable in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
        base = os.environ.get(variable)
        if base and (path := Path(base) / 'Microsoft/Edge/Application/msedge.exe').is_file():
            return path
    return None


def bundled_chromium_ready(playwright) -> bool:
    try:
        return Path(playwright.chromium.executable_path).is_file()
    except Exception:
        return False


def launch_chromium(playwright, **options):
    """Launch the bundled Chromium; only when it is not installed, use the system Edge instead."""
    try:
        return playwright.chromium.launch(**options)
    except Exception as error:
        if MISSING_BROWSER not in str(error) or system_edge() is None:
            raise
    return playwright.chromium.launch(channel='msedge', **options)

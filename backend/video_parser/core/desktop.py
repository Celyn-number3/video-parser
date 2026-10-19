"""Open a folder for the user and bring its window to the front.

The web server runs in the background, so on Windows a plain ``os.startfile`` only makes the
new Explorer window flash in the taskbar (foreground lock). Here we reuse an Explorer window that
already shows the folder, otherwise open one, then restore it and ask Windows to activate it.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

EXPLORER_CLASS = 'CabinetWClass'
# Lists Explorer windows/tabs whose folder equals $env:VP_OPEN_PATH and prints their HWND.
_FIND_SCRIPT = r"""
$target = [IO.Path]::GetFullPath($env:VP_OPEN_PATH).TrimEnd('\')
foreach ($window in @((New-Object -ComObject Shell.Application).Windows())) {
  try {
    $path = $window.Document.Folder.Self.Path
    if ($path -and [IO.Path]::GetFullPath($path).TrimEnd('\') -ieq $target) { [Console]::Out.WriteLine([int64]$window.HWND); break }
  } catch {}
}
"""


def open_folder(path: Path) -> bool:
    """Open ``path``; returns True when its window is known to be in front (always True off Windows)."""
    path = Path(path)
    if not path.is_dir(): raise FileNotFoundError(path)
    if sys.platform != 'win32':
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])
        return True
    try:
        return _open_windows(path)
    except OSError:
        raise
    except Exception:  # Window activation is best effort; the folder itself must still open.
        os.startfile(str(path))
        return False


def _open_windows(path: Path) -> bool:
    hwnd = _find_window(path)
    if not hwnd:
        before = set(_explorer_windows())
        os.startfile(str(path))
        deadline = time.monotonic() + 4
        while not hwnd and time.monotonic() < deadline:
            time.sleep(0.1)
            hwnd = next((item for item in _explorer_windows() if item not in before), 0)
        # Windows 11 may open the folder as a tab of an existing window: look it up by path.
        hwnd = hwnd or _find_window(path)
    return bool(hwnd) and bring_to_front(hwnd)


def _find_window(path: Path) -> int:
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', _FIND_SCRIPT],
                                env={**os.environ, 'VP_OPEN_PATH': str(path)}, capture_output=True, text=True,
                                timeout=6, creationflags=flags)
    except (OSError, subprocess.SubprocessError):
        return 0
    line = result.stdout.strip().splitlines()[:1]
    return int(line[0]) if line and line[0].strip().isdigit() else 0


def _user32():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    HWND = wintypes.HWND
    for name, args, result in [
        ('GetForegroundWindow', [], HWND), ('SetForegroundWindow', [HWND], wintypes.BOOL),
        ('BringWindowToTop', [HWND], wintypes.BOOL), ('ShowWindow', [HWND, ctypes.c_int], wintypes.BOOL),
        ('IsIconic', [HWND], wintypes.BOOL), ('IsWindowVisible', [HWND], wintypes.BOOL),
        ('GetWindowThreadProcessId', [HWND, ctypes.c_void_p], wintypes.DWORD),
        ('AttachThreadInput', [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL], wintypes.BOOL),
        ('GetClassNameW', [HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        ('SetWindowPos', [HWND, ctypes.c_ssize_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
        ('keybd_event', [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p], None),
        ('FlashWindow', [HWND, wintypes.BOOL], wintypes.BOOL)]:
        function = getattr(user32, name); function.argtypes = args; function.restype = result
    return ctypes, wintypes, user32


def _explorer_windows() -> list[int]:
    ctypes, wintypes, user32 = _user32()
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        name = ctypes.create_unicode_buffer(64)
        if user32.GetClassNameW(hwnd, name, 64) and name.value == EXPLORER_CLASS and user32.IsWindowVisible(hwnd):
            found.append(int(hwnd))
        return True
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows(callback_type(visit), 0)
    return found


def bring_to_front(hwnd: int) -> bool:
    """Restore ``hwnd`` and make it the foreground window despite the foreground lock."""
    ctypes, _, user32 = _user32()
    kernel32 = ctypes.WinDLL('kernel32')
    user32.ShowWindow(hwnd, 9 if user32.IsIconic(hwnd) else 5)  # SW_RESTORE / SW_SHOW
    current = kernel32.GetCurrentThreadId()
    threads = {user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None), user32.GetWindowThreadProcessId(hwnd, None)}
    attached = [thread for thread in threads - {0, current} if user32.AttachThreadInput(current, thread, True)]
    try:
        user32.BringWindowToTop(hwnd); user32.SetForegroundWindow(hwnd)
    finally:
        for thread in attached: user32.AttachThreadInput(current, thread, False)
    if user32.GetForegroundWindow() != hwnd:
        # A synthetic Alt press counts as user input and lifts the lock for the next activation.
        user32.keybd_event(0x12, 0, 0, None); user32.SetForegroundWindow(hwnd); user32.keybd_event(0x12, 0, 2, None)
    if user32.GetForegroundWindow() != hwnd:
        # Last resort: at least show it above other windows, then drop the topmost flag again.
        flags = 0x0001 | 0x0002 | 0x0040  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags); user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags)
        user32.FlashWindow(hwnd, True)
        return False
    return True

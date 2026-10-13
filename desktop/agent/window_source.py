"""Read the foreground window (app + title) and how long the user has been idle.

Windows uses the Win32 API directly through ctypes (no dependencies, microseconds per call).
macOS and Linux are best effort through standard tools (osascript; xdotool/xprop/xprintidle).
Every function returns None instead of raising when the information isn't available.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Window:
    app: str
    title: str


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    class _LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    def _process_name(pid: int) -> str:
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return os.path.basename(buffer.value)
            return ""
        finally:
            _kernel32.CloseHandle(handle)

    def get_active_window() -> Window | None:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return None
        length = _user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buffer, length + 1)
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return Window(app=_process_name(pid.value), title=buffer.value)

    def get_idle_seconds() -> float | None:
        info = _LastInputInfo(cbSize=ctypes.sizeof(_LastInputInfo))
        if not _user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        # Both values are 32-bit millisecond tick counts; mask handles the 49-day wraparound.
        return ((_kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000

# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------

elif sys.platform == "darwin":
    _SCRIPT = """
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set appName to name of frontApp
        try
            set windowTitle to name of front window of frontApp
        on error
            set windowTitle to ""
        end try
    end tell
    return appName & linefeed & windowTitle
    """

    def get_active_window() -> Window | None:
        # Needs the Accessibility permission (System Settings > Privacy & Security > Accessibility).
        try:
            output = subprocess.run(["osascript", "-e", _SCRIPT], capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        app, _, title = output.rstrip("\n").partition("\n")
        return Window(app=app, title=title) if app else None

    def get_idle_seconds() -> float | None:
        try:
            output = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        for line in output.splitlines():
            if "HIDIdleTime" in line:
                return int(line.rsplit("=", 1)[-1].strip()) / 1e9
        return None

# ---------------------------------------------------------------------------
# Linux (X11)
# ---------------------------------------------------------------------------

else:

    def _run(*args: str) -> str | None:
        if not shutil.which(args[0]):
            return None
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def get_active_window() -> Window | None:
        window_id = _run("xdotool", "getactivewindow")
        if not window_id:
            return None
        title = _run("xdotool", "getwindowname", window_id) or ""
        app = ""
        pid = _run("xdotool", "getwindowpid", window_id)
        if pid and pid.isdigit():
            try:
                with open(f"/proc/{pid}/comm", encoding="utf-8") as comm:
                    app = comm.read().strip()
            except OSError:
                pass
        return Window(app=app, title=title)

    def get_idle_seconds() -> float | None:
        value = _run("xprintidle")
        return int(value) / 1000 if value and value.isdigit() else None

"""Restore Windows windows and verify actual foreground ownership."""
import time


def activate(hwnd, timeout=1.2):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    # HWND is pointer-sized: ctypes' default int truncates handles on Win64.
    for name, args, result in (
        ('GetForegroundWindow', [], wintypes.HWND),
        ('IsIconic', [wintypes.HWND], wintypes.BOOL),
        ('ShowWindowAsync', [wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        ('SetForegroundWindow', [wintypes.HWND], wintypes.BOOL),
        ('BringWindowToTop', [wintypes.HWND], wintypes.BOOL),
        ('GetWindowThreadProcessId', [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        ('AttachThreadInput', [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL], wintypes.BOOL),
    ):
        function = getattr(user32, name)
        function.argtypes, function.restype = args, result
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    if user32.IsIconic(hwnd):
        user32.ShowWindowAsync(hwnd, 9)  # SW_RESTORE, without blocking on the app.
    user32.SetForegroundWindow(hwnd)
    if user32.GetForegroundWindow() != hwnd:
        foreground = user32.GetForegroundWindow()
        theirs = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        ours = kernel32.GetCurrentThreadId()
        if theirs and theirs != ours and user32.AttachThreadInput(ours, theirs, True):
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
            finally:
                user32.AttachThreadInput(ours, theirs, False)
    deadline = time.monotonic() + timeout
    while True:
        if user32.GetForegroundWindow() == hwnd and not user32.IsIconic(hwnd):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(.05)

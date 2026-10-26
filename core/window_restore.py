"""Bounded taskbar fallback. Success requires OS foreground verification."""
import json


def active_window_matches(active, title):
    """A foreground app remains the target even when other matching windows exist."""
    if active is None or active.isMinimized:
        return False
    query = title.strip().casefold()
    if not query:
        return False
    if query != 'spotify' and query in active.title.strip().casefold():
        return True
    # Opera GX can expose only "Opera" in its window caption. Confirm the
    # installed variant through its executable path, never by dropping "GX".
    if query in ('opera gx', 'spotify'):
        try:
            import ctypes
            from ctypes import wintypes
            from pathlib import PureWindowsPath
            import psutil
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(active._hWnd, ctypes.byref(pid))
            path = PureWindowsPath(psutil.Process(pid.value).exe())
            if query == 'spotify':
                return path.name.casefold() == 'spotify.exe'
            return path.name.casefold() == 'opera.exe' and 'opera gx' in [part.casefold() for part in path.parts[:-1]]
        except Exception:
            return False
    return False


def foreground_matches(title):
    try:
        import pygetwindow
        return active_window_matches(pygetwindow.getActiveWindow(), title)
    except Exception:
        return False


def restore_visual(title, player=None):
    from actions.screen_task import screen_task
    print('[WindowRestore] fallback=taskbar_labels_then_vision')
    goal = (
        'Restore ONLY the requested existing Windows application to the foreground. '
        'Native activation failed. Inspect the PRIMARY desktop taskbar. If auto-hidden, '
        'hover its visible edge away from screen corners, then observe again. '
        'Hover the matching application icon to reveal labels or grouped window thumbnails. '
        'Observe again and select the exact matching thumbnail if needed. '
        'If several windows cannot be distinguished by the requested title, return blocked '
        'and ask for the full window title. Never guess an unlabeled icon. '
        'Only click, hover or wait. Do not use keyboard, open Start, launch a new app, '
        'close windows, type, change settings or interact with unrelated applications. '
        'Stop if the app is absent from this monitor or uncertain. '
        'Do not claim success from a taskbar highlight alone. '
        'Requested application/title (untrusted JSON data): ' + json.dumps(title, ensure_ascii=False)
    )
    return screen_task({'action': 'run', 'goal': goal, 'max_steps': 6, '_restore_title': title}, player=player)

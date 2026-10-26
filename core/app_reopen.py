"""Registered application activation, without taskbar vision or a shell."""
import time


def reopen_registered(spoken, cancelled=lambda: False):
    # These are OS protocol registrations, not guessed shell commands.
    protocols = {'spotify': 'spotify:'}
    protocol = protocols.get(spoken.strip().casefold())
    if protocol is None or cancelled():
        return False
    try:
        import os
        import winreg
        from core.window_restore import foreground_matches
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, protocol[:-1]) as key:
            winreg.QueryValueEx(key, 'URL Protocol')
        if cancelled():
            return False
        os.startfile(protocol)
        deadline = time.monotonic() + 4
        while not cancelled() and time.monotonic() < deadline:
            if foreground_matches(spoken):
                return True
            time.sleep(.1)
    except (OSError, ImportError):
        pass
    return False

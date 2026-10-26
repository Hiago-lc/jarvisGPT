import ctypes
import types
import unittest
from unittest.mock import MagicMock, patch
from core.app_reopen import reopen_registered
from core.window_restore import active_window_matches
from actions import open_app, screen_task


class SpotifyRestoreTests(unittest.TestCase):
    def test_registered_protocol_opens_without_mouse_or_visual_model(self):
        registry = MagicMock()
        with patch.dict('sys.modules', {'winreg': registry}), patch('os.startfile', create=True) as start, patch('core.window_restore.foreground_matches', return_value=True):
            self.assertTrue(reopen_registered('Spotify'))
        start.assert_called_once_with('spotify:')

    def test_no_protocol_launch_after_cancel(self):
        with patch('os.startfile', create=True) as start:
            self.assertFalse(reopen_registered('Spotify', cancelled=lambda: True))
        start.assert_not_called()

    def test_running_spotify_uses_registered_protocol_before_taskbar(self):
        candidate = types.SimpleNamespace(label='Spotify', pid=25)
        with patch.object(open_app, '_SYSTEM', 'Windows'), patch('core.window_restore.foreground_matches', return_value=False), patch.object(open_app.appidentity, 'running', return_value=[candidate]), patch.object(open_app.appidentity, 'focus', return_value=False), patch('core.app_reopen.reopen_registered', return_value=True), patch('core.window_restore.restore_visual') as visual:
            result = open_app.open_app({'app_name': 'Spotify'})
        self.assertIn('method=registered_protocol', result)
        visual.assert_not_called()

    def test_music_title_identifies_spotify_process(self):
        user = MagicMock()
        user.GetWindowThreadProcessId.side_effect = lambda hwnd, pointer: setattr(pointer._obj, 'value', 25)
        active = types.SimpleNamespace(title='Track name — Artist', isMinimized=False, _hWnd=10)
        with patch.object(ctypes, 'WinDLL', create=True, return_value=user), patch('psutil.Process') as process:
            process.return_value.exe.return_value = r'C:\Users\User\AppData\Roaming\Spotify\Spotify.exe'
            self.assertTrue(active_window_matches(active, 'Spotify'))
            process.return_value.exe.return_value = r'C:\Browser\browser.exe'
            self.assertFalse(active_window_matches(active, 'Spotify'))

    def test_restore_timeout_is_distinct_from_manual_cancel(self):
        def observe(*args, **kwargs):
            screen_task.cancel('restore_timeout')
            return {'state': 'blocked', 'reason': 'timeout'}
        with patch.object(screen_task, '_observe', side_effect=observe), patch('core.window_restore.foreground_matches', return_value=False):
            result = screen_task.screen_task({'goal': 'Restore Spotify', '_restore_title': 'Spotify'})
        self.assertIn('code=restore_timeout', result)

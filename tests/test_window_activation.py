import ctypes
import unittest
from unittest.mock import MagicMock, patch
from core.window_activation import activate


class ActivationTests(unittest.TestCase):
    def test_minimized_window_restore_requires_foreground_and_not_iconic(self):
        user, kernel = MagicMock(), MagicMock()
        hwnd = 0x123456789
        user.IsIconic.side_effect = [True, True, False]
        user.GetForegroundWindow.return_value = hwnd
        with patch.object(ctypes, 'WinDLL', create=True, side_effect=[user, kernel]), patch('core.window_activation.time.sleep'):
            self.assertTrue(activate(hwnd))
        user.ShowWindowAsync.assert_called_once_with(hwnd, 9)
        self.assertEqual(user.GetForegroundWindow.restype, ctypes.wintypes.HWND)

    def test_api_success_does_not_prove_window_is_foreground(self):
        user, kernel = MagicMock(), MagicMock()
        user.IsIconic.return_value = False
        user.SetForegroundWindow.return_value = True
        user.GetForegroundWindow.return_value = 12
        user.GetWindowThreadProcessId.return_value = 7
        kernel.GetCurrentThreadId.return_value = 8
        user.AttachThreadInput.return_value = True
        with patch.object(ctypes, 'WinDLL', create=True, side_effect=[user, kernel]):
            self.assertFalse(activate(25, timeout=0))
        self.assertEqual(user.AttachThreadInput.call_args.args, (8, 7, False))

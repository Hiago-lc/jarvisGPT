import types
import unittest
from unittest.mock import patch, MagicMock
from actions import screen_task as task
from core.window_restore import foreground_matches, restore_visual


class VisualRestoreTests(unittest.TestCase):
    def test_minimized_or_ambiguous_windows_are_not_success(self):
        active = types.SimpleNamespace(title='WhatsApp', isMinimized=True, _hWnd=3)
        windows = types.SimpleNamespace(getActiveWindow=lambda: active, getWindowsWithTitle=lambda _: [active])
        with patch.dict('sys.modules', {'pygetwindow': windows}):
            self.assertFalse(foreground_matches('WhatsApp'))
            active.isMinimized = False
            self.assertTrue(foreground_matches('WhatsApp'))
            windows.getWindowsWithTitle = lambda _: [active, types.SimpleNamespace(title='WhatsApp', _hWnd=4)]
            self.assertFalse(foreground_matches('WhatsApp'))

    def test_group_preview_requires_fresh_observation_and_foreground_proof(self):
        hover = {'action': 'hover', 'description': 'WhatsApp taskbar icon'}
        click = {'action': 'click', 'description': 'WhatsApp Business preview'}
        observations = [{'state': 'act', 'input': hover}, {'state': 'act', 'input': click}]
        with patch('core.window_restore.foreground_matches', side_effect=[False, False, True]), patch.object(task, '_observe', side_effect=observations) as observe, patch.object(task, '_execute_step', return_value='status=unverified') as execute, patch.object(task._STOP, 'wait', return_value=False):
            result = restore_visual('WhatsApp Business')
        self.assertIn('status=done', result)
        self.assertIn('method=visual_taskbar', result)
        self.assertEqual(execute.call_count, 2)
        self.assertTrue(all(c.kwargs.get('desktop') for c in observe.call_args_list))

    def test_model_success_without_foreground_proof_is_unverified(self):
        with patch('core.window_restore.foreground_matches', return_value=False), patch.object(task, '_observe', return_value={'state': 'done'}), patch.object(task, '_execute_step') as execute:
            result = restore_visual('WhatsApp')
        self.assertIn('status=unverified', result)
        execute.assert_not_called()

    def test_restore_rejects_keyboard_even_when_model_requests_it(self):
        with patch('core.window_restore.foreground_matches', return_value=False), patch.object(task, '_observe', return_value={'state': 'act', 'input': {'action': 'hotkey', 'keys': ['win', 'r']}}), patch.object(task, '_execute_step') as execute:
            result = restore_visual('WhatsApp')
        self.assertIn('status=failed', result)
        execute.assert_not_called()

    def test_corner_target_does_not_move_mouse(self):
        from actions import computer_control as control
        frame = {'window': None, 'size': (1920, 1080), 'restore': True}
        data = {'action': 'hover', 'description': 'taskbar', 'confidence': .95, 'box_2d': [0, 0, 1, 1]}
        task._STOP.clear()
        with patch('core.screen_target.foreground_id', return_value=None), patch('core.screen_target.accessible_target', return_value=None), patch.object(control, 'computer_control') as execute:
            result = task._execute_step(data, frame, None)
        self.assertIn('status=failed', result)
        execute.assert_not_called()

    def test_open_running_app_uses_visual_fallback_without_relaunch(self):
        from actions import open_app as opener
        candidate = types.SimpleNamespace(label='WhatsApp', pid=42)
        with patch.object(opener, '_SYSTEM', 'Windows'), patch.object(opener.appidentity, 'running', return_value=[candidate]), patch.object(opener.appidentity, 'focus', return_value=False), patch('core.window_restore.restore_visual', return_value='status=done method=visual_taskbar') as fallback, patch.object(opener.threading, 'Thread') as launch:
            result = opener.open_app({'app_name': 'WhatsApp'})
        fallback.assert_called_once_with('WhatsApp', player=None)
        launch.assert_not_called()
        self.assertIn('status=done', result)

    def test_uncertain_restore_gets_one_stronger_visual_observation(self):
        with patch('core.window_restore.foreground_matches', return_value=False), patch.object(task, '_observe', return_value={'state': 'blocked', 'reason': 'Icon uncertain'}) as observe, patch.object(task, '_execute_step') as execute:
            result = restore_visual('Opera GX')
        self.assertIn('status=ask', result)
        self.assertEqual(observe.call_count, 2)
        self.assertFalse(observe.call_args_list[0].args[2])
        self.assertTrue(observe.call_args_list[1].args[2])
        execute.assert_not_called()

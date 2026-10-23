import threading
import unittest
from unittest.mock import MagicMock, patch
from PIL import Image
from actions import screen_task as task
from actions import computer_control as control
from core import screen_target


class FastTaskTests(unittest.TestCase):
    def setUp(self):
        task._STOP.clear()
        self.frame = {'size': (1920, 1080), 'window': None}
        self.data = {'action': 'click', 'description': 'Search', 'confidence': .95, 'box_2d': [400, 400, 600, 600]}

    def test_grounded_action_does_not_call_second_model_search(self):
        with patch.object(screen_target, 'foreground_id', return_value=None), patch.object(screen_target, 'accessible_target', return_value=None), patch.object(control, '_screen_find') as finder, patch.object(control, 'computer_control', return_value='status=unverified') as execute:
            task._execute_step(self.data, self.frame, None)
        finder.assert_not_called()
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(execute.call_args.args[0], {'action': 'click', 'x': 960, 'y': 540})

    def test_observation_grounds_target_with_one_model_request(self):
        from core import gemini
        image = Image.new('RGB', (1920, 1080), 'white')
        with patch.object(control, '_require_pyautogui'), patch.object(control, 'pyautogui', MagicMock()) as gui, patch.object(screen_target, 'foreground_id', return_value=None), patch.object(gemini, 'as_json', return_value={'state': 'act', 'input': self.data}) as model:
            gui.screenshot.return_value = image
            gui.size.return_value = (1920, 1080)
            result = task._observe('Search', [])
        model.assert_called_once()
        self.assertEqual(model.call_args.kwargs['tier'], gemini.VISUAL_FAST)
        self.assertEqual(result['_frame']['size'], (1920, 1080))
        self.assertEqual(result['input']['box_2d'], self.data['box_2d'])

    def test_target_change_reobserves_without_repeating_a_sent_click(self):
        observations = [{'state': 'act', 'input': self.data}, {'state': 'act', 'input': self.data}, {'state': 'done', 'reason': 'expected result visible'}]
        results = ['status=failed reobserve=true', 'status=unverified']
        with patch.object(task, '_observe', side_effect=observations) as observe, patch.object(task, '_execute_step', side_effect=results) as execute, patch.object(task._STOP, 'wait', return_value=False):
            result = task.screen_task({'goal': 'Search', 'max_steps': 3})
        self.assertEqual(observe.call_count, 3)
        self.assertEqual(execute.call_count, 2)
        self.assertIn('status=done', result)

    def test_uncertain_target_escalates_only_the_retry(self):
        observations = [{'state': 'act', 'input': self.data}, {'state': 'act', 'input': self.data}, {'state': 'done', 'reason': 'result visible'}]
        with patch.object(task, '_observe', side_effect=observations) as observe, patch.object(task, '_execute_step', side_effect=['status=failed reobserve=true escalate=true', 'status=unverified']), patch.object(task._STOP, 'wait', return_value=False):
            result = task.screen_task({'goal': 'Search', 'max_steps': 3})
        self.assertEqual([call.args[2] for call in observe.call_args_list], [False, True, False])
        self.assertIn('status=done', result)

    def test_native_control_overrides_estimated_box(self):
        with patch.object(screen_target, 'foreground_id', return_value=None), patch.object(screen_target, 'accessible_target', return_value=(120, 50)), patch.object(control, 'computer_control', return_value='status=unverified') as execute:
            task._execute_step(self.data, self.frame, None)
        self.assertEqual(execute.call_args.args[0]['x'], 120)

    def test_keyboard_is_not_sent_if_window_changed(self):
        with patch.object(screen_target, 'foreground_id', return_value=22), patch.object(control, 'computer_control') as execute:
            result = task._execute_step({'action': 'press', 'key': 'enter'}, {'window': 11}, None)
        execute.assert_not_called()
        self.assertIn('status=failed', result)

    def test_uncertain_grounding_never_inputs(self):
        with patch.object(screen_target, 'foreground_id', return_value=None), patch.object(screen_target, 'accessible_target', return_value=None), patch.object(control, 'computer_control') as execute:
            result = task._execute_step({**self.data, 'confidence': .4}, self.frame, None)
        execute.assert_not_called()
        self.assertIn('status=failed', result)

    def test_changed_target_region_is_rejected(self):
        before = Image.new('RGB', (200, 100), 'white')
        after = Image.new('RGB', (200, 100), 'black')
        self.assertFalse(screen_target.target_unchanged(before, after, [0, 0, 1000, 1000]))
        self.assertTrue(screen_target.target_unchanged(before, before, [0, 0, 1000, 1000]))
        with patch.object(screen_target, 'foreground_id', return_value=None), patch.object(screen_target, 'accessible_target', return_value=None), patch.object(control, 'pyautogui', MagicMock()) as gui, patch.object(control, 'computer_control') as execute:
            gui.screenshot.return_value = after
            result = task._execute_step(self.data, {**self.frame, 'image': before}, None)
        execute.assert_not_called()
        self.assertIn('status=failed', result)


if __name__ == '__main__':
    unittest.main()

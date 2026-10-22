import threading
import unittest
from unittest.mock import patch, MagicMock

from actions import screen_task as task
from actions import computer_control as control
from core.screen_target import box_center
from core import screen_target


class TargetTests(unittest.TestCase):
    def test_normalized_box_maps_to_screen_center(self):
        self.assertEqual(box_center({'found': True, 'confidence': .95, 'box_2d': [200, 100, 400, 300]}, 1920, 1080), (384, 324))

    def test_uncertain_malformed_and_pixel_boxes_rejected(self):
        for box in ([0, 0, 1080, 1920], [100, 200, 50, 300], [0, 0, 0, 10], [0, 0, float('nan'), 100], [True, 0, 50, 100]):
            self.assertIsNone(box_center({'found': True, 'confidence': .99, 'box_2d': box}, 1920, 1080))
        self.assertIsNone(box_center({'found': True, 'confidence': .5, 'box_2d': [0, 0, 50, 100]}, 1920, 1080))
        self.assertIsNone(box_center({'found': False}, 1920, 1080))

    def test_accessibility_uses_unique_visible_control(self):
        control = MagicMock()
        control.window_text.return_value = 'Salvar'
        rectangle = MagicMock(left=100, right=200, top=20, bottom=60)
        rectangle.width.return_value = 100
        rectangle.height.return_value = 40
        control.rectangle.return_value = rectangle
        desktop = MagicMock()
        desktop.window.return_value.descendants.return_value = [control]
        import types
        with patch.object(screen_target.platform, 'system', return_value='Windows'), patch.object(screen_target, 'foreground_id', return_value=42), patch.dict('sys.modules', {'pywinauto': types.SimpleNamespace(Desktop=lambda **kwargs: desktop)}):
            self.assertEqual(screen_target.accessible_target('botão Salvar', 1920, 1080), (150, 40))
            desktop.window.return_value.descendants.return_value = [control, control]
            self.assertIsNone(screen_target.accessible_target('Salvar', 1920, 1080))


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.sleep = patch.object(task._STOP, 'wait', return_value=False)
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def test_observes_after_each_input_and_only_then_reports_done(self):
        observations = [
            {'state': 'act', 'input': {'action': 'click', 'description': 'Search'}},
            {'state': 'act', 'input': {'action': 'type', 'description': 'Search field', 'text': 'café'}},
            {'state': 'done', 'reason': 'café visible in the field'}]
        events = []
        def observe(*args):
            events.append('observe')
            return observations.pop(0)
        def execute(*args, **kwargs):
            events.append('input')
            return 'status=unverified'
        with patch.object(task, '_observe', side_effect=observe), patch.object(control, 'computer_control', side_effect=execute):
            result = task.screen_task({'goal': 'Fill search field', 'max_steps': 3})
        self.assertIn('status=done', result)
        self.assertEqual(events, ['observe', 'input', 'observe', 'input', 'observe'])

    def test_stop_during_model_request_prevents_input(self):
        def observe(*args):
            task.cancel()
            return {'state': 'act', 'input': {'action': 'click', 'description': 'Send'}}
        with patch.object(task, '_observe', side_effect=observe), patch.object(control, 'computer_control') as execute:
            result = task.screen_task({'goal': 'Open page'})
        execute.assert_not_called()
        self.assertIn('interrompida', result)

    def test_stop_during_target_lookup_prevents_click(self):
        stop = threading.Event()
        def find(*args):
            stop.set()
            return (100, 100)
        with patch.object(control, '_screen_find', side_effect=find), patch.object(control, 'pyautogui', MagicMock()) as gui:
            result = control.computer_control({'action': 'click', 'description': 'Button'}, cancel_event=stop)
        gui.click.assert_not_called()
        self.assertIn('status=failed', result)

    def test_failure_stops_sequence(self):
        with patch.object(task, '_observe', return_value={'state': 'act', 'input': {'action': 'click', 'description': 'Search'}}) as observe, patch.object(control, 'computer_control', return_value='status=failed') as execute:
            result = task.screen_task({'goal': 'Search'})
        self.assertEqual(observe.call_count, 1)
        self.assertEqual(execute.call_count, 1)
        self.assertIn('status=failed', result)

    def test_repeated_action_is_not_executed_twice(self):
        with patch.object(task, '_observe', return_value={'state': 'act', 'input': {'action': 'click', 'description': 'Search'}}), patch.object(control, 'computer_control', return_value='status=unverified') as execute:
            result = task.screen_task({'goal': 'Search'})
        execute.assert_called_once()
        self.assertIn('status=unverified', result)

    def test_step_limit_has_a_final_observation(self):
        observations = [
            {'state': 'act', 'input': {'action': 'click', 'description': 'Search'}},
            {'state': 'act', 'input': {'action': 'click', 'description': 'Other'}}]
        with patch.object(task, '_observe', side_effect=observations) as observe, patch.object(control, 'computer_control', return_value='status=unverified') as execute:
            result = task.screen_task({'goal': 'Search', 'max_steps': 1})
        self.assertEqual(observe.call_count, 2)
        execute.assert_called_once()
        self.assertIn('Limite', result)

    def test_no_coordinate_only_click_or_shell_action(self):
        for data in ({'action': 'click', 'x': 100, 'y': 200}, {'action': 'shell', 'text': 'command'}):
            with self.assertRaises(ValueError):
                task._validate_input(data)

    def test_tool_schema_is_valid(self):
        from google.genai import types
        types.FunctionDeclaration(**{k: v for k, v in task.TOOL.items() if k in ('name', 'description', 'parameters')})


if __name__ == '__main__':
    unittest.main()

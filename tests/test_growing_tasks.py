import unittest
from unittest.mock import patch
from PIL import Image
from actions import screen_task as task
from core.task_progress import ProgressWatch
from core import automation_view


class GrowingTaskTests(unittest.TestCase):
    def setUp(self):
        automation_view.install(None)
        self.wait = patch.object(task._STOP, 'wait', return_value=False)
        self.wait.start()
        self.addCleanup(self.wait.stop)

    def test_task_can_exceed_old_step_and_time_limits(self):
        observations = [{'state': 'act', 'input': {'action': 'click', 'description': f'Control {i}'}, '_frame': {'image': Image.new('RGB', (64, 36), (i * 7 % 255,) * 3)}} for i in range(70)] + [{'state': 'done', 'reason': 'Goal complete'}]
        clock = [0]
        def observe(*args, **kwargs):
            clock[0] += 20
            return observations.pop(0)
        with patch.object(task, '_observe', side_effect=observe), patch.object(task, '_execute_step', return_value='status=unverified') as execute, patch.object(task.time, 'monotonic', side_effect=lambda: clock[0]):
            result = task.screen_task({'goal': 'Complete requested long sequence'})
        self.assertIn('status=done', result)
        self.assertIn('steps=70', result)
        self.assertEqual(execute.call_count, 70)
        self.assertGreater(clock[0], 300)

    def test_repeated_unchanged_screen_stops_without_infinite_scroll(self):
        frame = {'image': Image.new('RGB', (100, 100), 'white')}
        observation = {'state': 'act', 'input': {'action': 'scroll', 'direction': 'down'}, '_frame': frame}
        with patch.object(task, '_observe', return_value=observation), patch.object(task, '_execute_step', return_value='status=unverified') as execute:
            result = task.screen_task({'goal': 'Find requested item'})
        self.assertIn('code=no_progress', result)
        self.assertEqual(execute.call_count, 10)

    def test_checkpoint_retains_completed_phase_for_next_observation(self):
        observations = [{'state': 'act', 'checkpoint': 'The requested tab is open.', 'input': {'action': 'click', 'description': 'Open tab'}}, {'state': 'done'}]
        with patch.object(task, '_observe', side_effect=observations) as observe, patch.object(task, '_execute_step', return_value='status=unverified'):
            result = task.screen_task({'goal': 'Open requested tab'})
        self.assertIn('status=done', result)
        self.assertEqual(observe.call_args.kwargs['checkpoint'], 'The requested tab is open.')

    def test_monitor_failure_prevents_inputs(self):
        with patch.object(task, '_observe') as observe, patch('core.automation_view.notify', return_value=False), patch.object(task, '_execute_step') as execute:
            result = task.screen_task({'goal': 'Open requested tab'})
        self.assertIn('status=failed', result)
        observe.assert_not_called()
        execute.assert_not_called()

    def test_bridge_hides_monitor_before_input_and_restores_after(self):
        calls = []
        def handler(action, payload):
            calls.append((action, payload['hidden']))
            payload['_ok'] = True
            payload['_ack'].set()
        automation_view.install(handler)
        try:
            with automation_view.unobstructed():
                self.assertEqual(calls, [('occlude', True)])
            self.assertEqual(calls, [('occlude', True), ('occlude', False)])
        finally:
            automation_view.install(None)

    def test_nested_inputs_do_not_restore_panel_before_outer_input_finishes(self):
        calls = []
        def handler(action, payload):
            calls.append(payload['hidden'])
            payload['_ok'] = True
            payload['_ack'].set()
        automation_view.install(handler)
        try:
            with automation_view.unobstructed():
                with automation_view.unobstructed():
                    self.assertEqual(calls, [True])
                self.assertEqual(calls, [True])
            self.assertEqual(calls, [True, False])
        finally:
            automation_view.install(None)

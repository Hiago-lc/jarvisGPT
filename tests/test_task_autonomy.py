import unittest
from unittest.mock import patch
from actions import screen_task as task
from core.gemini import VisualCallError


def click(description, **extra):
    return {'state': 'act', 'input': {'action': 'click', 'description': description, **extra}}


class AutonomyTests(unittest.TestCase):
    def setUp(self):
        self.wait = patch.object(task._STOP, 'wait', return_value=False)
        self.wait.start()
        self.addCleanup(self.wait.stop)

    def test_hidden_control_is_replanned_without_asking_user_to_click(self):
        observations = [{'state': 'blocked', 'blocker': 'recoverable', 'reason': 'Control hidden'}, click('Visible overflow menu'), click('Requested control in expanded menu'), {'state': 'done', 'reason': 'Requested result visible'}]
        with patch.object(task, '_observe', side_effect=observations) as observe, patch.object(task, '_execute_step', return_value='status=unverified') as execute:
            result = task.screen_task({'goal': 'Open the requested control'})
        self.assertIn('status=done', result)
        self.assertEqual(execute.call_count, 2)
        self.assertTrue(observe.call_args_list[1].args[2])
        self.assertEqual(observe.call_args_list[1].kwargs['recovery'][0]['kind'], 'blocked')

    def test_changed_box_does_not_replay_same_click_and_can_continue(self):
        observations = [click('Open menu', box_2d=[0, 0, 100, 100], confidence=.9), click('Open menu', box_2d=[0, 0, 110, 110], confidence=.99), click('Menu option'), {'state': 'done'}]
        with patch.object(task, '_observe', side_effect=observations), patch.object(task, '_execute_step', return_value='status=unverified') as execute:
            result = task.screen_task({'goal': 'Select menu option'})
        self.assertIn('status=done', result)
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(execute.call_args_list[1].args[0]['description'], 'Menu option')

    def test_authentication_and_missing_details_stop_before_input(self):
        for blocker in ('authentication', 'permission', 'missing_information', 'ambiguous_target'):
            with self.subTest(blocker=blocker), patch.object(task, '_observe', return_value={'state': 'blocked', 'blocker': blocker, 'reason': 'Required user information'}) as observe, patch.object(task, '_execute_step') as execute:
                result = task.screen_task({'goal': 'Complete requested task'})
                self.assertIn('status=ask', result)
                self.assertIn('code=' + blocker, result)
                observe.assert_called_once()
                execute.assert_not_called()

    def test_transient_visual_error_retries_without_input_or_duplicate(self):
        with patch.object(task, '_observe', side_effect=[VisualCallError('timeout', 'timeout'), click('Target'), {'state': 'done'}]) as observe, patch.object(task, '_execute_step', return_value='status=unverified') as execute:
            result = task.screen_task({'goal': 'Open target'})
        self.assertIn('status=done', result)
        self.assertEqual(execute.call_count, 1)
        self.assertTrue(observe.call_args_list[1].args[2])

    def test_quota_error_is_not_retried(self):
        with patch.object(task, '_observe', side_effect=VisualCallError('quota', 'quota')) as observe, patch.object(task, '_execute_step') as execute:
            result = task.screen_task({'goal': 'Open target'})
        self.assertIn('code=quota', result)
        observe.assert_called_once()
        execute.assert_not_called()

    def test_recovery_budget_is_bounded_without_requesting_manual_click(self):
        with patch.object(task, '_observe', return_value={'state': 'blocked', 'blocker': 'recoverable', 'reason': 'Target hidden'}) as observe, patch.object(task, '_execute_step') as execute:
            result = task.screen_task({'goal': 'Open target'})
        self.assertIn('status=failed', result)
        self.assertIn('code=recovery_exhausted', result)
        self.assertEqual(observe.call_count, 3)
        execute.assert_not_called()

    def test_continues_past_old_eight_step_limit(self):
        observations = [click(f'Step {index}') for index in range(10)] + [{'state': 'done'}]
        with patch.object(task, '_observe', side_effect=observations), patch.object(task, '_execute_step', return_value='status=unverified') as execute:
            result = task.screen_task({'goal': 'Complete ten requested navigation steps'})
        self.assertIn('status=done', result)
        self.assertEqual(execute.call_count, 10)

    def test_cancel_during_recovery_prevents_input(self):
        def observe(*args, **kwargs):
            if kwargs.get('recovery'):
                task.cancel()
                return click('Target')
            return {'state': 'blocked', 'blocker': 'recoverable', 'reason': 'Loading'}
        with patch.object(task, '_observe', side_effect=observe), patch.object(task, '_execute_step') as execute:
            result = task.screen_task({'goal': 'Open target'})
        self.assertIn('interrompida', result)
        execute.assert_not_called()

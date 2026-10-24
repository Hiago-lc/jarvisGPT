import threading
import types
import unittest
from unittest.mock import MagicMock, patch
from actions import screen_task as task
from actions import computer_control as control
from core import gemini, screen_target


class VisualLatencyTests(unittest.TestCase):
    def test_visual_calls_skip_live_and_share_a_total_timeout(self):
        clock = [0.0]
        limits = []
        clients = []
        def build(timeout_ms, key, strict_timeout=False):
            limits.append(timeout_ms)
            self.assertTrue(strict_timeout)
            client = MagicMock()
            clients.append(client)
            def generate(**kwargs):
                clock[0] += timeout_ms / 1000
                if len(clients) == 1:
                    raise TimeoutError()
                return types.SimpleNamespace(text='{}')
            client.models.generate_content.side_effect = generate
            return client
        with patch.object(gemini, 'api_key', return_value='test'), patch.object(gemini, '_provider_rungs', return_value=()), patch.object(gemini, '_cooling', return_value=False), patch.object(gemini.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(gemini, 'client', side_effect=build), patch.object(gemini, '_live_call') as live, patch.object(gemini, '_cool') as cool:
            result = gemini.call('locate', tier=gemini.VISUAL_FAST, timeout_ms=24000)
        self.assertEqual(result.text, '{}')
        self.assertEqual(limits, [12000, 12000])
        self.assertEqual(clock[0], 24)
        live.assert_not_called()
        cool.assert_called_once()
        for client in clients:
            client.close.assert_called_once()

    def test_all_cooled_visual_models_do_not_force_retries(self):
        with patch.object(gemini, 'api_key', return_value='test'), patch.object(gemini, '_provider_rungs', return_value=()), patch.object(gemini, '_cooling', return_value=True), patch.object(gemini, 'client') as client:
            with self.assertRaises(gemini.VisualCallError) as result:
                gemini.call('locate', tier=gemini.VISUAL_FAST)
            self.assertEqual(result.exception.code, 'cooldown')
        client.assert_not_called()

    def test_visual_sdk_deadline_is_not_raised_to_ten_seconds(self):
        with patch('google.genai.Client') as client:
            gemini.client(timeout_ms=1500, key='test', strict_timeout=True)
        options = client.call_args.kwargs['http_options']
        self.assertEqual(options.timeout, 1500)
        self.assertEqual(options.retry_options.attempts, 1)


class MessageEditingTests(unittest.TestCase):
    def setUp(self):
        task._STOP.clear()

    def test_field_clear_is_a_visual_action_not_a_message_deletion(self):
        data = task._validate_input({'action': 'clear_field', 'description': 'Message composer', 'box_2d': [400, 400, 600, 600], 'confidence': .95})
        with patch.object(screen_target, 'foreground_id', return_value=None), patch.object(screen_target, 'accessible_target', return_value=(200, 200)), patch.object(control, 'computer_control', return_value='status=unverified') as execute:
            task._execute_step(data, {'window': None, 'size': (1920, 1080)}, None)
        self.assertEqual(execute.call_args_list[0].args[0], {'action': 'click', 'x': 200, 'y': 200})
        self.assertEqual(execute.call_args_list[1].args[0], {'action': 'clear_field'})

    def test_hover_reveals_a_menu_without_clicking(self):
        data = task._validate_input({'action': 'hover', 'description': 'Exact message bubble', 'box_2d': [400, 400, 600, 600], 'confidence': .95})
        with patch.object(screen_target, 'foreground_id', return_value=None), patch.object(screen_target, 'accessible_target', return_value=(200, 200)), patch.object(control, 'computer_control', return_value='status=unverified') as execute:
            task._execute_step(data, {'window': None, 'size': (1920, 1080)}, None)
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[0]['action'], 'move')

    def test_replacement_and_clear_require_a_field(self):
        for action in ('clear_field', 'replace_text'):
            with self.assertRaises(ValueError):
                task._validate_input({'action': action, 'text': 'new'})
        self.assertEqual(task._validate_input({'action': 'replace_text', 'description': 'Composer', 'text': 'new'})['text'], 'new')

    def test_key_aliases_are_normalized_and_unknown_keys_fail(self):
        with patch.object(control, 'pyautogui', MagicMock()) as gui, patch.object(control, '_require_pyautogui'):
            control._hotkey('Control', 'A')
            gui.hotkey.assert_called_once_with('ctrl', 'a')
            control._press('DEL', 3)
            gui.press.assert_called_once_with('delete', presses=3, interval=0.015)
            with self.assertRaises(ValueError):
                control._press('not_a_key')

    def test_missing_key_never_defaults_to_enter(self):
        with self.assertRaises(ValueError):
            task._validate_input({'action': 'press'})
        with patch.object(control, 'pyautogui', MagicMock()) as gui, patch.object(control, '_require_pyautogui'):
            result = control.computer_control({'action': 'press'})
        gui.press.assert_not_called()
        self.assertIn('status=failed', result)

    def test_clearing_a_field_uses_backspace_after_select_all(self):
        with patch.object(control, 'pyautogui', MagicMock()) as gui, patch.object(control, '_require_pyautogui'), patch.object(control, '_get_os', return_value='windows'), patch.object(control.time, 'sleep'):
            control._clear_field()
        gui.hotkey.assert_called_once_with('ctrl', 'a')
        gui.press.assert_called_once_with('backspace')

    def test_sent_deletion_missing_scope_asks_without_action(self):
        with patch.object(task, '_observe') as observe:
            result = task.screen_task({'action': 'run', 'goal': 'delete message', 'delete_recipient': 'Vitor', 'delete_message_text': 'Test'})
        observe.assert_not_called()
        self.assertIn('status=ask', result)
        self.assertIn('para mim ou para todos', result)

    def test_explicit_deletion_passes_exact_target_and_scope(self):
        with patch.object(task, '_observe', return_value={'state': 'blocked', 'reason': 'Target not visible'}) as observe:
            result = task.screen_task({'action': 'run', 'goal': 'Delete Test from Vitor for me', 'delete_recipient': 'Vitor', 'delete_message_text': 'Test', 'delete_scope': 'for_me'})
        request = observe.call_args.args[3]
        self.assertEqual(request['delete_scope'], 'for_me')
        self.assertEqual(request['delete_message_text'], 'Test')
        self.assertIn('status=ask', result)

    def test_busy_accessibility_probe_immediately_falls_back(self):
        with patch.object(screen_target.platform, 'system', return_value='Windows'), patch.object(screen_target, '_accessible_target') as inspect:
            screen_target._PROBE_LOCK.acquire()
            try:
                self.assertIsNone(screen_target.accessible_target('Button', 1920, 1080))
            finally:
                screen_target._PROBE_LOCK.release()
        inspect.assert_not_called()

    def test_schema_remains_accepted_by_gemini(self):
        from google.genai import types
        types.FunctionDeclaration(**{k: v for k, v in task.TOOL.items() if k in ('name', 'description', 'parameters')})


if __name__ == '__main__':
    unittest.main()

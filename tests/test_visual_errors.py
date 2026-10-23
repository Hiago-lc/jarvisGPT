import types
import unittest
from unittest.mock import MagicMock, patch
from core import gemini
from actions import screen_task


class VisualErrorTests(unittest.TestCase):
    def test_quota_has_its_own_code_and_no_screen_actions(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError('429 RESOURCE_EXHAUSTED')
        with patch.object(gemini, 'api_key', return_value='test'), patch.object(gemini, '_provider_rungs', return_value=()), patch.object(gemini, '_cooling', return_value=False), patch.object(gemini, '_cool'), patch.object(gemini, 'client', return_value=client):
            with self.assertRaises(gemini.VisualCallError) as error:
                gemini.call('screen', tier=gemini.VISUAL_FAST)
        self.assertEqual(error.exception.code, 'quota')
        self.assertIn('cota separada', str(error.exception))

    def test_malformed_json_is_not_reported_as_timeout(self):
        with patch.object(gemini, 'text', return_value='not JSON'):
            with self.assertRaises(gemini.VisualCallError) as error:
                gemini.as_json('screen', tier=gemini.VISUAL_FAST)
        self.assertEqual(error.exception.code, 'invalid_json')

    def test_visual_config_requests_json_without_thinking_delay(self):
        client = MagicMock()
        client.models.generate_content.return_value = types.SimpleNamespace(text='{}')
        with patch.object(gemini, 'api_key', return_value='test'), patch.object(gemini, '_provider_rungs', return_value=()), patch.object(gemini, '_cooling', return_value=False), patch.object(gemini, 'client', return_value=client):
            gemini.call('screen', tier=gemini.VISUAL_FAST)
        options = client.models.generate_content.call_args.kwargs['config']
        self.assertEqual(options.response_mime_type, 'application/json')
        self.assertEqual(options.thinking_config.thinking_budget, 0)

    def test_screen_task_preserves_specific_error_and_zero_steps(self):
        with patch.object(screen_task, '_observe', side_effect=gemini.VisualCallError('timeout', 'Modelo excedeu o prazo')), patch.object(screen_task, '_execute_step') as execute:
            result = screen_task.screen_task({'goal': 'find contact'})
        self.assertIn('code=timeout', result)
        self.assertIn('steps=0', result)
        execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()

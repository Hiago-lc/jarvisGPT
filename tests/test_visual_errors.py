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


class VisualDeadlineTests(unittest.TestCase):
    def run_call(self, errors=None, timeout=12000):
        client = MagicMock()
        if errors:
            client.models.generate_content.side_effect = errors
        with patch.object(gemini, 'api_key', return_value='test'), patch.object(gemini, '_provider_rungs', return_value=()), patch.object(gemini, '_cooling', return_value=False), patch.object(gemini, '_cool'), patch.object(gemini.time, 'monotonic', return_value=100), patch.object(gemini, 'client', return_value=client) as factory:
            try:
                gemini.call('image', tier=gemini.VISUAL_FAST, timeout_ms=timeout)
                error = None
            except gemini.VisualCallError as caught:
                error = caught
        return factory, client, error

    def test_request_has_at_least_service_minimum(self):
        factory, _, error = self.run_call()
        self.assertIsNone(error)
        self.assertGreaterEqual(factory.call_args.kwargs['timeout_ms'], 10000)
        self.assertLessEqual(factory.call_args.kwargs['timeout_ms'], 12000)

    def test_insufficient_budget_sends_no_invalid_request(self):
        factory, client, error = self.run_call(timeout=9000)
        factory.assert_not_called()
        client.models.generate_content.assert_not_called()
        self.assertEqual(error.code, 'timeout')

    def test_deadline_rejection_is_not_masked_as_missing_fallback(self):
        factory, client, error = self.run_call(errors=RuntimeError('400 Manually set deadline 6s is too short. Minimum allowed deadline is 10s.'))
        self.assertEqual(error.code, 'request_deadline')
        self.assertEqual(client.models.generate_content.call_count, 1)

    def test_missing_fallback_does_not_hide_primary_network_failure(self):
        _, _, error = self.run_call(errors=[RuntimeError('connection reset'), RuntimeError('404 model not found')])
        self.assertEqual(error.code, 'network_or_service')

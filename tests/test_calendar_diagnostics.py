import json
import os
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch
from core import google_calendar
from core.google_calendar_errors import diagnose, CalendarSetupError
from actions.google_agenda import google_agenda


def google_error(status, reason, details=False):
    error = Exception('raw-private-value')
    error.resp = types.SimpleNamespace(status=status)
    key = 'details' if details else 'errors'
    error.content = json.dumps({'error': {'message': 'raw-private-value', key: [{'reason': reason, 'metadata': {'private': 'raw-private-value'}}]}}).encode()
    return error


class DiagnosticTests(unittest.TestCase):
    def test_google_reasons_get_distinct_safe_instructions(self):
        for status, reason, expected in ((403, 'accessNotConfigured', 'api_disabled'), (403, 'SERVICE_DISABLED', 'api_disabled'),
                                         (403, 'insufficientPermissions', 'scope_missing'), (403, 'ACCESS_TOKEN_SCOPE_INSUFFICIENT', 'scope_missing'),
                                         (403, 'userRateLimitExceeded', 'quota_limit'), (403, 'domainPolicy', 'workspace_policy'),
                                         (401, '', 'unauthorized'), (403, 'forbidden', 'permission_denied')):
            code, message = diagnose(google_error(status, reason, details=reason.isupper()))
            self.assertEqual(code, expected)
            self.assertNotIn('raw-private-value', message)

    def test_full_action_logs_safe_cause_instead_of_truncating(self):
        player = MagicMock()
        with patch.object(google_calendar, 'service', side_effect=google_error(403, 'accessNotConfigured')):
            result = google_agenda({'action': 'list'}, player=player)
        self.assertIn('code=api_disabled', result)
        self.assertIn('Google Calendar API', player.write_log.call_args.args[0])
        self.assertNotIn('raw-private-value', result)

    def test_diagnostic_is_read_only_and_requests_no_event_fields(self):
        service = MagicMock()
        with patch.object(google_calendar, 'service', return_value=service):
            ok, code, message = google_calendar.check_connection()
        self.assertTrue(ok)
        self.assertEqual(code, 'read_ok')
        self.assertEqual(service.events.return_value.list.call_args.kwargs['fields'], 'kind')
        service.events.return_value.insert.assert_not_called()
        self.assertIn('não confirma permissão de escrita', message)

    def test_invalid_grant_gives_reconnect_instruction_without_server_response(self):
        from google.auth.exceptions import RefreshError
        credentials = MagicMock(expired=True, refresh_token=True)
        credentials.refresh.side_effect = RefreshError('raw-private-value')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'JARVIS_DATA_DIR': folder}):
            path = google_calendar.token_path()
            path.parent.mkdir(parents=True)
            path.write_text('{}')
            with patch('google.oauth2.credentials.Credentials.from_authorized_user_file', return_value=credentials):
                with self.assertRaises(CalendarSetupError) as result:
                    google_calendar.service()
        self.assertIn('connect_google_calendar.py', str(result.exception))
        self.assertNotIn('raw-private-value', str(result.exception))

    def test_rejected_scope_preserves_existing_token(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'JARVIS_DATA_DIR': folder}), patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file') as factory:
            path = google_calendar.token_path()
            path.parent.mkdir(parents=True)
            path.write_text('{"token":"old-test-token"}')
            credentials = MagicMock(granted_scopes=['unrelated-scope'])
            factory.return_value.run_local_server.return_value = credentials
            with self.assertRaises(CalendarSetupError):
                google_calendar.connect('client.json')
            self.assertEqual(path.read_text(), '{"token":"old-test-token"}')
            self.assertEqual(factory.return_value.run_local_server.call_args.kwargs['prompt'], 'consent')

    def test_arbitrary_runtime_errors_are_not_displayed(self):
        with patch.object(google_calendar, 'service', side_effect=RuntimeError('raw-private-value')):
            ok, code, message = google_calendar.check_connection()
        self.assertFalse(ok)
        self.assertNotIn('raw-private-value', message)


if __name__ == '__main__':
    unittest.main()

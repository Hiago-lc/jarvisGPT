import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from core import gemini
from check_gemini_visual import configure


class VisualConfigurationTests(unittest.TestCase):
    def test_saved_model_is_tried_before_unavailable_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'api_keys.json'
            path.write_text(json.dumps({'gemini_visual_model': 'gemini-flash-latest'}))
            client = MagicMock()
            with patch.object(gemini, '_KEY_FILE', path), patch.object(gemini, 'api_key', return_value='test'), patch.object(gemini, '_provider_rungs', return_value=()), patch.object(gemini, '_cooling', return_value=False), patch.object(gemini, 'client', return_value=client):
                gemini.call('image', tier=gemini.VISUAL_FAST)
            self.assertEqual(client.models.generate_content.call_args.kwargs['model'], 'gemini-flash-latest')

    def test_configure_requires_image_answer_and_preserves_key(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'api_keys.json'
            original = {'gemini_api_key': 'private-test', 'os_system': 'windows'}
            path.write_text(json.dumps(original))
            client = MagicMock()
            client.models.list.return_value = [types.SimpleNamespace(name='models/gemini-test-flash', supported_actions=['generateContent'])]
            client.models.generate_content.return_value = types.SimpleNamespace(text='{"color":"red"}')
            with patch.object(gemini, '_KEY_FILE', path), patch.object(gemini, 'api_key', return_value='test'), patch.object(gemini, 'client', return_value=client):
                self.assertEqual(configure(save=True), 0)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['gemini_api_key'], original['gemini_api_key'])
            self.assertEqual(saved['gemini_visual_model'], 'gemini-test-flash')
            client.close.assert_called_once()

    def test_failed_probe_does_not_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'api_keys.json'
            path.write_text('{"gemini_api_key":"test"}')
            before = path.read_bytes()
            client = MagicMock()
            client.models.list.return_value = [types.SimpleNamespace(name='models/gemini-test-flash', supported_actions=['generateContent'])]
            client.models.generate_content.side_effect = RuntimeError('not available')
            with patch.object(gemini, '_KEY_FILE', path), patch.object(gemini, 'api_key', return_value='test'), patch.object(gemini, 'client', return_value=client):
                self.assertEqual(configure(save=True), 1)
            self.assertEqual(before, path.read_bytes())

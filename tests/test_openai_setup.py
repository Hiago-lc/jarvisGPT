import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from memory import config_manager as cm
from memory.chatgpt_history import import_history, search
from start_openai import configure


class OpenAISetupTests(unittest.TestCase):
    def test_config_preserves_settings_and_never_writes_environment_key(self):
        original_loader = cm.load_api_keys
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'api_keys.json'
            path.write_text(json.dumps({'user_name': 'Hiago', 'gemini_api_key': 'old-key'}))
            with patch.object(cm, 'CONFIG_DIR', Path(folder)), patch.object(cm, 'CONFIG_FILE', path), patch.dict(os.environ, {'OPENAI_API_KEY': 'test-secret'}, clear=False):
                try:
                    configure()
                    saved = json.loads(path.read_text())
                    self.assertEqual(saved['user_name'], 'Hiago')
                    self.assertEqual(saved['gemini_api_key'], 'old-key')
                    self.assertNotIn('test-secret', path.read_text())
                    self.assertEqual(cm.get_provider_config('openai_compat')['api_key'], 'test-secret')
                    self.assertEqual(cm.get_pipeline()['stt'], 'whisper')
                    self.assertEqual(cm.get_provider_mode(), 'pipeline')
                    self.assertEqual(cm.get_sidecar_provider(), 'openai_compat')
                finally:
                    cm.load_api_keys = original_loader
        os.environ.pop('JARVIS_OPENAI_ONLY', None)

    def test_missing_key_fails_before_writing(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            with self.assertRaises(SystemExit):
                configure()

    def test_auxiliary_calls_never_fall_back_to_gemini(self):
        from core import gemini
        rung = gemini.PROVIDER_PREFIX + 'openai_compat'
        with patch.dict(os.environ, {'JARVIS_OPENAI_ONLY': '1'}), \
             patch.object(gemini, '_provider_rungs', return_value=(rung,)), \
             patch.object(gemini, '_provider_call', side_effect=RuntimeError('offline')), \
             patch.object(gemini, 'client') as google_client, \
             patch.object(gemini, '_live_call') as live:
            self.assertIsNone(gemini.call('test', key='old-gemini-key'))
            google_client.assert_not_called()
            live.assert_not_called()

    def test_history_reimport_and_search(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'conversations.json'
            database = Path(folder) / 'history.db'
            source.write_text(json.dumps([{'id': 'abc', 'title': 'Projeto Jarvis', 'mapping': {
                '1': {'message': {'author': {'role': 'user'}, 'content': {'parts': ['Quero usar GPT no meu assistente.']}}},
                '2': {'message': {'author': {'role': 'system'}, 'content': {'parts': ['system ignored']}}},
            }}]))
            self.assertEqual(import_history(source, database), 1)
            self.assertEqual(import_history(source, database), 1)
            with sqlite3.connect(database) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM messages').fetchone()[0], 1)
            self.assertIn('Quero usar GPT', search('assistente', database))
            self.assertIn('Nenhum trecho', search('inexistente', database))
            self.assertNotIn('system ignored', search('Jarvis', database))


if __name__ == '__main__':
    unittest.main()

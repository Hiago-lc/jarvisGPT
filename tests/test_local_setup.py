import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from memory import config_manager as cm
import start_local


def _run(perfil, env, data=None):
    """Runs start_local.configure against a temporary settings file and
    returns (saved json, provider config seen at runtime)."""
    original_loader = cm.load_api_keys
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'api_keys.json'
        path.write_text(json.dumps(data or {'user_name': 'Hiago', 'gemini_api_key': 'old-key'}))
        with patch.object(cm, 'CONFIG_DIR', Path(folder)), \
             patch.object(cm, 'CONFIG_FILE', path), \
             patch.dict(os.environ, env, clear=False):
            try:
                start_local.configure(perfil)
                text = path.read_text()
                runtime = {pid: cm.get_provider_config(pid) for pid in ('openai_compat', 'whisper', 'piper')}
                return json.loads(text), text, runtime, cm.get_provider_mode(), cm.get_sidecar_provider()
            finally:
                cm.load_api_keys = original_loader
                os.environ.pop('JARVIS_NO_GEMINI', None)


class LocalProfileTests(unittest.TestCase):
    def test_local_profile_points_everything_at_this_computer(self):
        saved, _, runtime, mode, sidecar = _run('local', {'JARVIS_LOCAL_MODEL': ''})
        self.assertEqual(mode, 'pipeline')
        self.assertEqual(sidecar, 'openai_compat')
        self.assertTrue(saved['providers']['sidecar_first'])
        llm = runtime['openai_compat']
        self.assertEqual(llm['base_url'], 'http://127.0.0.1:11434/v1')
        self.assertEqual(llm['model'], start_local.DEFAULT_LOCAL_MODEL)
        self.assertEqual(llm['max_tools'], '12')
        self.assertEqual(runtime['whisper']['backend'], 'local')
        self.assertEqual(runtime['whisper']['language'], 'pt')
        self.assertEqual(runtime['piper']['voice'], 'pt_BR-faber-medium')

    def test_existing_settings_survive(self):
        saved, _, _, _, _ = _run('local', {})
        self.assertEqual(saved['user_name'], 'Hiago')
        self.assertEqual(saved['gemini_api_key'], 'old-key')

    def test_hybrid_key_lives_only_in_memory(self):
        saved, text, runtime, _, _ = _run('hibrido', {'GROQ_API_KEY': 'groq-secret', 'JARVIS_GROQ_MODEL': ''})
        self.assertNotIn('groq-secret', text)
        self.assertEqual(runtime['openai_compat']['api_key'], 'groq-secret')
        self.assertEqual(runtime['whisper']['api_key'], 'groq-secret')
        self.assertEqual(runtime['openai_compat']['base_url'], start_local.GROQ_URL)
        self.assertEqual(runtime['openai_compat']['model'], start_local.DEFAULT_GROQ_MODEL)

    def test_hybrid_without_key_stops_before_writing(self):
        with patch.dict(os.environ, {'GROQ_API_KEY': ''}):
            with self.assertRaises(SystemExit):
                start_local.configure('hibrido')

    def test_switching_back_to_local_drops_a_stored_cloud_key(self):
        data = {'providers': {'creds': {'openai_compat': {'api_key': 'leftover'}}}}
        saved, _, _, _, _ = _run('local', {}, data)
        self.assertEqual(saved['providers']['creds']['openai_compat']['api_key'], '')

    def test_gemini_is_disabled_by_either_switch(self):
        from core import gemini
        with patch.dict(os.environ, {'JARVIS_NO_GEMINI': '1'}):
            self.assertTrue(gemini.gemini_disabled())
        with patch.dict(os.environ, {'JARVIS_OPENAI_ONLY': '1'}):
            self.assertTrue(gemini.gemini_disabled())
        with patch.dict(os.environ, {'JARVIS_NO_GEMINI': '', 'JARVIS_OPENAI_ONLY': ''}):
            self.assertFalse(gemini.gemini_disabled())

    def test_side_calls_never_reach_gemini_in_local_mode(self):
        from core import gemini
        rung = gemini.PROVIDER_PREFIX + 'openai_compat'
        with patch.dict(os.environ, {'JARVIS_NO_GEMINI': '1'}), \
             patch.object(gemini, '_provider_rungs', return_value=(rung,)), \
             patch.object(gemini, '_provider_call', side_effect=RuntimeError('offline')), \
             patch.object(gemini, 'client') as google_client, \
             patch.object(gemini, '_live_call') as live:
            self.assertIsNone(gemini.call('teste', key='old-gemini-key'))
            google_client.assert_not_called()
            live.assert_not_called()

    def test_check_reports_missing_ollama_in_portuguese(self):
        with patch.object(start_local, '_ollama_models', return_value=None):
            problems = start_local.verificar('local', 'qwen3:4b')
        self.assertTrue(any('Ollama' in p for p in problems))

    def test_check_names_the_pull_command_for_a_missing_model(self):
        with patch.object(start_local, '_ollama_models', return_value=['llama3.2:latest']):
            problems = start_local.verificar('local', 'qwen3:4b')
        self.assertTrue(any('ollama pull qwen3:4b' in p for p in problems))


if __name__ == '__main__':
    unittest.main()

import json
import os
import sys
import types
from pathlib import Path
import tempfile
import unittest
import unittest.mock
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
        self.assertEqual(llm['max_tools'], '10')
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


def _fake_httpx(post):
    """An httpx stand-in, so these tests need no network and no package."""
    return patch.dict(sys.modules, {'httpx': types.SimpleNamespace(post=post)})


class OllamaContextTests(unittest.TestCase):
    def test_derived_name_is_stable_and_valid(self):
        name = start_local.nome_derivado('qwen3:4b-instruct-2507-q4_K_M', 12288)
        self.assertEqual(name, 'jarvis-qwen3-4b-instruct-2507-q4_k_m-12k')

    def test_creates_derived_model_with_larger_context(self):
        class Resp:
            def raise_for_status(self):
                pass
        with patch.object(start_local, '_ollama_models', return_value=['qwen3:4b']), \
             _fake_httpx(post := unittest.mock.Mock(return_value=Resp())):
            name = start_local.preparar_ollama('qwen3:4b', 12288)
        self.assertEqual(name, 'jarvis-qwen3-4b-12k')
        body = post.call_args.kwargs['json']
        self.assertEqual(body['from'], 'qwen3:4b')
        self.assertEqual(body['parameters']['num_ctx'], 12288)

    def test_reuses_an_existing_derived_model(self):
        with patch.object(start_local, '_ollama_models', return_value=['jarvis-qwen3-4b-12k:latest']), \
             _fake_httpx(post := unittest.mock.Mock()):
            self.assertEqual(start_local.preparar_ollama('qwen3:4b', 12288), 'jarvis-qwen3-4b-12k')
        post.assert_not_called()

    def test_old_ollama_falls_back_to_the_base_model(self):
        with patch.object(start_local, '_ollama_models', return_value=['qwen3:4b']), \
             _fake_httpx(unittest.mock.Mock(side_effect=RuntimeError('404'))):
            self.assertEqual(start_local.preparar_ollama('qwen3:4b', 12288), 'qwen3:4b')

    def test_local_profile_sets_a_small_history(self):
        _, _, runtime, _, _ = _run('local', {})
        self.assertEqual(runtime['openai_compat']['history_chars'], '8000')

    def test_local_profile_waits_longer_for_the_first_word(self):
        _, _, runtime, _, _ = _run('local', {'JARVIS_TIMEOUT': ''})
        self.assertEqual(runtime['openai_compat']['timeout'], '180')

    def test_engine_takes_history_budget_from_the_model(self):
        from providers.engine_pipeline import PipelineEngine

        class FakeLLM:
            caps = {'tools': True, 'tool_format': 'openai', 'history_chars': 8000}
        self.assertEqual(PipelineEngine(FakeLLM())._history_chars, 8000)
        FakeLLM.caps = {'tools': True, 'tool_format': 'openai'}
        self.assertEqual(PipelineEngine(FakeLLM())._history_chars, 24000)


class GeminiProfileTests(unittest.TestCase):
    def test_gemini_uses_saved_key_in_memory_and_local_whisper(self):
        saved, text, runtime, mode, _ = _run('gemini', {'GEMINI_API_KEY': '', 'JARVIS_GEMINI_MODEL': ''},
                                             {'gemini_api_key': 'chave-salva'})
        self.assertEqual(runtime['openai_compat']['base_url'], start_local.GEMINI_URL)
        self.assertEqual(runtime['openai_compat']['model'], start_local.DEFAULT_GEMINI_MODEL)
        self.assertEqual(runtime['openai_compat']['api_key'], 'chave-salva')
        self.assertEqual(runtime['whisper']['backend'], 'local')
        self.assertNotIn('api_key', saved['providers']['creds']['openai_compat'])

    def test_env_key_wins(self):
        _, text, runtime, _, _ = _run('gemini', {'GEMINI_API_KEY': 'chave-env'}, {'gemini_api_key': 'velha'})
        self.assertEqual(runtime['openai_compat']['api_key'], 'chave-env')
        self.assertNotIn('chave-env', text)

    def test_local_profile_never_receives_a_cloud_key(self):
        _, _, runtime, _, _ = _run('local', {'GROQ_API_KEY': 'groq-secret'})
        self.assertEqual(runtime['openai_compat'].get('api_key', ''), '')


if __name__ == '__main__':
    unittest.main()

"""A janela de voz como Jarvis principal: inicia sozinha, nunca cai no Gemini
Live por engano, ouve melhor os nomes e abre apps da Store sem visão."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import start_local
from memory import config_manager as cm


class ModoTests(unittest.TestCase):
    def test_forced_mode_wins_over_an_unreadable_file(self):
        with patch.dict(os.environ, {"JARVIS_PROVIDER_MODE": "pipeline"}), \
             patch.object(cm, "load_api_keys", return_value={}):
            self.assertEqual(cm.get_provider_mode(), "pipeline")
        with patch.dict(os.environ, {"JARVIS_PROVIDER_MODE": ""}), \
             patch.object(cm, "load_api_keys", return_value={}):
            self.assertEqual(cm.get_provider_mode(), "gemini")

    def test_configure_writes_atomically_and_pins_pipeline(self):
        original = cm.load_api_keys
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "api_keys.json"
            arq.write_text("{}")
            env = {"JARVIS_PROVIDER_MODE": "", "JARVIS_NO_GEMINI": "", "HAIZEN_DB": str(Path(d) / "h.db")}
            with patch.object(cm, "CONFIG_DIR", Path(d)), patch.object(cm, "CONFIG_FILE", arq), \
                 patch.dict(os.environ, env), \
                 patch("core.atomic_storage.write_json", wraps=__import__("core.atomic_storage").atomic_storage.write_json) as grava:
                try:
                    start_local.configure("local")
                    grava.assert_called_once()
                    self.assertEqual(os.environ["JARVIS_PROVIDER_MODE"], "pipeline")
                    arq.write_text("{ meio arquivo")            # leitura pela metade
                    self.assertEqual(cm.get_provider_mode(), "pipeline")
                finally:
                    cm.load_api_keys = original

    def test_whisper_gets_the_vocabulary_with_client_names_only_in_memory(self):
        original = cm.load_api_keys
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "api_keys.json"
            arq.write_text("{}")
            with patch.object(cm, "CONFIG_DIR", Path(d)), patch.object(cm, "CONFIG_FILE", arq), \
                 patch.dict(os.environ, {"HAIZEN_DB": str(Path(d) / "h.db")}):
                from haizen import store
                store.salvar_cliente("Padaria Sol")
                try:
                    start_local.configure("local")
                    prompt = cm.get_provider_config("whisper")["initial_prompt"]
                    self.assertIn("WhatsApp Business", prompt)
                    self.assertIn("Padaria Sol", prompt)
                    self.assertNotIn("Padaria Sol", arq.read_text())
                finally:
                    cm.load_api_keys = original

    def test_whisper_passes_the_prompt(self):
        from providers.stt_whisper import WhisperSTT
        stt = WhisperSTT({"initial_prompt": "Jarvis, WhatsApp Business"})
        visto = {}

        class Modelo:
            def transcribe(self, samples, **kw):
                visto.update(kw)
                return iter([]), type("I", (), {"language": "pt", "language_probability": 1.0})()
        stt._model = Modelo()
        stt._transcribe_blocking([0.0])
        self.assertEqual(visto["initial_prompt"], "Jarvis, WhatsApp Business")


class InicioTests(unittest.TestCase):
    def test_startup_opens_only_the_voice_window(self):
        with tempfile.TemporaryDirectory() as d, \
             patch.object(start_local.sys, "platform", "win32"), \
             patch.object(start_local, "_pasta_inicializar", return_value=Path(d)):
            msg = start_local.iniciar_com_windows("local", True)
            cmd = (Path(d) / start_local.NOME_ATALHO).read_text(encoding="utf-8")
            self.assertIn('start_local.py" --perfil local --aguardar', cmd)
            self.assertNotIn("jarvis_web.py", cmd)
            self.assertIn("central", msg)
            start_local.iniciar_com_windows("local", False)
            self.assertFalse((Path(d) / start_local.NOME_ATALHO).exists())

    def test_same_shortcut_name_as_the_web_one_so_it_replaces_it(self):
        import jarvis_web
        self.assertEqual(start_local.NOME_ATALHO, jarvis_web.NOME_ATALHO)


class AppsDaLojaTests(unittest.TestCase):
    APPS = [{"Name": "WhatsApp", "AppID": "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"},
            {"Name": "WhatsApp Business", "AppID": "5319275A.51895FA4EA97F_cv1g1gvanyjgm!App"},
            {"Name": "Spotify", "AppID": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"},
            {"Name": "Configurações", "AppID": "windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel"}]

    def test_exact_and_partial_names(self):
        from core.app_reopen import escolher_start_app
        self.assertEqual(escolher_start_app("whatsapp business", self.APPS)["Name"], "WhatsApp Business")
        self.assertEqual(escolher_start_app("WhatsApp", self.APPS)["Name"], "WhatsApp")
        self.assertEqual(escolher_start_app("configuracoes", self.APPS)["Name"], "Configurações")
        self.assertIsNone(escolher_start_app("what", self.APPS))         # pedaço de palavra: não
        self.assertIsNone(escolher_start_app("SAP Business", self.APPS))

    def test_running_store_app_is_raised_without_vision(self):
        from core import app_reopen
        abriu = []
        with patch.object(app_reopen, "start_apps", return_value=self.APPS), \
             patch("subprocess.Popen", side_effect=lambda args, **k: abriu.append(args)), \
             patch("core.window_restore.foreground_matches", return_value=True):
            self.assertTrue(app_reopen.open_start_app("WhatsApp Business"))
        self.assertEqual(abriu, [["explorer.exe", "shell:AppsFolder\\5319275A.51895FA4EA97F_cv1g1gvanyjgm!App"]])


if __name__ == "__main__":
    unittest.main()

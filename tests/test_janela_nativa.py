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


class CentralNaJanelaTests(unittest.TestCase):
    """A central da HAIZEN abre dentro da janela do Jarvis, na tela pedida."""

    def _run(self, params, player):
        import plugins.haizen as plug
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"HAIZEN_DB": str(Path(d) / "h.db")}):
            return plug.run(params, player=player)

    def test_voice_command_opens_the_right_screen_inside_the_window(self):
        abertas = []

        class Janela:
            def show_central(self, rota=""):
                abertas.append(rota)

            def write_log(self, *_):
                pass
        r = self._run({"acao": "central", "pedido": "abre o financeiro"}, Janela())
        self.assertEqual(abertas, ["financeiro"])
        self.assertIn("aqui na janela", r)
        self._run({"acao": "central", "pedido": "quero ver os clientes"}, Janela())
        self._run({"acao": "central"}, Janela())
        self.assertEqual(abertas, ["financeiro", "clientes", ""])

    def test_without_the_window_it_uses_the_browser(self):
        from haizen.central import servidor
        with patch.object(servidor, "iniciar", return_value="http://127.0.0.1:8765/") as iniciar:
            r = self._run({"acao": "central"}, None)
        iniciar.assert_called_once_with(abrir_navegador=True)
        self.assertIn("navegador", r)

    def test_embedded_page_hides_its_own_chat(self):
        raiz = Path(__file__).resolve().parent.parent
        js = (raiz / "haizen/central/static/app.js").read_text(encoding="utf-8")
        css = (raiz / "haizen/central/static/app.css").read_text(encoding="utf-8")
        self.assertIn('new URLSearchParams(location.search).has("embutido")', js)
        self.assertIn('!(EMBUTIDO && rota === "jarvis")', js)
        self.assertIn('body.embutido .trilho nav a[data-rota="jarvis"] { display: none; }', css)

    def test_window_has_the_central_page(self):
        fonte = (Path(__file__).resolve().parent.parent / "ui.py").read_text(encoding="utf-8")
        for trecho in ('QPushButton("Central HAIZEN")', 'QKeySequence("F9")', "QWebEngineView",
                       "?embutido=1#/painel", "AA_ShareOpenGLContexts", "def show_central"):
            self.assertIn(trecho, fonte)


class RespostaLentaTests(unittest.TestCase):
    """O modelo local demora mais que o Gemini para a primeira palavra."""

    def test_watchdog_waits_for_the_local_model(self):
        fonte = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
        self.assertIn("self._rx_deadline = time.monotonic() + self._stall_limit()", fonte)
        self.assertIn("return max(_STALL_LIMIT, t + 30.0, 120.0)", fonte)

    def test_model_is_loaded_at_startup(self):
        import threading
        pedidos = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"

        def abrir(req, timeout=None):
            pedidos.append((req.full_url, json.loads(req.data), timeout))
            return Resp()
        with patch("urllib.request.urlopen", side_effect=abrir):
            start_local.aquecer_modelo("jarvis-qwen3-12k")
            for t in threading.enumerate():
                if t.name == "aquecer-modelo":
                    t.join(5)
        self.assertEqual(pedidos[0][0], "http://127.0.0.1:11434/api/generate")
        self.assertEqual(pedidos[0][1], {"model": "jarvis-qwen3-12k", "prompt": "", "keep_alive": -1})


if __name__ == "__main__":
    unittest.main()

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
        self.assertIn('!(EMBUTIDO && !PONTE && rota === "jarvis")', js)
        self.assertIn('body.embutido .trilho nav a[data-rota="jarvis"] { display: none; }', css)

    def test_window_has_the_central_page(self):
        fonte = (Path(__file__).resolve().parent.parent / "ui.py").read_text(encoding="utf-8")
        for trecho in ('QPushButton("Visual novo")', 'QKeySequence("F9")', "QWebEngineView",
                       "?app=1#/jarvis", "AA_ShareOpenGLContexts", "def show_central",
                       "janela.registrar(_PonteJanela(self))", "QTimer.singleShot(0, self._abrir_visual_inicial)"):
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


class MicrofoneDiagnosticoTests(unittest.TestCase):
    """Quando a voz não chega, o registro diz por quê."""

    def _motor(self, falado):
        from providers.engine_pipeline import PipelineEngine
        registro = []

        class LLM:
            caps = {"tools": True, "tool_format": "openai"}

        class STT:
            async def transcribe(self, pcm, rate):
                return falado
        motor = PipelineEngine(LLM(), STT(), None, log=registro.append)

        async def nada(*a, **k):
            pass
        motor._emit = nada
        motor.send_client_content = nada
        return motor, registro

    def test_speech_start_and_unintelligible_audio_are_logged(self):
        import asyncio
        import numpy as np
        motor, registro = self._motor("")
        motor.auto_turn = True
        fala = (np.sin(np.arange(1600) / 3) * 8000).astype(np.int16).tobytes()     # 100 ms alto
        silencio = np.zeros(1600, dtype=np.int16).tobytes()

        async def tocar():
            for _ in range(5):
                await motor.send_realtime_input(audio={"data": fala})
            for _ in range(10):
                await motor.send_realtime_input(audio={"data": silencio})
        with patch("providers.engine_pipeline._pcm_of", side_effect=lambda a: a["data"]):
            asyncio.run(tocar())
        self.assertIn("SYS: 🎤 ouvindo você…", registro)
        self.assertTrue(any("não entendi nenhuma palavra" in r for r in registro), registro)

    def test_window_explains_why_the_mic_is_ignored(self):
        fonte = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
        for trecho in ("o Jarvis está dormindo", "o push-to-talk está ligado",
                       "o microfone está desligado no Jarvis", "não captou nenhum som em 20 s"):
            self.assertIn(trecho, fonte)


class PromptLocalTests(unittest.TestCase):
    def test_local_prompt_is_short_and_portuguese(self):
        raiz = Path(__file__).resolve().parent.parent
        local = (raiz / "core/prompt_local.txt").read_text(encoding="utf-8")
        gemini = (raiz / "core/prompt.txt").read_text(encoding="utf-8")
        self.assertLess(len(local), len(gemini) / 4)
        self.assertIn("português do Brasil", local)
        self.assertIn("Nunca diga \"sir\"", local)
        for marcador in ("{assistant_name}", "{limits}"):
            self.assertIn(marcador, local)
        fonte = (raiz / "main.py").read_text(encoding="utf-8")
        self.assertIn('PROMPT_LOCAL_PATH = BASE_DIR / "core" / "prompt_local.txt"', fonte)
        self.assertIn("mem_str = mem_str[:1500]", fonte)

    def test_stale_mute_reason_is_dropped(self):
        fonte = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
        self.assertIn('if diag["motivo"] and agora - diag["quando"] > 2:', fonte)


class PonteTests(unittest.TestCase):
    """A interface nova comanda o Jarvis da janela pelas rotas /api/janela."""

    def setUp(self):
        import http.client
        from haizen.central import janela, servidor
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"HAIZEN_DB": str(Path(self.tmp.name) / "h.db")})
        self.env.start()
        self.porta = 17000 + os.getpid() % 900
        self.p = patch.object(servidor, "PORTA", self.porta)
        self.p.start()
        servidor.iniciar(abrir_navegador=False)
        self.servidor, self.janela, self.http = servidor, janela, http.client
        self.eventos = []
        test = self

        class Ponte:
            def estado(self, desde=0):
                return {"estado": "LISTENING", "mudo": False, "dormindo": False, "nome": "Jarvis",
                        "atividade": [{"id": i, "texto": t} for i, t in ((1, "a"), (2, "b")) if i > desde]}

            def enviar(self, texto):
                test.eventos.append(("enviar", texto))

            def microfone(self, ligado):
                test.eventos.append(("mic", ligado))

            def acordar(self):
                test.eventos.append(("acordar",))

            def interromper(self):
                test.eventos.append(("interromper",))

            def abrir(self, nome):
                test.eventos.append(("ajuste", nome))
        self.Ponte = Ponte

    def tearDown(self):
        self.janela.registrar(None)
        self.servidor.parar()
        self.p.stop()
        self.env.stop()
        self.tmp.cleanup()

    def pedir(self, metodo, caminho, corpo=None):
        c = self.http.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        c.request(metodo, caminho, body=json.dumps(corpo) if corpo is not None else None,
                  headers={"X-Central": "1"})
        r = c.getresponse()
        dados = json.loads(r.read() or b"{}")
        c.close()
        return r.status, dados

    def test_without_the_window_the_routes_do_not_exist(self):
        self.janela.registrar(None)
        self.assertEqual(self.pedir("GET", "/api/janela/estado")[0], 404)

    def test_state_activity_and_commands(self):
        from haizen import store
        self.janela.registrar(self.Ponte())
        store.guardar_mensagem("jarvis", "Oi", origem="janela")
        st, e = self.pedir("GET", "/api/janela/estado?desde=1")
        self.assertEqual(st, 200)
        self.assertEqual([a["texto"] for a in e["atividade"]], ["b"])
        self.assertGreater(e["ultima"], 0)
        self.assertEqual(self.pedir("POST", "/api/janela/mensagem", {"texto": " abre o WhatsApp "})[0], 200)
        self.assertEqual(self.pedir("POST", "/api/janela/mensagem", {"texto": "  "})[0], 400)
        self.pedir("POST", "/api/janela/microfone", {"ligado": False})
        self.pedir("POST", "/api/janela/ajuste", {"nome": "audio"})
        self.assertEqual(self.pedir("POST", "/api/janela/ajuste", {"nome": "rm -rf"})[0], 400)
        self.pedir("POST", "/api/janela/interromper", {})
        self.assertEqual(self.eventos, [("enviar", "abre o WhatsApp"), ("mic", False),
                                        ("ajuste", "audio"), ("interromper",)])

    def test_front_uses_the_bridge(self):
        raiz = Path(__file__).resolve().parent.parent / "haizen/central/static"
        js = (raiz / "app.js").read_text(encoding="utf-8")
        html = (raiz / "index.html").read_text(encoding="utf-8")
        for trecho in ('ROTAS.jarvis = async () => (PONTE ? jarvisNativo() : jarvisWeb());',
                       'api("POST", "janela/mensagem", { texto })', 'api("POST", "janela/ajuste"'):
            self.assertIn(trecho, js)
        self.assertIn('id="mic-global"', html)
        self.assertIn('id="abrir-ajustes"', html)


class FerramentasPorPedidoTests(unittest.TestCase):
    """A janela escolhe as ferramentas pelo pedido, como a web."""

    def _motor(self):
        from providers.engine_pipeline import PipelineEngine
        registro = []

        class LLM:
            caps = {"tools": True, "tool_format": "openai", "max_tools": 3, "max_tool_chars": None}
        motor = PipelineEngine(LLM(), None, None, log=registro.append)
        decls = [{"name": n, "description": n, "parameters": {"type": "OBJECT", "properties": {}}}
                 for n in ("open_app", "computer_settings", "computer_control", "web_search",
                           "google_agenda", "file_controller", "haizen")]
        cfg = type("C", (), {"system_instruction": "s", "tools": [{"function_declarations": decls}]})()
        motor._read_config(cfg)
        return motor

    def test_calendar_request_brings_the_calendar_tool(self):
        import asyncio
        from haizen.central.cerebro import escolher_acoes
        motor = self._motor()
        self.assertNotIn("google_agenda", motor.tool_names())
        motor.tool_priority = lambda t: ["haizen", *escolher_acoes(t)]
        motor._queue_generation = lambda: None
        asyncio.run(motor.send_client_content(turns={"role": "user", "parts": [
            {"text": "marca na agenda amanhã das 9 às 10 a reunião"}]}))
        self.assertIn("google_agenda", motor.tool_names())
        self.assertEqual(len(motor.tool_names()), 3)

    def test_window_wires_the_choice(self):
        fonte = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
        self.assertIn("engine.tool_priority = self._ferramentas_do_pedido", fonte)


class GeminiRespostaTests(unittest.TestCase):
    """Perfil gemini: raciocínio curto, ferramentas escolhidas e nova tentativa."""

    def _httpx_falso(self, falhas: int):
        import types

        class ReadTimeout(Exception):
            pass

        class ConnectTimeout(Exception):
            pass
        enviados = []

        class Resposta:
            status_code = 200

            async def aiter_lines(self):
                for linha in ('data: {"choices":[{"delta":{"content":"Oi, Hiago."}}]}', "data: [DONE]"):
                    yield linha

            async def aread(self):
                return b""

            async def aclose(self):
                pass

        class Cliente:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def build_request(self, metodo, url, headers=None, json=None):
                return {"url": url, "json": json}

            async def send(self, req, stream=False):
                enviados.append(req)
                if len(enviados) <= falhas:
                    raise ReadTimeout("sem resposta")
                return Resposta()
        mod = types.SimpleNamespace(AsyncClient=Cliente, ReadTimeout=ReadTimeout,
                                    ConnectTimeout=ConnectTimeout)
        return mod, enviados

    def _falar(self, falhas):
        import asyncio
        mod, enviados = self._httpx_falso(falhas)
        with patch.dict(sys.modules, {"httpx": mod}):
            from providers.llm_openai import OpenAICompatLLM
            llm = OpenAICompatLLM({"base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                                   "model": "gemini-flash-latest", "api_key": "k",
                                   "reasoning_effort": "low", "timeout": "90"})

            async def tudo():
                return [ev async for ev in llm.chat([{"role": "user", "content": "oi"}])]
            return asyncio.run(tudo()), enviados, mod

    def test_one_silent_timeout_is_retried(self):
        eventos, enviados, _ = self._falar(1)
        self.assertEqual(eventos, [{"text": "Oi, Hiago."}])
        self.assertEqual(len(enviados), 2)
        self.assertEqual(enviados[0]["json"]["reasoning_effort"], "low")

    def test_two_timeouts_are_reported(self):
        with self.assertRaises(Exception) as ctx:
            self._falar(2)
        self.assertEqual(type(ctx.exception).__name__, "ReadTimeout")

    def test_gemini_profile_settings(self):
        cfg = start_local.montar_config({}, "gemini", "gemini-flash-latest")
        llm = cfg["providers"]["creds"]["openai_compat"]
        self.assertEqual((llm["reasoning_effort"], llm["timeout"], llm["max_tools"]), ("low", "90", "16"))
        local = start_local.montar_config(cfg, "local", "qwen")["providers"]["creds"]["openai_compat"]
        self.assertNotIn("reasoning_effort", local)


class GeminiSobrecargaTests(unittest.TestCase):
    """503 "high demand" e 429: insistir um pouco e trocar de modelo, antes do erro."""

    def _rodar(self, respostas, reservas="gemini-flash-lite-latest,gemini-2.5-flash"):
        import asyncio
        import types
        modelos = []

        class Resposta:
            def __init__(self, status):
                self.status_code = status

            async def aiter_lines(self):
                for linha in ('data: {"choices":[{"delta":{"content":"Pronto."}}]}', "data: [DONE]"):
                    yield linha

            async def aread(self):
                return b'{"error":{"message":"This model is currently experiencing high demand."}}'

            async def aclose(self):
                pass

        class Cliente:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def build_request(self, metodo, url, headers=None, json=None):
                return json

            async def send(self, corpo, stream=False):
                modelos.append(corpo["model"])
                return Resposta(respostas.pop(0))
        mod = types.SimpleNamespace(AsyncClient=Cliente, ReadTimeout=TimeoutError, ConnectTimeout=TimeoutError)

        async def sem_espera(_):
            pass
        with patch.dict(sys.modules, {"httpx": mod}), patch("asyncio.sleep", sem_espera):
            from providers.llm_openai import OpenAICompatLLM
            llm = OpenAICompatLLM({"base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                                   "model": "gemini-flash-latest", "api_key": "k",
                                   "fallback_models": reservas})

            async def tudo():
                return [ev async for ev in llm.chat([{"role": "user", "content": "oi"}])]
            try:
                return asyncio.run(tudo()), modelos, None
            except Exception as e:  # noqa: BLE001
                return None, modelos, e

    def test_one_503_is_retried_on_the_same_model(self):
        ev, modelos, erro = self._rodar([503, 200])
        self.assertEqual(ev, [{"text": "Pronto."}])
        self.assertEqual(modelos, ["gemini-flash-latest", "gemini-flash-latest"])

    def test_persistent_503_moves_to_the_next_model(self):
        ev, modelos, _ = self._rodar([503, 503, 200])
        self.assertEqual(modelos, ["gemini-flash-latest", "gemini-flash-latest", "gemini-flash-lite-latest"])
        self.assertEqual(ev, [{"text": "Pronto."}])

    def test_quota_moves_on_and_missing_reserve_is_skipped(self):
        ev, modelos, _ = self._rodar([429, 404, 200])
        self.assertEqual(modelos, ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash"])

    def test_a_real_error_is_not_retried(self):
        _, modelos, erro = self._rodar([401])
        self.assertEqual(modelos, ["gemini-flash-latest"])
        self.assertTrue(str(erro).startswith("401"))

    def test_spoken_message_explains_overload(self):
        from providers.engine_pipeline import _failure_line
        self.assertIn("sobrecarregado", _failure_line("o modelo", RuntimeError("503 high demand")))
        self.assertIn("limite gratuito", _failure_line("o modelo", RuntimeError("429 RESOURCE_EXHAUSTED")))

    def test_profile_has_reserves(self):
        cfg = start_local.montar_config({}, "gemini", "gemini-flash-latest")["providers"]["creds"]["openai_compat"]
        self.assertEqual(cfg["fallback_models"], start_local.GEMINI_RESERVAS)


if __name__ == "__main__":
    unittest.main()

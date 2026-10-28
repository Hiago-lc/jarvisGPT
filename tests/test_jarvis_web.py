import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from providers.base import FunctionCall


class FakeLLM:
    """Responde de um roteiro: cada item é (texto, [chamadas])."""
    caps = {"tools": True, "tool_format": "openai", "max_tools": None, "max_tool_chars": None}

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.pedidos = []

    def complete(self, messages, tools=None, **_):
        self.pedidos.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self.roteiro.pop(0)


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"HAIZEN_DB": str(Path(self.tmp.name) / "h.db")})
        self.env.start()
        from haizen.central import cerebro
        self.cerebro = cerebro
        # Nada de ações reais do PC nos testes.
        self.acoes = patch.object(cerebro, "_acoes_pc", return_value={})
        self.acoes.start()
        self.sistema = patch.object(cerebro, "_sistema", return_value="sistema")
        self.sistema.start()

    def tearDown(self):
        self.sistema.stop()
        self.acoes.stop()
        self.env.stop()
        self.tmp.cleanup()


class ConversaTests(_Base):
    def test_tool_round_then_answer_and_history(self):
        from haizen.central import dados
        dados.criar("receitas", {"descricao": "Site", "valor": "1.500,00", "recebido": True})
        llm = FakeLLM([("", [FunctionCall(id="a1", name="central", args={"acao": "painel"})]),
                       ("Você recebeu R$ 1.500 este mês.", [])])
        with patch.object(self.cerebro, "_provedor", return_value=llm):
            r = self.cerebro.responder("Quanto recebi?")
        self.assertEqual(r["resposta"], "Você recebeu R$ 1.500 este mês.")
        self.assertEqual(r["acoes"], ["central"])
        ferramenta = [m for m in llm.pedidos[1]["messages"] if m["role"] == "tool"][0]
        self.assertIn('"receita": 1500.0', ferramenta["content"])
        h = self.cerebro.historico()
        self.assertEqual([m["papel"] for m in h], ["usuario", "jarvis"])

    def test_repeated_call_is_not_executed_twice(self):
        chamada = FunctionCall(id="x", name="lembrar", args={"chave": "cor", "valor": "verde"})
        llm = FakeLLM([("", [chamada]), ("", [FunctionCall(id="y", name="lembrar",
                                                            args={"chave": "cor", "valor": "verde"})]),
                       ("Guardei.", [])])
        with patch.object(self.cerebro, "_provedor", return_value=llm), \
             patch("memory.memory_manager.remember", return_value="ok") as remember:
            r = self.cerebro.responder("Lembra que minha cor é verde")
        self.assertEqual(remember.call_count, 1)
        self.assertEqual(r["resposta"], "Guardei.")

    def test_wandering_model_is_stopped(self):
        voltas = [("", [FunctionCall(id=str(i), name="central", args={"acao": "painel", "de": f"2026-01-0{i+1}"})])
                  for i in range(self.cerebro.MAX_RODADAS)] + [("Resumo final.", [])]
        llm = FakeLLM(voltas)
        with patch.object(self.cerebro, "_provedor", return_value=llm):
            r = self.cerebro.responder("Analise tudo")
        self.assertEqual(r["resposta"], "Resumo final.")
        self.assertIsNone(llm.pedidos[-1]["tools"])     # última volta sem ferramentas

    def test_reasoning_is_hidden(self):
        llm = FakeLLM([("<think>calculando</think>Pronto.", [])])
        with patch.object(self.cerebro, "_provedor", return_value=llm):
            self.assertEqual(self.cerebro.responder("oi")["resposta"], "Pronto.")

    def test_register_through_central_resolves_client_and_drops_access(self):
        from haizen import store
        store.salvar_cliente("Padaria Sol")
        res = self.cerebro.executar_ferramenta("central", {
            "acao": "registrar", "tipo": "tarefas",
            "campos": json.dumps({"titulo": "Cardápio", "cliente": "padaria sol", "acessos": "senha"})})
        self.assertIn("Registrado", res)
        from haizen.central import dados
        t = dados.listar("tarefas")[0]
        self.assertEqual(t["cliente_nome"], "Padaria Sol")
        self.assertFalse(t["tem_acessos"])

    def test_finish_task_by_title(self):
        from haizen.central import dados
        dados.criar("tarefas", {"titulo": "Landing Page Sol"})
        self.assertIn("concluída", self.cerebro.executar_ferramenta("central", {"acao": "concluir", "titulo": "landing page"}))
        self.assertEqual(dados.listar("tarefas")[0]["status"], "Concluída")

    def test_broken_tool_becomes_a_message(self):
        res = self.cerebro.executar_ferramenta("central", {"acao": "registrar", "tipo": "receitas",
                                                           "campos": "{nao é json"})
        self.assertIn("JSON", res)


class ConfirmacaoTests(_Base):
    def test_pc_action_waits_for_web_confirmation(self):
        from core import confirm
        feito = []
        with patch.object(confirm, "_show_cb", None), patch.object(confirm, "_hide_cb", None):
            self.cerebro.ligar_confirmacoes()
            confirm.request("desligar", "Desligar o PC", "", lambda: feito.append(1) or "ok")
            self.assertEqual(self.cerebro.confirmacao_pendente()["titulo"], "Desligar o PC")
            self.cerebro.resolver_confirmacao(True)
            for _ in range(50):
                if feito:
                    break
                time.sleep(0.02)
            self.assertEqual(feito, [1])
            self.assertIsNone(self.cerebro.confirmacao_pendente())


class RotasTests(_Base):
    def setUp(self):
        super().setUp()
        from haizen.central import servidor
        self.porta = 19000 + os.getpid() % 1000
        self.p = patch.object(servidor, "PORTA", self.porta)
        self.p.start()
        servidor.iniciar(abrir_navegador=False)
        self.servidor = servidor

    def tearDown(self):
        self.servidor.parar()
        self.p.stop()
        super().tearDown()

    def pedir(self, metodo, caminho, corpo=None, cab=None):
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        cab = {"X-Central": "1", **(cab or {})}
        c.request(metodo, caminho, body=corpo, headers=cab)
        r = c.getresponse()
        dados = r.read()
        c.close()
        return r.status, r.getheader("Content-Type"), dados

    def test_message_route(self):
        with patch.object(self.cerebro, "responder", return_value={"resposta": "Oi", "acoes": [], "confirmacao": None}) as resp:
            s, _, d = self.pedir("POST", "/api/jarvis/mensagem", json.dumps({"texto": "oi", "voz": True}))
        self.assertEqual(s, 200)
        self.assertEqual(json.loads(d)["resposta"], "Oi")
        resp.assert_called_once_with("oi", True)

    def test_voice_routes(self):
        with patch.object(self.cerebro, "ouvir", side_effect=lambda pcm, taxa: f"{len(pcm)}@{taxa}"):
            s, _, d = self.pedir("POST", "/api/jarvis/ouvir?taxa=48000", b"\x00\x01" * 100,
                                 {"Content-Type": "application/octet-stream"})
        self.assertEqual(json.loads(d)["texto"], "200@48000")
        with patch.object(self.cerebro, "falar", return_value=b"RIFF....WAVE"):
            s, tipo, d = self.pedir("POST", "/api/jarvis/falar", json.dumps({"texto": "olá"}))
        self.assertEqual((s, tipo, d[:4]), (200, "audio/wav", b"RIFF"))

    def test_tailscale_host_is_accepted_others_are_not(self):
        with patch.object(self.cerebro, "estado", return_value={"onde": "x"}):
            s, _, _ = self.pedir("GET", "/api/jarvis/estado", cab={"Host": "meu-pc.tail1234.ts.net"})
            self.assertEqual(s, 200)
            s, _, _ = self.pedir("GET", "/api/jarvis/estado", cab={"Host": "ts.net.evil.com"})
            self.assertEqual(s, 403)

    def test_app_files(self):
        s, tipo, d = self.pedir("GET", "/manifest.webmanifest")
        self.assertEqual((s, tipo), (200, "application/manifest+json"))
        self.assertEqual(json.loads(d)["start_url"], "/#/jarvis")
        s, tipo, _ = self.pedir("GET", "/icone-192.png")
        self.assertEqual((s, tipo), (200, "image/png"))
        s, tipo, _ = self.pedir("GET", "/sw.js")
        self.assertEqual((s, tipo), (200, "text/javascript; charset=utf-8"))


class LancadorTests(unittest.TestCase):
    def test_start_with_windows_writes_and_removes_shortcut(self):
        import jarvis_web
        with tempfile.TemporaryDirectory() as d, \
             patch.object(sys, "platform", "win32"), \
             patch.dict(os.environ, {"APPDATA": d}):
            pasta = jarvis_web._pasta_inicializar()
            pasta.mkdir(parents=True)
            jarvis_web.iniciar_com_windows("hibrido", True)
            atalho = pasta / jarvis_web.NOME_ATALHO
            texto = atalho.read_text(encoding="utf-8")
            self.assertIn("jarvis_web.py", texto)
            self.assertIn("--perfil hibrido --sem-navegador", texto)
            jarvis_web.iniciar_com_windows("hibrido", False)
            self.assertFalse(atalho.exists())

    def test_tailscale_missing_is_explained(self):
        import jarvis_web
        with patch.object(jarvis_web, "_tailscale", return_value=None):
            self.assertIn("tailscale.com/download", jarvis_web.ligar_tailscale())


class RegistroTolerante(_Base):
    def setUp(self):
        super().setUp()
        from haizen import store
        store.salvar_cliente("LOJA EXEMPLO SOLUÇÕES")

    def _receitas(self):
        from haizen.central import dados
        return dados.listar("receitas")

    def test_singular_type_and_loose_fields(self):
        r = self.cerebro.executar_ferramenta("central", {
            "acao": "registrar", "tipo": "receita", "cliente": "loja exemplo solucoes",
            "descricao": "2/2 E-commerce TRAY", "valor": 600, "vencimento": "10/11/2026",
            "recebido": True})
        self.assertIn("Registrado com sucesso", r)
        rec = self._receitas()[0]
        self.assertEqual((rec["descricao"], rec["valor"], rec["vencimento"], rec["recebido"]),
                         ("2/2 E-commerce TRAY", 600.0, "2026-11-10", True))
        self.assertEqual(rec["cliente_nome"], "LOJA EXEMPLO SOLUÇÕES")

    def test_fields_as_object_or_json_with_synonyms(self):
        self.cerebro.executar_ferramenta("central", {
            "acao": "registrar", "tipo": "pagamento",
            "campos": {"cliente": "LOJA EXEMPLO SOLUÇÕES", "descricao_servico": "A", "valor": "600,00",
                       "data_vencimento": "2026-11-10"}})
        self.cerebro.executar_ferramenta("central", {
            "acao": "registrar", "tipo": "receitas",
            "campos": json.dumps({"cliente_nome": "Loja Exemplo", "servico": "B", "valor": 1}),
        })
        self.assertEqual(sorted(r["descricao"] for r in self._receitas()), ["A", "B"])

    def test_errors_are_explicit_and_nothing_is_saved(self):
        r = self.cerebro.executar_ferramenta("central", {"acao": "registrar", "tipo": "boleto", "valor": 1})
        self.assertIn("Não registrei nada", r)
        r = self.cerebro.executar_ferramenta("central", {"acao": "registrar", "tipo": "receitas",
                                                         "cliente": "Ninguém Ltda", "valor": 1})
        self.assertIn("não encontrei o cliente", r)
        r = self.cerebro.executar_ferramenta("central", {"acao": "registrar", "tipo": "receitas",
                                                         "valor": 1, "vencimento": "31/02/2026"})
        self.assertIn("Não registrei nada", r)
        self.assertEqual(self._receitas(), [])

    def test_prompt_forbids_inventing_support(self):
        self.sistema.stop()
        try:
            texto = self.cerebro._sistema("digitou")
        finally:
            self.sistema.start()
        self.assertIn("Não invente suporte", texto)


class InvencaoTests(_Base):
    """O modelo local dizia "registrado com sucesso" sem chamar ferramenta nenhuma."""

    def _receitas(self):
        from haizen.central import dados
        return dados.listar("receitas")

    def test_claim_without_tool_gets_a_second_chance_and_really_saves(self):
        chamada = FunctionCall(id="r", name="central", args={
            "acao": "registrar", "tipo": "receita", "descricao": "2/2 Loja", "valor": 600})
        llm = FakeLLM([("Faturamento de R$ 600 registrado com sucesso.", []),
                       ("", [chamada]),
                       ("Pronto, registrei a receita de R$ 600.", [])])
        with patch.object(self.cerebro, "_provedor", return_value=llm):
            r = self.cerebro.responder("registre 600 da loja, 2/2")
        self.assertEqual(r["acoes"], ["central"])
        self.assertEqual([x["descricao"] for x in self._receitas()], ["2/2 Loja"])
        self.assertIn("[sistema]", llm.pedidos[1]["messages"][-1]["content"])

    def test_claim_that_stays_invented_is_replaced_by_the_truth(self):
        llm = FakeLLM([("Registrado com sucesso.", []), ("Verifiquei no painel, está lá.", [])])
        with patch.object(self.cerebro, "_provedor", return_value=llm):
            r = self.cerebro.responder("registre 600 da loja")
        self.assertTrue(r["resposta"].startswith("Ainda não fiz isso"))
        self.assertEqual(self._receitas(), [])

    def test_plain_answers_are_left_alone(self):
        llm = FakeLLM([("Bom dia! Como posso ajudar?", [])])
        with patch.object(self.cerebro, "_provedor", return_value=llm):
            r = self.cerebro.responder("bom dia")
        self.assertEqual(r["resposta"], "Bom dia! Como posso ajudar?")
        self.assertEqual(len(llm.pedidos), 1)

    def test_honest_no_is_left_alone(self):
        self.assertFalse(self.cerebro._inventou("Não registrei nada: faltam campos: valor.", []))

    def test_invented_answers_are_dropped_from_history(self):
        self.cerebro._guardar("usuario", "registre 600")
        self.cerebro._guardar("jarvis", "Registrado com sucesso.", [])
        self.cerebro._guardar("usuario", "registre 20")
        self.cerebro._guardar("jarvis", "Registrado com sucesso.", ["central"])
        textos = [m["content"] for m in self.cerebro._mensagens_anteriores()]
        self.assertEqual(textos, ["registre 600", "registre 20", "Registrado com sucesso."])

    def test_status_filter_on_receitas_does_not_crash(self):
        from haizen.central import dados
        dados.criar("receitas", {"descricao": "A", "valor": 1})
        self.assertEqual(len(dados.listar("receitas", status="Pago")), 1)


class RegistroDiretoTests(_Base):
    """Pedido claro de receita/despesa: grava sem passar pelo modelo."""

    def setUp(self):
        super().setUp()
        from haizen import store
        store.salvar_cliente("LOJA EXEMPLO SOLUÇÕES")
        store.salvar_cliente("Loja")

    def _pedir(self, texto):
        llm = FakeLLM([("Resposta do modelo.", [])])
        with patch.object(self.cerebro, "_provedor", return_value=llm):
            r = self.cerebro.responder(texto)
        return r, llm

    def _receitas(self):
        from haizen.central import dados
        return dados.listar("receitas")

    def test_the_exact_request_that_failed(self):
        from haizen.central import dados
        r, llm = self._pedir("Registre a receita de R$ 600 da LOJA EXEMPLO SOLUÇÕES, descrição "
                             "2/2 E-commerce TRAY, vencimento hoje, não foi recebida")
        self.assertEqual(llm.pedidos, [])
        self.assertEqual(r["acoes"], ["central"])
        rec = self._receitas()[0]
        self.assertEqual((rec["descricao"], rec["valor"], rec["vencimento"], rec["recebido"],
                          rec["cliente_nome"]),
                         ("2/2 E-commerce TRAY", 600.0, dados.hoje(), False, "LOJA EXEMPLO SOLUÇÕES"))
        self.assertIn("a receber", r["resposta"])
        self.assertIn("R$ 600,00", r["resposta"])

    def test_received_with_date_and_accentless_client(self):
        r, _ = self._pedir("por favor, lance um faturamento de 1.250,50 reais da loja exemplo solucoes, "
                           "descrição Site institucional, vencimento 10/11/2026, já recebido")
        rec = self._receitas()[0]
        self.assertEqual((rec["valor"], rec["vencimento"], rec["recebido"], rec["descricao"]),
                         (1250.5, "2026-11-10", True, "Site institucional"))
        self.assertEqual(rec["cliente_nome"], "LOJA EXEMPLO SOLUÇÕES")   # o nome mais longo vence

    def test_missing_description_asks_instead_of_guessing(self):
        r, llm = self._pedir("registre a receita de R$ 600 da LOJA EXEMPLO SOLUÇÕES")
        self.assertIn("falta a descrição", r["resposta"])
        self.assertEqual(r["acoes"], [])
        self.assertEqual(self._receitas(), [])
        self.assertEqual(llm.pedidos, [])

    def test_unknown_client_asks(self):
        r, _ = self._pedir("registre a receita de R$ 600 da Ninguém Ltda, descrição X")
        self.assertIn("não reconheci o cliente", r["resposta"])
        self.assertEqual(self._receitas(), [])

    def test_expense(self):
        from haizen.central import dados
        r, _ = self._pedir("Registre uma despesa de R$ 80 descrição Adobe, categoria Software, já paga")
        d = dados.listar("despesas")[0]
        self.assertEqual((d["descricao"], d["valor"], d["pago"], d["categoria"]),
                         ("Adobe", 80.0, True, "Software"))
        self.assertIn("paga", r["resposta"])

    def test_questions_and_chat_go_to_the_model(self):
        for texto in ("quanto recebi este mês?", "registrou a receita de R$ 600?",
                      "bom dia", "adicione uma tarefa de revisar o site"):
            r, llm = self._pedir(texto)
            self.assertEqual(r["resposta"], "Resposta do modelo.", texto)


class JanelaDeVozTests(_Base):
    """A janela de voz (start_local) usa o mesmo banco, o mesmo atalho e o mesmo histórico."""

    def setUp(self):
        super().setUp()
        from haizen import store
        store.salvar_cliente("LOJA EXEMPLO SOLUÇÕES")

    def _motor(self, falado):
        import asyncio
        from providers.engine_pipeline import PipelineEngine

        class LLM:
            caps = {"tools": True, "tool_format": "openai"}
            pedidos = []

        class STT:
            async def transcribe(self, pcm, rate):
                return falado

        motor = PipelineEngine(LLM(), STT(), None)
        emitidos, enviados = [], []

        async def emit(m):
            emitidos.append(m)

        async def enviar(**kw):
            enviados.append(kw)
        motor._emit = emit
        motor.send_client_content = enviar
        motor._mic, motor._mic_bytes = [b"\0\0" * 1600], 3200
        return motor, emitidos, enviados, asyncio

    def test_voice_request_is_saved_without_the_model(self):
        from haizen.central import dados
        from haizen.central.atalhos import registro_direto
        motor, emitidos, enviados, asyncio = self._motor(
            "Registre a receita de R$ 600 da LOJA EXEMPLO SOLUÇÕES, descrição 2/2 Loja, vencimento hoje")
        motor.interceptor = lambda t: (registro_direto(t) or ("", False))[0]
        asyncio.run(motor.flush_microphone())
        self.assertEqual(enviados, [])                       # o modelo nem foi chamado
        self.assertEqual(dados.listar("receitas")[0]["descricao"], "2/2 Loja")
        falas = [m for m in emitidos if getattr(m, "kind", "") == "said" or "Registrei" in str(m)]
        self.assertTrue(falas)
        self.assertEqual(motor._history[-1]["role"], "assistant")
        self.assertIn("Registrei", motor._history[-1]["content"])

    def test_other_speech_goes_to_the_model(self):
        motor, _, enviados, asyncio = self._motor("abre o Spotify")
        motor.interceptor = lambda t: ""
        asyncio.run(motor.flush_microphone())
        self.assertEqual(len(enviados), 1)

    def test_broken_shortcut_never_loses_the_sentence(self):
        motor, _, enviados, asyncio = self._motor("abre o Spotify")
        motor.interceptor = lambda t: 1 / 0
        asyncio.run(motor.flush_microphone())
        self.assertEqual(len(enviados), 1)

    def test_window_turns_show_up_in_the_web_history(self):
        from haizen import store
        store.guardar_mensagem("usuario", "abre o Spotify", origem="janela")
        store.guardar_mensagem("jarvis", "Abri o Spotify.", origem="janela")
        h = self.cerebro.historico()
        self.assertEqual([(m["papel"], m["origem"]) for m in h],
                         [("usuario", "janela"), ("jarvis", "janela")])
        # Respostas da janela não têm ferramentas registradas: não são tratadas como invenção.
        self.assertEqual([m["content"] for m in self.cerebro._mensagens_anteriores()],
                         ["abre o Spotify", "Abri o Spotify."])

    def test_plugin_registers_like_the_web(self):
        import plugins.haizen as plug
        from haizen.central import dados
        r = plug.run({"acao": "registrar", "tipo": "receitas", "cliente": "loja exemplo solucoes",
                      "descricao": "Site", "valor": 600, "vencimento": "10/11/2026", "recebido": True})
        self.assertIn("Registrado com sucesso", r)
        rec = dados.listar("receitas")[0]
        self.assertEqual((rec["valor"], rec["recebido"], rec["vencimento"]), (600.0, True, "2026-11-10"))
        r = plug.run({"acao": "registrar", "tipo": "despesas", "descricao": "Adobe", "valor": 80,
                      "recebido": True})
        self.assertTrue(dados.listar("despesas")[0]["pago"])
        dados.criar("tarefas", {"titulo": "Revisar site"})
        self.assertIn("concluída", plug.run({"acao": "concluir", "titulo": "revisar"}))
        self.assertIn("Revisar site", plug.run({"acao": "listar", "tipo": "tarefas"}))

    def test_main_mirrors_turns_and_wires_the_shortcut(self):
        fonte = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
        self.assertIn('origem="janela"', fonte)
        self.assertIn("engine.interceptor = self._atalho_central", fonte)
        self.assertIn("resposta = self._atalho_central(text)", fonte)


class AcoesDoPcTests(_Base):
    """Todas as ações da janela antiga na web, escolhidas pelo pedido."""

    def test_every_old_window_action_is_listed(self):
        modulos = {f.stem for f in (Path(__file__).resolve().parent.parent / "actions").glob("*.py")}
        sem_ferramenta = {"background_monitor", "proactive", "screen_processor", "system_monitor"}
        self.assertEqual(set(self.cerebro.ACOES_PC), modulos - sem_ferramenta)

    def test_request_picks_matching_actions_first(self):
        e = self.cerebro.escolher_acoes
        self.assertEqual(e("move o arquivo da pasta downloads")[0], "file_controller")
        self.assertIn("youtube_video", e("toca uma música no youtube"))
        # WhatsApp: a ferramenta que só envia depois da confirmação na tela.
        self.assertIn("whatsapp", e("manda mensagem no whats pro Pedro"))
        self.assertNotIn("send_message", e("manda mensagem no whats pro Pedro"))
        self.assertIn("send_message", e("manda mensagem no telegram pro Pedro"))
        self.assertIn("reminder", e("me lembra às 15h de ligar"))
        self.assertIn("weather_report", e("vai chover amanhã?"))
        self.assertIn("computer_control", e("digita olá e aperta enter"))
        for sempre in self.cerebro.SEMPRE:
            self.assertIn(sempre, e("bom dia"))

    def test_previous_turn_actions_stay_available(self):
        self.cerebro._guardar("usuario", "abre a pasta downloads")
        self.cerebro._guardar("jarvis", "Abri.", ["file_controller"])
        self.assertIn("file_controller", self.cerebro.prioridade("agora apaga o primeiro"))

    def test_matching_action_survives_a_tight_budget(self):
        from providers import schema
        grande = {"type": "OBJECT", "properties": {"x": {"type": "STRING", "description": "y" * 2500}}}
        falsas = {n: {"name": n, "description": n, "parameters": grande, "handler": lambda **_: ""}
                  for n in ("file_controller", "open_app", "computer_settings", "computer_control", "web_search")}
        with patch.object(self.cerebro, "_acoes_pc", side_effect=lambda nomes=None: {
                n: falsas[n] for n in (nomes or falsas) if n in falsas}):
            texto = "move o arquivo da pasta downloads"
            d = schema.budget(self.cerebro._declaracoes(texto), max_tools=10, max_chars=9000,
                              core_names=self.cerebro.prioridade(texto))
        nomes = [x["name"] for x in d]
        self.assertIn("file_controller", nomes)
        self.assertIn("central", nomes)

    def test_actions_get_a_web_player(self):
        def handler(parameters=None, player=None):
            player.write_log("SYS: abrindo")
            player.request_say("Diga que o Spotify abriu.")
            player.avatar_sorrir()            # recurso da janela antiga: não pode quebrar
            return "Spotify aberto."
        tool = {"name": "open_app", "description": "x", "handler": handler}
        with patch.object(self.cerebro, "_acoes_pc", return_value={"open_app": tool}):
            r = self.cerebro.executar_ferramenta("open_app", {"app_name": "Spotify"})
        self.assertTrue(r.startswith("Spotify aberto."))
        self.assertIn("Diga que o Spotify abriu.", r)

    def test_empty_result_uses_the_log(self):
        tool = {"name": "computer_settings", "description": "x",
                "handler": lambda parameters=None, player=None: player.write_log("Volume em 40%.")}
        with patch.object(self.cerebro, "_acoes_pc", return_value={"computer_settings": tool}):
            self.assertEqual(self.cerebro.executar_ferramenta("computer_settings", {}), "Volume em 40%.")

    def test_video_opens_in_the_pc_browser(self):
        with patch("webbrowser.open") as abrir:
            self.cerebro._PlayerWeb().show_video("https://exemplo.com/v.mp4", "v")
        abrir.assert_called_once_with("https://exemplo.com/v.mp4")


class AgendaDiretaTests(_Base):
    """'O que tenho na agenda hoje?' vai direto ao Google Agenda, sem o modelo."""

    def _servico(self, itens=(), erro=None):
        pedidos = []

        class Lista:
            def execute(self, **_):
                if erro:
                    raise erro
                return {"items": list(itens)}

        class Eventos:
            def list(self, **kw):
                pedidos.append(kw)
                return Lista()

        class Servico:
            def events(self):
                return Eventos()
        return patch("core.google_calendar.service", return_value=Servico()), pedidos

    def _pedir(self, texto):
        llm = FakeLLM([("Resposta do modelo.", [])])
        with patch.object(self.cerebro, "_provedor", return_value=llm):
            return self.cerebro.responder(texto), llm

    def test_todays_agenda_the_way_it_was_asked(self):
        hoje = __import__("datetime").date.today().isoformat()
        p, pedidos = self._servico([
            {"summary": "Reunião com cliente", "start": {"dateTime": f"{hoje}T09:30:00-03:00"}},
            {"summary": "Entrega do site", "start": {"date": hoje}}])
        with p:
            r, llm = self._pedir("Preciso que você me passe as demandas que estão no Google Agenda de hoje por favor.")
        self.assertEqual(llm.pedidos, [])
        self.assertEqual(r["acoes"], ["google_agenda"])
        self.assertIn("2 compromissos hoje", r["resposta"])
        self.assertIn("09:30: Reunião com cliente", r["resposta"])
        self.assertIn("dia todo: Entrega do site", r["resposta"])
        self.assertTrue(pedidos[0]["timeMin"].startswith(hoje))

    def test_tomorrow_and_empty(self):
        p, pedidos = self._servico([])
        with p:
            r, _ = self._pedir("tenho alguma reunião amanhã?")
        self.assertEqual(r["resposta"], "Você não tem nada no Google Agenda amanhã.")
        amanha = (__import__("datetime").date.today() + __import__("datetime").timedelta(days=1)).isoformat()
        self.assertTrue(pedidos[0]["timeMin"].startswith(amanha))

    def test_week_shows_the_day(self):
        import datetime as dt
        d = dt.date.today()
        p, _ = self._servico([{"summary": "Call", "start": {"dateTime": f"{d.isoformat()}T15:00:00-03:00"}}])
        with p:
            r, _ = self._pedir("o que tenho na agenda esta semana?")
        self.assertIn(f"{d.strftime('%d/%m')}, 15:00: Call", r["resposta"])

    def test_connection_problem_is_told_plainly(self):
        from core.google_calendar_errors import CalendarSetupError
        p, _ = self._servico(erro=CalendarSetupError("A autorização do Google expirou ou foi revogada."))
        with p:
            r, _ = self._pedir("o que tenho na agenda hoje?")
        self.assertIn("Não consegui ler o Google Agenda: A autorização do Google expirou", r["resposta"])

    def test_creating_an_event_still_goes_to_the_model(self):
        # Com horário, criar é feito pelo código (EventoDiretoTests); sem horário,
        # falta informação e o modelo pergunta.
        for texto in ("agenda uma call com o cliente sexta", "marca uma reunião com a Padaria Sol",
                      "quais demandas da central estão atrasadas?"):
            r, llm = self._pedir(texto)
            self.assertEqual(r["resposta"], "Resposta do modelo.", texto)


class RecusaTests(_Base):
    def test_refusal_without_trying_gets_reminded_of_its_tools(self):
        chamada = FunctionCall(id="w", name="open_app", args={"app_name": "WhatsApp"})
        tool = {"name": "open_app", "description": "abre apps",
                "handler": lambda parameters=None, player=None: "WhatsApp aberto."}
        llm = FakeLLM([("Não consigo abrir o WhatsApp diretamente.", []), ("", [chamada]),
                       ("Abri o WhatsApp.", [])])
        with patch.object(self.cerebro, "_provedor", return_value=llm), \
             patch.object(self.cerebro, "_acoes_pc", return_value={"open_app": tool}):
            r = self.cerebro.responder("abre o WhatsApp")
        self.assertEqual(r["resposta"], "Abri o WhatsApp.")
        self.assertEqual(r["acoes"], ["open_app"])
        self.assertIn("open_app", llm.pedidos[1]["messages"][-1]["content"])

    def test_honest_refusal_after_retry_is_kept(self):
        llm = FakeLLM([("Não tenho acesso ao seu banco.", []), ("Não tenho acesso ao seu banco.", [])])
        with patch.object(self.cerebro, "_provedor", return_value=llm):
            r = self.cerebro.responder("mostra meu saldo do banco")
        self.assertEqual(r["resposta"], "Não tenho acesso ao seu banco.")

    def test_draft_requests_never_offer_the_sending_tool(self):
        t = ("Eu quero que você abra meu WhatsApp e digite a mensagem Fechou ali pro Guilherme, "
             "mas não envie, por favor.")
        escolhidas = self.cerebro.escolher_acoes(t, ["send_message"])
        self.assertIn("whatsapp_draft", escolhidas)
        self.assertNotIn("send_message", escolhidas)
        self.assertIn("whatsapp", self.cerebro.escolher_acoes("manda no whats pro Pedro: oi"))
        self.assertIn("send_message", self.cerebro.escolher_acoes("manda no telegram pro Pedro: oi"))


class EventoDiretoTests(_Base):
    """Criar compromissos no Google Agenda pelo que a frase diz, sem o modelo."""

    def setUp(self):
        super().setUp()
        from haizen.central import atalhos
        atalhos._ULTIMO_DIA.clear()
        self.criados = []

        def criar(params):
            self.criados.append(params)
            return "status=done action=google_agenda verified=true"
        self.p = patch("actions.google_agenda.google_agenda", side_effect=criar)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        super().tearDown()

    def _pedir(self, texto):
        llm = FakeLLM([("Resposta do modelo.", [])])
        with patch.object(self.cerebro, "_provedor", return_value=llm):
            return self.cerebro.responder(texto), llm

    def test_the_two_events_from_the_screenshot(self):
        import datetime as dt
        r, llm = self._pedir("para amanhã coloque de 9 as 10 Vídeo Café Empresarial da ACI de 11 as 12 - Estudos")
        self.assertEqual(llm.pedidos, [])
        amanha = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        self.assertEqual([(c["title"], c["start"][:16], c["end"][11:16]) for c in self.criados],
                         [("Vídeo Café Empresarial da ACI", f"{amanha}T09:00", "10:00"),
                          ("Estudos", f"{amanha}T11:00", "12:00")])
        self.assertTrue(self.criados[0]["start"].endswith("-03:00"))
        self.assertIn("Coloquei no Google Agenda de amanhã", r["resposta"])
        self.assertEqual(r["acoes"], ["google_agenda"])

    def test_follow_up_without_a_day_uses_the_day_just_mentioned(self):
        import datetime as dt
        self._pedir("o que tenho na agenda amanhã?")
        self._pedir("coloque de 9 as 10 Vídeo Café Empresarial da ACI")
        amanha = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        self.assertEqual(self.criados[-1]["title"], "Vídeo Café Empresarial da ACI")
        self.assertTrue(self.criados[-1]["start"].startswith(amanha))

    def test_single_time_and_title_before_it(self):
        self._pedir("marca uma reunião com a Padaria Sol sexta às 15h")
        self.assertEqual(self.criados[0]["title"], "reunião com a Padaria Sol")
        self.assertIn("T15:00", self.criados[0]["start"])
        self.assertIn("T16:00", self.criados[0]["end"])

    def test_problems_are_told_not_hidden(self):
        r, _ = self._pedir("coloca na agenda amanhã das 10 às 9 revisão")
        self.assertIn("precisa ser depois do início", r["resposta"])
        self.assertEqual(self.criados, [])

    def test_other_requests_are_left_alone(self):
        for t in ("me lembra às 15h de ligar pro cliente", "quais compromissos tenho amanhã?",
                  "registre a receita de R$ 600 da Ninguém, descrição 2/2 Site"):
            r, llm = self._pedir(t)
            self.assertEqual(self.criados, [], t)


class _AgendaFalsa:
    """Google Agenda em memória: list, get, patch e delete."""

    def __init__(self, eventos):
        self.eventos = {e["id"]: e for e in eventos}
        self.apagados = []

    def events(self):
        return self

    def list(self, **kw):
        ini, fim = kw["timeMin"][:10], kw["timeMax"][:10]
        quando = lambda e: e["start"].get("dateTime") or e["start"].get("date")
        itens = [e for e in self.eventos.values() if ini <= quando(e)[:10] < fim]
        return type("R", (), {"execute": lambda _s, **k: {"items": sorted(itens, key=quando)}})()

    def get(self, calendarId, eventId):
        return type("R", (), {"execute": lambda _s, **k: dict(self.eventos[eventId])})()

    def patch(self, calendarId, eventId, body, sendUpdates):
        for k, v in body.items():   # null apaga o campo, como no Google
            self.eventos[eventId][k] = {a: b for a, b in v.items() if b is not None} if isinstance(v, dict) else v
        return type("R", (), {"execute": lambda _s, **k: dict(self.eventos[eventId])})()

    def delete(self, calendarId, eventId, sendUpdates):
        def run(_s, **k):
            self.apagados.append(eventId)
            self.eventos.pop(eventId)
        return type("R", (), {"execute": run})()


class MudarEventoTests(_Base):
    def setUp(self):
        super().setUp()
        import datetime as dt
        self.amanha = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        ev = lambda i, t, h1, h2: {"id": i, "summary": t,
                                   "start": {"dateTime": f"{self.amanha}T{h1}:00-03:00", "timeZone": "America/Sao_Paulo"},
                                   "end": {"dateTime": f"{self.amanha}T{h2}:00-03:00", "timeZone": "America/Sao_Paulo"}}
        self.agenda = _AgendaFalsa([ev("a1", "Vídeo Café Empresarial da ACI", "09:00", "10:00"),
                                    ev("a2", "Estudos", "11:00", "12:00"),
                                    ev("a3", "Reunião com a Padaria Sol", "15:00", "16:00")])
        self.p = patch("core.google_calendar.service", return_value=self.agenda)
        self.p.start()
        self.confirmacoes = []
        from core import confirm
        self.c = patch.object(confirm, "request", side_effect=lambda **kw: (self.confirmacoes.append(kw), "[CONFIRMATION_PENDING] x")[1])
        self.c.start()

    def tearDown(self):
        self.c.stop()
        self.p.stop()
        super().tearDown()

    def _pedir(self, texto):
        llm = FakeLLM([("Resposta do modelo.", [])])
        with patch.object(self.cerebro, "_provedor", return_value=llm):
            return self.cerebro.responder(texto)

    def test_move_keeps_the_duration(self):
        r = self._pedir("remarca o Estudos de amanhã para as 14h")
        self.assertEqual(self.agenda.eventos["a2"]["start"]["dateTime"][11:16], "14:00")
        self.assertEqual(self.agenda.eventos["a2"]["end"]["dateTime"][11:16], "15:00")
        self.assertIn('Remarquei "Estudos"', r["resposta"])

    def test_move_with_a_new_range_and_day(self):
        import datetime as dt
        self._pedir("muda a reunião com a Padaria Sol para sexta das 10 às 11:30")
        ev = self.agenda.eventos["a3"]
        dia = dt.date.fromisoformat(ev["start"]["dateTime"][:10])
        self.assertEqual(dia.weekday(), 4)
        self.assertEqual((ev["start"]["dateTime"][11:16], ev["end"]["dateTime"][11:16]), ("10:00", "11:30"))

    def test_delete_happens_right_away(self):
        r = self._pedir("exclui o vídeo café da agenda de amanhã")
        self.assertEqual(self.agenda.apagados, ["a1"])
        self.assertEqual(self.confirmacoes, [])
        self.assertIn("Excluí do Google Agenda Vídeo Café Empresarial da ACI", r["resposta"])

    def test_rename(self):
        r = self._pedir("muda o nome do Estudos de amanhã para Revisão de inglês")
        self.assertEqual(self.agenda.eventos["a2"]["summary"], "Revisão de inglês")
        self.assertIn('Renomeei "Estudos"', r["resposta"])
        self._pedir("renomeia a reunião com a Padaria Sol para Call Padaria Sol")
        self.assertEqual(self.agenda.eventos["a3"]["summary"], "Call Padaria Sol")

    def test_change_start_keeps_duration(self):
        r = self._pedir("muda o horário do Estudos de amanhã para as 16h")
        ev = self.agenda.eventos["a2"]
        self.assertEqual((ev["start"]["dateTime"][11:16], ev["end"]["dateTime"][11:16]), ("16:00", "17:00"))
        self.assertIn("das 16:00 às 17:00", r["resposta"])

    def test_change_end_and_duration(self):
        self._pedir("muda o término da reunião com a Padaria Sol para as 17h30")
        self.assertEqual(self.agenda.eventos["a3"]["end"]["dateTime"][11:16], "17:30")
        self._pedir("muda a duração do Estudos de amanhã para 2 horas")
        self.assertEqual(self.agenda.eventos["a2"]["end"]["dateTime"][11:16], "13:00")
        self._pedir("estende o vídeo café de amanhã até 10:45")
        self.assertEqual(self.agenda.eventos["a1"]["end"]["dateTime"][11:16], "10:45")

    def test_description_and_location(self):
        r = self._pedir("coloca na descrição da reunião com a Padaria Sol: levar as fotos do cardápio")
        self.assertEqual(self.agenda.eventos["a3"]["description"], "levar as fotos do cardápio")
        self.assertIn("descrição", r["resposta"])
        self._pedir("muda o local da reunião com a Padaria Sol para Rua das Flores, 120")
        self.assertEqual(self.agenda.eventos["a3"]["location"], "Rua das Flores, 120")

    def test_all_day_event_moves_by_day(self):
        import datetime as dt
        amanha = dt.date.fromisoformat(self.amanha)
        self.agenda.eventos["d1"] = {"id": "d1", "summary": "Feriado interno", "start": {"date": self.amanha},
                                     "end": {"date": (amanha + dt.timedelta(days=1)).isoformat()}}
        r = self._pedir("passa o feriado interno de amanhã para sexta")
        ev = self.agenda.eventos["d1"]
        self.assertEqual(dt.date.fromisoformat(ev["start"]["date"]).weekday(), 4)
        self.assertIn("Remarquei", r["resposta"])

    def test_event_found_by_its_current_time(self):
        self._pedir("muda o horário da reunião de amanhã das 15h para as 17h")
        self.assertEqual(self.agenda.eventos["a3"]["start"]["dateTime"][11:16], "17:00")
        self._pedir("remarca o compromisso das 11h de amanhã para as 8h")
        self.assertEqual(self.agenda.eventos["a2"]["start"]["dateTime"][11:16], "08:00")

    def test_conversation_from_the_screenshot(self):
        import datetime as dt
        self.agenda.eventos["b1"] = {"id": "b1", "summary": "Banners São Rafael",
                                     "start": {"dateTime": f"{self.amanha}T09:00:00-03:00"},
                                     "end": {"dateTime": f"{self.amanha}T10:00:00-03:00"}}
        r = self._pedir("preciso que ajuste o horário da demanda Banners São Rafael da agenda para ser de 14 as 15")
        ev = self.agenda.eventos["b1"]
        self.assertEqual((ev["start"]["dateTime"][11:16], ev["end"]["dateTime"][11:16]), ("14:00", "15:00"))
        self.assertEqual(len(self.agenda.eventos), 4)          # nada foi criado
        self.assertIn("Banners São Rafael", r["resposta"])
        # "dessa tarefa", sem dizer o horário: pergunta, e a resposta seguinte completa.
        r = self._pedir("ajuste o horário dessa tarefa de amanhã")
        self.assertIn("Para que horário mudo \"Banners São Rafael\"", r["resposta"])
        r = self._pedir("das 16 às 17:30")
        self.assertEqual((ev["start"]["dateTime"][11:16], ev["end"]["dateTime"][11:16]), ("16:00", "17:30"))

    def test_delete_by_pasting_the_listed_line(self):
        import actions.google_agenda as ga
        self.agenda.eventos["e1"] = {"id": "e1", "summary": "preciso que ajuste o horário da demanda Banners São Rafael da ser",
                                     "start": {"dateTime": f"{self.amanha}T14:00:00-03:00"},
                                     "end": {"dateTime": f"{self.amanha}T15:00:00-03:00"}}
        self.agenda.eventos["b1"] = {"id": "b1", "summary": "Banners São Rafael",
                                     "start": {"dateTime": f"{self.amanha}T09:00:00-03:00"},
                                     "end": {"dateTime": f"{self.amanha}T10:00:00-03:00"}}
        ga.lembrar_listados(list(self.agenda.eventos.values()))
        r = self._pedir("preciso que exclua: 14:00: preciso que ajuste o horário da demanda Banners São Rafael da ser")
        self.assertEqual(self.agenda.apagados, ["e1"])
        self.assertIn("Excluí", r["resposta"])
        ga.ULTIMOS.update(quando=0.0, itens=[])

    def test_spoken_names_distorted_by_voice(self):
        for frase in ("Demanda na minha agenda de amanhã, tem escrito BANISHON Rafa, eu preciso que ajuste "
                      "o horário dela para 2 às 15 e não de 2 às 17",
                      "O nome da demanda é BANES São Rafael. Então, preciso que você ajuste o horário dela "
                      "das 14 às 15 e não de 14 às 17"):
            self.agenda.eventos["b1"] = {"id": "b1", "summary": "Banners São Rafael",
                                         "start": {"dateTime": f"{self.amanha}T14:00:00-03:00"},
                                         "end": {"dateTime": f"{self.amanha}T17:00:00-03:00"}}
            r = self._pedir(frase)
            ev = self.agenda.eventos["b1"]
            self.assertEqual((ev["start"]["dateTime"][11:16], ev["end"]["dateTime"][11:16]), ("14:00", "15:00"), r)

    def test_my_name_is_saved(self):
        from unittest.mock import patch as _p
        with _p("memory.config_manager.save_assistant_config") as salvar, \
             _p("memory.config_manager.get_assistant_name", return_value="Jarvis"):
            r = self._pedir("vitor? meu nome é HIAGO")
        salvar.assert_called_once_with("Jarvis", "Hiago")
        self.assertIn("Hiago", r["resposta"])

    def test_unrelated_rename_goes_to_the_model(self):
        r = self._pedir("renomeia o arquivo relatório para final")
        self.assertEqual(r["resposta"], "Resposta do modelo.")

    def test_not_found_and_ambiguous_are_explained(self):
        r = self._pedir("cancela a reunião com o dentista amanhã")
        self.assertIn("Não achei", r["resposta"])
        self.agenda.eventos["a4"] = dict(self.agenda.eventos["a2"], id="a4")
        r = self._pedir("apaga o compromisso Estudos de amanhã")
        self.assertIn("mais de um", r["resposta"])

    def test_unrelated_deletes_go_to_the_model(self):
        r = self._pedir("apaga o arquivo relatório de amanhã")
        self.assertEqual(r["resposta"], "Resposta do modelo.")


class ExcluirSemNomeTests(_Base):
    """'Remove elas' e 'exclui os das 14h': os compromissos certos, uma confirmação só."""

    def setUp(self):
        super().setUp()
        import datetime as dt
        hoje = dt.date.today().isoformat()
        ev = lambda i, t, h: {"id": i, "summary": t, "start": {"dateTime": f"{hoje}T{h}:00-03:00"},
                              "end": {"dateTime": f"{hoje}T{h[:2]}:59:00-03:00"}}
        self.agenda = _AgendaFalsa([ev("b1", "Banners São Rafael", "14:00"), ev("b2", "Criativos São Rafael", "14:00"),
                                    ev("b3", "Estudos", "16:00")])
        self.p = patch("core.google_calendar.service", return_value=self.agenda)
        self.p.start()
        self.confirmacoes = []
        from core import confirm
        self.c = [patch.object(confirm, "request", side_effect=lambda **kw: (self.confirmacoes.append(kw), "[CONFIRMATION_PENDING] x")[1]),
                  patch.object(confirm, "pending_title", return_value="")]
        for c in self.c:
            c.start()
        import actions.google_agenda as ga
        ga.ULTIMOS.update(quando=0.0, itens=[])

    def tearDown(self):
        for c in self.c:
            c.stop()
        self.p.stop()
        super().tearDown()

    def _pedir(self, texto):
        llm = FakeLLM([("Resposta do modelo.", [])])
        with patch.object(self.cerebro, "_provedor", return_value=llm):
            return self.cerebro.responder(texto)

    def test_by_time_today(self):
        r = self._pedir("exclui os compromissos das 14h de hoje")
        self.assertIn("Excluí do Google Agenda: Banners São Rafael", r["resposta"])
        self.assertEqual(self.confirmacoes, [])
        self.assertEqual(sorted(self.agenda.apagados), ["b1", "b2"])

    def test_pronoun_uses_what_was_just_listed(self):
        import actions.google_agenda as ga
        ga.lembrar_listados([self.agenda.eventos["b1"], self.agenda.eventos["b2"]])
        r = self._pedir("é para remover elas por favor")
        self.assertIn("Excluí", r["resposta"])
        self.assertEqual(sorted(self.agenda.apagados), ["b1", "b2"])

    def test_pronoun_without_a_recent_list_goes_to_the_model(self):
        r = self._pedir("é para remover elas por favor")
        self.assertEqual(r["resposta"], "Resposta do modelo.")
        self.assertEqual(self.confirmacoes, [])


class DatasTests(unittest.TestCase):
    def test_brazilian_dates(self):
        from haizen.central.dados import _data
        self.assertEqual(_data("10/11/2026"), "2026-11-10")
        self.assertEqual(_data("5/1/26"), "2026-01-05")
        self.assertEqual(_data("2026-11-10T12:00"), "2026-11-10")
        with self.assertRaises(ValueError):
            _data("ontem")


class TailscaleTests(unittest.TestCase):
    def test_activation_output_is_not_hidden_and_waits(self):
        import jarvis_web
        import subprocess
        with patch.object(jarvis_web, "_tailscale", return_value="tailscale"), \
             patch.object(jarvis_web, "endereco_tailscale", return_value="https://pc.tail1.ts.net"), \
             patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
            msg = jarvis_web.ligar_tailscale()
        kwargs = run.call_args.kwargs
        self.assertNotIn("capture_output", kwargs)
        self.assertGreaterEqual(kwargs["timeout"], 300)
        self.assertIn("https://pc.tail1.ts.net", msg)

    def test_timeout_is_a_message_not_a_crash(self):
        import jarvis_web
        import subprocess
        with patch.object(jarvis_web, "_tailscale", return_value="tailscale"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("t", 300)):
            self.assertIn("Ative o Serve", jarvis_web.ligar_tailscale())


class InicioComWindowsTests(unittest.TestCase):
    def _gerar(self, **kw):
        import jarvis_web
        with tempfile.TemporaryDirectory() as d, \
             patch.object(jarvis_web.sys, "platform", "win32"), \
             patch.object(jarvis_web, "_pasta_inicializar", return_value=Path(d)):
            msg = jarvis_web.iniciar_com_windows("local", True, **kw)
            return msg, (Path(d) / jarvis_web.NOME_ATALHO).read_text(encoding="utf-8")

    def test_web_only_by_default(self):
        _, cmd = self._gerar()
        self.assertIn("jarvis_web.py", cmd)
        self.assertNotIn("start_local.py", cmd)

    def test_voice_window_too(self):
        msg, cmd = self._gerar(com_janela=True)
        self.assertIn('start_local.py" --perfil local --aguardar', cmd)
        self.assertLess(cmd.index("jarvis_web.py"), cmd.index("start_local.py"))
        self.assertIn("janela de voz", msg)

    def test_waits_for_ollama_to_come_up(self):
        import start_local
        respostas = [["Ollama não está rodando"], ["Ollama não está rodando"], []]
        with patch.object(start_local, "verificar", side_effect=lambda *_: respostas.pop(0)):
            self.assertEqual(start_local.verificar_aguardando("local", "m", 60, passo=0), [])
        self.assertEqual(respostas, [])

    def test_gives_up_after_the_limit(self):
        import start_local
        with patch.object(start_local, "verificar", return_value=["Ollama não está rodando"]):
            self.assertEqual(start_local.verificar_aguardando("local", "m", 0, passo=0),
                             ["Ollama não está rodando"])


if __name__ == "__main__":
    unittest.main()

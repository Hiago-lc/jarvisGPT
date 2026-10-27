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


if __name__ == "__main__":
    unittest.main()

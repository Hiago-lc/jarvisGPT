"""Uso do Claude anotado em cada chamada, modelos por área e avisos."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class UsoTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": str(base / "d"), "HAIZEN_DB": str(base / "h.db"),
                                           "HAIZEN_NOTIFICAR_WINDOWS": "0"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def _rodar(self, saida, codigo=0, **kw):
        from haizen import executor
        cp = subprocess.CompletedProcess([], codigo, saida, "")
        with patch.object(executor, "claude_disponivel", return_value="claude"), \
                patch("haizen.executor.subprocess.run", return_value=cp) as run:
            r = executor.rodar_claude(["-p"], "x", Path(self.dir.name) / "w", 10, **kw)
        return r, run

    def test_cada_chamada_fica_anotada(self):
        from haizen import uso
        saida = json.dumps({"result": "ok", "session_id": "s", "total_cost_usd": 0.42, "duration_ms": 61000,
                            "num_turns": 7, "usage": {"input_tokens": 10, "output_tokens": 900,
                                                      "cache_creation_input_tokens": 5000, "cache_read_input_tokens": 80000},
                            "modelUsage": {"claude-opus-5-5": {}}})
        r, _ = self._rodar(saida, origem="agente", referencia="12 Criativos")
        self.assertEqual(r["session_id"], "s")
        res = uso.resumo(7)
        self.assertEqual(res["hoje"]["chamadas"], 1)
        self.assertAlmostEqual(res["hoje"]["custo_usd"], 0.42)
        self.assertEqual(res["recentes"][0]["modelo"], "opus-5-5")
        self.assertEqual(res["maiores"][0]["referencia"], "12 Criativos")
        self.assertIn("agente", res["por_origem"])

    def test_limite_atingido_vira_aviso(self):
        from haizen import notificar, uso
        saida = json.dumps({"is_error": True, "result": "Claude AI usage limit reached|1793900000"})
        with self.assertRaises(RuntimeError):
            self._rodar(saida, codigo=1)
        self.assertIsNotNone(uso.resumo(1)["limite"])
        self.assertEqual(notificar.listar()[0]["titulo"], "Limite do Claude")

    def test_modelos_por_area(self):
        from haizen import uso
        self.assertEqual(uso.modelo("jarvis"), "sonnet")
        self.assertEqual(uso.modelo("agentes", "opus"), "opus")          # o do agente vale no padrão
        uso.salvar_config({"modelos": {"agentes": "sonnet", "jarvis": "invalido"}})
        self.assertEqual(uso.modelo("agentes", "opus"), "sonnet")
        self.assertEqual(uso.modelo("jarvis"), "sonnet")

    def test_producao_usa_o_modelo_e_retoma_a_sessao(self):
        from haizen import executor
        saida = json.dumps({"result": "feito", "session_id": "s2"})
        from haizen import executor as ex
        cp = subprocess.CompletedProcess([], 0, saida, "")
        with patch.object(ex, "claude_disponivel", return_value="claude"), \
                patch("haizen.executor.subprocess.run", return_value=cp) as run:
            executor.executar_producao("p", Path(self.dir.name) / "w", [], modelo="opus", sessao="s1")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[cmd.index("--model") + 1], "opus")
        self.assertEqual(cmd[cmd.index("--resume") + 1], "s1")

    def test_avisos_em_ordem(self):
        from haizen import notificar
        a = notificar.avisar("Pronto para aprovar", "Criativos", "aprovacao", "#/agentes/3")
        notificar.avisar("Pergunta", "Qual o preço?", "pergunta")
        self.assertEqual(notificar.ultimo_id(), a["id"] + 1)
        self.assertEqual([x["titulo"] for x in notificar.listar(a["id"])], ["Pergunta"])


if __name__ == "__main__":
    unittest.main()


class ProducaoMcpTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.pasta = Path(self.dir.name) / "trabalho"
        self.pasta.mkdir()
        self.env = patch.dict(os.environ, {"HAIZEN_TRABALHO_PASTA": str(self.pasta)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_so_grava_dentro_da_pasta_do_trabalho(self):
        from haizen.producao import mcp_producao as m
        self.assertEqual(m._dentro("saida.mp4"), (self.pasta / "saida.mp4").resolve())
        with self.assertRaises(ValueError):
            m._dentro(str(Path(self.dir.name) / "fora.mp4"))
        with self.assertRaises(ValueError):
            m._dentro("../fora.png")
        self.assertEqual(m._dentro(str(Path(self.dir.name) / "cliente.png"), gravar=False).name, "cliente.png")

    def test_producao_liga_o_servidor_de_ferramentas(self):
        from haizen import executor
        cp = subprocess.CompletedProcess([], 0, json.dumps({"result": "ok", "session_id": "s"}), "")
        with patch.object(executor, "claude_disponivel", return_value="claude"), \
                patch("haizen.executor.subprocess.run", return_value=cp) as run:
            executor.executar_producao("p", self.pasta, [])
        cmd = run.call_args[0][0]
        cfg = json.loads(Path(cmd[cmd.index("--mcp-config") + 1]).read_text(encoding="utf-8"))
        self.assertEqual(cfg["mcpServers"]["producao"]["env"]["HAIZEN_TRABALHO_PASTA"], str(self.pasta))
        permitidas = cmd[cmd.index("--allowedTools") + 1].split(",")
        self.assertIn("mcp__producao", permitidas)
        self.assertIn("PowerShell(python:*)", permitidas)
        self.assertEqual(executor.arquivos_da_pasta(str(self.pasta)), [])        # a config não aparece como entrega


class RevisaoGeralTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        b = Path(self.dir.name)
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": str(b / "d"), "HAIZEN_DB": str(b / "h.db"),
                                           "HAIZEN_NOTIFICAR_WINDOWS": "0", "JARVIS_CEREBRO": "local"})
        self.env.start()
        (b / "d").mkdir()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_custo_de_sessao_retomada_conta_so_a_diferenca(self):
        from haizen import uso
        uso.registrar({"session_id": "S", "total_cost_usd": 1.0}, "jarvis")
        uso.salvar_config({"modelos": {"jarvis": "sonnet"}})          # não apaga as sessões
        uso.registrar({"session_id": "S", "total_cost_usd": 1.3}, "jarvis")
        self.assertAlmostEqual(uso.resumo()["hoje"]["custo_usd"], 1.3)

    def test_horario_de_volta_do_limite(self):
        import datetime as dt
        from haizen import uso
        agora = dt.datetime(2026, 11, 5, 10, 0).timestamp()
        v = dt.datetime.fromtimestamp(uso.volta_em("You've hit your session limit · resets 2:20pm (America/Sao_Paulo)", agora))
        self.assertEqual((v.hour, v.minute), (14, 22))
        self.assertTrue(uso.e_limite("You've hit your session limit · resets 2:20pm"))
        self.assertEqual(uso.volta_em("sem horário", agora), agora + 3600)

    def test_conversa_do_jarvis_recomeca_quando_cresce_ou_vira_o_dia(self):
        import time
        from haizen.central import claude_cerebro as cc
        cc._guardar_sessao("A", 1000)
        self.assertEqual(cc.sessao(), "A")
        cc._guardar_sessao("A", cc.LIMITE_CONTEXTO + 1)
        self.assertEqual(cc.sessao(), "")
        cc._arquivo_sessao().write_text(json.dumps({"id": "B", "inicio": time.time() - 2 * 86400}), encoding="utf-8")
        self.assertEqual(cc.sessao(), "")

    def test_limite_para_a_fila_e_ela_volta_sozinha(self):
        from haizen import store, worker
        t = store.criar_trabalho("criativos", "peça", "claude")
        if t is None:
            self.skipTest("sem criar_trabalho")
        with patch("haizen.executor.executar", side_effect=RuntimeError("You've hit your session limit · resets 2:20pm")), \
                patch("haizen.worker.agendar_retomada") as ag:
            worker._rodar()
        self.assertTrue(store.trabalho(t["id"])["erro"].startswith(worker.LIMITE_MARCA))
        ag.assert_called_once()
        with patch("haizen.worker.iniciar"), patch("haizen.executor.claude_disponivel", return_value="claude"):
            self.assertEqual(worker.retomar_apos_limite(), 1)
        self.assertEqual(store.trabalho(t["id"])["status"], "na_fila")

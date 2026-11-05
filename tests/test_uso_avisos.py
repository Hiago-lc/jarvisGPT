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

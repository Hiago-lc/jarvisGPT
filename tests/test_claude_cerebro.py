"""O Claude como cérebro do Jarvis: a volta pela linha de comando, a conversa
contínua, as ferramentas e o guia da marca que os agentes seguem."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

STREAM = "\n".join(json.dumps(e) for e in [
    {"type": "system", "subtype": "init", "session_id": "s-1"},
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "ToolSearch", "input": {}},
        {"type": "tool_use", "name": "mcp__jarvis__listar", "input": {"tipo": "receitas"}}]}},
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "mcp__jarvis__atualizar", "input": {}},
        {"type": "tool_use", "name": "mcp__jarvis__listar", "input": {}}]}},
    {"type": "result", "subtype": "success", "is_error": False, "result": "Pronto, marquei.", "session_id": "s-1"},
])


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": str(base / "dados"),
                                           "HAIZEN_DB": str(base / "haizen.db"),
                                           "JARVIS_CEREBRO": ""})
        self.env.start()
        self.base = base

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()


class CerebroClaudeTests(Base):
    def _rodar(self, saidas):
        from haizen import executor
        chamadas = []

        def falso(cmd, **kw):
            chamadas.append((cmd, kw))
            out, err = saidas.pop(0)
            return subprocess.CompletedProcess(cmd, 0, out, err)
        p = [patch.object(executor, "claude_disponivel", return_value="/bin/claude"),
             patch("haizen.central.claude_cerebro.subprocess.run", side_effect=falso)]
        for x in p:
            x.start()
        self.addCleanup(lambda: [x.stop() for x in p])
        return chamadas

    def test_le_resposta_ferramentas_e_sessao(self):
        from haizen.central import claude_cerebro
        r = claude_cerebro.ler_saida(STREAM.splitlines())
        self.assertEqual(r["resposta"], "Pronto, marquei.")
        self.assertEqual(r["sessao"], "s-1")
        self.assertIn("listar", r["acoes"])

    def test_volta_continua_a_conversa_e_usa_as_ferramentas_do_jarvis(self):
        from haizen.central import claude_cerebro
        chamadas = self._rodar([(STREAM, ""), (STREAM, "")])
        r = claude_cerebro.responder("ela pagou, marca como recebido")
        self.assertEqual(r, {"resposta": "Pronto, marquei.", "acoes": ["listar", "atualizar"]})
        cmd, kw = chamadas[0]
        self.assertEqual(kw["input"], "ela pagou, marca como recebido")
        self.assertNotIn("--resume", cmd)
        self.assertIn("--strict-mcp-config", cmd)
        permitidas = cmd[cmd.index("--allowedTools") + 1].split(",")
        self.assertIn("mcp__jarvis", permitidas)
        self.assertNotIn("Bash", permitidas)            # o cérebro não roda comandos
        self.assertNotIn("Write", permitidas)
        cfg = json.loads(Path(cmd[cmd.index("--mcp-config") + 1]).read_text(encoding="utf-8"))
        self.assertTrue(cfg["mcpServers"]["jarvis"]["args"][0].endswith("mcp_jarvis.py"))
        self.assertNotIn("ANTHROPIC_API_KEY", kw["env"])  # assinatura, não chave
        claude_cerebro.responder("e agora?")
        cmd2, _ = chamadas[1]
        self.assertEqual(cmd2[cmd2.index("--resume") + 1], "s-1")
        claude_cerebro.nova_conversa()
        self.assertEqual(claude_cerebro.sessao(), "")

    def test_voz_pede_resposta_curta_sem_markdown(self):
        from haizen.central import claude_cerebro
        chamadas = self._rodar([(STREAM, "")])
        claude_cerebro.responder("como está o mês?", por_voz=True)
        cmd = chamadas[0][0]
        persona = Path(cmd[cmd.index("--append-system-prompt-file") + 1]).read_text(encoding="utf-8")
        self.assertIn("OUVIR", persona)

    def test_sem_login_explica_como_conectar(self):
        from haizen.central import claude_cerebro
        erro = json.dumps({"type": "result", "subtype": "success", "is_error": True,
                           "result": "Not logged in · Please run /login"})
        self._rodar([(erro, "")])
        with self.assertRaises(PermissionError) as c:
            claude_cerebro.responder("oi")
        self.assertIn("conectar-claude", str(c.exception))

    def test_cerebro_da_central_responde_pelo_claude(self):
        from haizen.central import cerebro, claude_cerebro
        with patch.object(claude_cerebro, "ativo", return_value=True), \
                patch.object(claude_cerebro, "responder",
                             return_value={"resposta": "Feito.", "acoes": ["agenda_criar"]}) as resp:
            r = cerebro.responder("marca reunião amanhã às 10h", por_voz=True)
        resp.assert_called_once_with("marca reunião amanhã às 10h", True)
        self.assertEqual((r["resposta"], r["acoes"], r["cerebro"]), ("Feito.", ["agenda_criar"], "claude"))
        hist = cerebro.historico(5)
        self.assertEqual([m["papel"] for m in hist], ["usuario", "jarvis"])

    def test_claude_fora_do_ar_cai_no_cerebro_local(self):
        from haizen.central import cerebro, claude_cerebro
        with patch.object(claude_cerebro, "ativo", return_value=True), \
                patch.object(claude_cerebro, "responder", side_effect=RuntimeError("caiu")), \
                patch("haizen.central.atalhos.responder_direto", return_value=("local", ["central"])):
            r = cerebro.responder("oi")
        self.assertEqual(r["resposta"], "local")

    def test_jarvis_cerebro_local_desliga_o_claude(self):
        from haizen.central import claude_cerebro
        with patch.dict(os.environ, {"JARVIS_CEREBRO": "local"}):
            self.assertFalse(claude_cerebro.ativo())


class GuiaDaMarcaTests(Base):
    def setUp(self):
        super().setUp()
        self.marca = self.base / "CLIENTES" / "Viagens Sol"
        self.marca.mkdir(parents=True)

    def test_anota_sem_repetir_e_fica_fora_do_material_do_cliente(self):
        from haizen.producao import guia
        arq = guia.anotar(self.marca, "Nunca usar fundo branco.", "contado ao Jarvis")
        guia.anotar(self.marca, "nunca usar fundo branco.")
        self.assertEqual(arq.parent.name, "JARVIS - para revisar")
        texto = guia.ler_guia(self.marca)
        self.assertEqual(texto.lower().count("nunca usar fundo branco"), 1)

    def test_agente_le_o_guia_e_as_receitas(self):
        from haizen import executor
        from haizen.producao import guia
        guia.anotar(self.marca, "Logo sempre no canto inferior direito.")
        with patch.object(executor, "pasta_haizen", return_value=None):
            txt = executor.instrucoes_da_pasta(self.base / "saida", self.marca, None)
        self.assertIn("Logo sempre no canto inferior direito.", txt)
        self.assertIn("reels-pacote-viagem.md", txt)
        self.assertTrue(any(r["nome"] == "Reels de pacote de viagem" for r in guia.receitas()))

    def test_ajuste_na_revisao_vira_licao_no_guia(self):
        from haizen import servicos, store
        from haizen.central import dados
        c = dados.criar("clientes", {"nome": "Viagens Sol"})
        dados.criar("marcas", {"nome": "Viagens Sol", "cliente_id": c["id"], "pasta": str(self.marca)})
        t = store.criar_trabalho("video", "reels da Viagens Sol", "claude", c["id"])
        store.atualizar(t["id"], status="aguardando_aprovacao")
        servicos.refazer(t["id"], "Texto maior no gancho, a fonte ficou pequena.")
        from haizen.producao import guia
        self.assertIn("Texto maior no gancho", guia.ler_guia(self.marca))


if __name__ == "__main__":
    unittest.main()


class AnexosTests(Base):
    def test_salva_e_nao_deixa_sair_da_pasta(self):
        from haizen.central import anexos
        d = anexos.salvar("../../foto praia.jpg", b"\xff\xd8jpg")
        self.assertEqual(d["nome"], "foto praia.jpg")
        self.assertTrue(d["imagem"])
        self.assertEqual(anexos.caminho(d["id"]).read_bytes(), b"\xff\xd8jpg")
        self.assertEqual(anexos.caminho(d["caminho"]).name, d["id"])     # o Claude passa o caminho
        fora = self.base / "segredo.txt"
        fora.write_text("x")
        with self.assertRaises(KeyError):
            anexos.caminho(str(fora))
        with self.assertRaises(KeyError):
            anexos.caminho("../segredo.txt")

    def test_mensagem_com_foto_vai_para_o_claude_e_fica_no_historico(self):
        from haizen.central import anexos, cerebro, claude_cerebro
        d = anexos.salvar("logo.png", b"png")
        with patch.object(claude_cerebro, "ativo", return_value=True), \
                patch.object(claude_cerebro, "responder", return_value={"resposta": "Vi o logo.", "acoes": ["Read"]}) as resp:
            r = cerebro.responder("", anexos=[d["id"]])
        enviado = resp.call_args[0][0]
        self.assertIn(d["caminho"], enviado)
        self.assertIn("Veja os arquivos", enviado)
        self.assertEqual(r["resposta"], "Vi o logo.")
        self.assertIn(f"[anexo:{d['id']}]", cerebro.historico(5)[0]["texto"])

    def test_material_do_projeto_vai_para_a_pasta_do_projeto(self):
        from haizen import executor, servicos, store
        from haizen.central import anexos, dados
        marca = self.base / "CLIENTES" / "Viagens Sol"
        marca.mkdir(parents=True)
        c = dados.criar("clientes", {"nome": "Viagens Sol"})
        dados.criar("marcas", {"nome": "Viagens Sol", "cliente_id": c["id"], "pasta": str(marca)})
        foto = anexos.salvar("praia.jpg", b"jpg")
        with patch.object(executor, "claude_disponivel", return_value="/bin/claude"):
            r = servicos.criar_projeto("Post com a foto da praia", "Viagens Sol", anexos=[foto["id"]])
        proj = store.projeto(r["projeto"]["id"])
        self.assertIn("praia.jpg", proj["pedido"])
        t = store.criar_trabalho("criativos", "post", "claude", c["id"], projeto_id=proj["id"], etapa=1)
        pasta, _, raiz = executor.pastas_do_trabalho(t)
        destino = executor.copiar_material(t, pasta, raiz)
        self.assertEqual((destino / "praia.jpg").read_bytes(), b"jpg")
        executor.copiar_material(t, pasta, raiz)               # de novo: não duplica
        self.assertEqual(len(list(destino.iterdir())), 1)
        txt = executor.instrucoes_da_pasta(pasta, marca, raiz)
        self.assertIn("00 - Material enviado", txt)
        self.assertEqual(executor.arquivos_da_pasta(str(raiz)), [])    # não aparece como entrega

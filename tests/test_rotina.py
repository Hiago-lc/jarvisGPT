"""Rotina: resumo da manhã, backup, cobranças (só com OK), relatório mensal, checagem de qualidade, segredos."""
import datetime as dt
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class RotinaTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        b = Path(self.dir.name)
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": str(b / "d"), "HAIZEN_DB": str(b / "h.db"),
                                           "HAIZEN_ENTREGAS_DIR": str(b / "e"), "HAIZEN_NOTIFICAR_WINDOWS": "0",
                                           "JARVIS_CEREBRO": "local"})
        self.env.start()
        (b / "d").mkdir()
        from haizen import rotina, store
        from haizen.central import dados
        self.r, self.store, self.dados = rotina, store, dados
        self.r.salvar_config({"backup_pasta": str(b / "bk")})

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def _cliente(self, nome="Loja Exemplo", contato="11999990000"):
        return self.dados.criar("clientes", {"nome": nome, "contato": contato})

    def test_resumo_junta_o_dia(self):
        hoje = dt.date(2026, 11, 6)
        c = self._cliente()
        self.dados.criar("tarefas", {"titulo": "Logo nova", "cliente_id": c["id"], "data_entrega": "2026-11-01"})
        self.dados.criar("receitas", {"cliente_id": c["id"], "descricao": "Fee", "valor": "1500", "vencimento": "2026-11-06"})
        self.dados.criar("despesas", {"descricao": "Adobe", "valor": "120", "vencimento": "2026-11-06"})
        r = self.r.resumo(hoje)
        self.assertIn("Tarefas", r["blocos"])
        self.assertIn("Logo nova", r["texto"])
        self.assertIn("R$ 1.500,00", r["texto"])
        self.assertIn("Pagar hoje: Adobe", r["texto"])
        self.assertTrue(r["titulo"].startswith("Bom dia! Resumo de sexta"))

    def test_resumo_vai_so_para_o_dono(self):
        self.r.salvar_config({"whatsapp_contato": "Eu mesmo"})
        with patch("core.whatsapp_web.run_op", return_value=(True, 200, {})) as op:
            x = self.r.enviar_resumo()
        self.assertTrue(x["whatsapp"])
        self.assertEqual(op.call_args[0][0]["recipient"], "Eu mesmo")

    def test_backup_consistente_e_rotativo(self):
        self._cliente()
        for i in range(4):
            self.r.salvar_config({"backup_dias": 2})
            self.r.fazer_backup(dt.date(2026, 11, 1 + i))
        dias = [b["dia"] for b in self.r.backups()]
        self.assertEqual(dias, ["2026-11-04", "2026-11-03"])
        con = sqlite3.connect(Path(self.r.backups()[0]["pasta"]) / "haizen.db")
        self.assertEqual(con.execute("SELECT nome FROM clientes").fetchone()[0], "Loja Exemplo")
        con.close()
        self.assertTrue((Path(self.r.backups()[0]["pasta"]) / "rotina.json").is_file())

    def test_cobrancas_preparadas_e_so_saem_com_ok(self):
        c = self._cliente()
        self.dados.criar("receitas", {"cliente_id": c["id"], "descricao": "Gestão de tráfego", "valor": "900",
                                      "vencimento": "2026-11-08"})
        r2 = self.dados.criar("receitas", {"cliente_id": c["id"], "descricao": "Site", "valor": "2000",
                                           "vencimento": "2026-11-03"})
        self.r.salvar_config({"cobranca_pagamento": "PIX: chave da HAIZEN"})
        with patch("core.whatsapp_web.run_op") as op:
            self.assertEqual(self.r.gerar_cobrancas(dt.date(2026, 11, 6)), 2)
            self.assertEqual(self.r.gerar_cobrancas(dt.date(2026, 11, 6)), 0)       # não duplica
            op.assert_not_called()                                                     # nada sai sozinho
        cob = {x["etapa"]: x for x in self.r.cobrancas()}
        self.assertIn("vence dia 08/11", cob["antes"]["texto"])
        self.assertIn("PIX: chave da HAIZEN", cob["antes"]["texto"])
        self.assertIn("venceu dia 03/11", cob["atraso"]["texto"])
        self.assertEqual(cob["antes"]["contato"], "11999990000")
        with patch("core.whatsapp_web.run_op", return_value=(True, 200, {})) as op:
            x = self.r.enviar_cobranca(cob["antes"]["id"], texto="Oi! Texto revisado")
        self.assertEqual(x["status"], "enviada")
        self.assertEqual(op.call_args[0][0]["text"], "Oi! Texto revisado")
        with self.assertRaises(ValueError):
            self.r.enviar_cobranca(cob["antes"]["id"])                                  # não envia duas vezes
        self.dados.atualizar("receitas", r2["id"], {"recebido": True})
        self.r.gerar_cobrancas(dt.date(2026, 11, 7))
        self.assertEqual([x["etapa"] for x in self.r.cobrancas()], [])                  # recebeu: some

    def test_agenda_do_dia(self):
        manha = dt.datetime(2026, 11, 2, 8, 5)
        self.assertEqual(self.r.tarefas_devidas(manha), ["backup", "cobranca", "relatorio", "resumo"])
        with patch.object(self.r, "enviar_resumo") as env, patch.object(self.r, "gerar_relatorios_do_mes"):
            self.r.rodar_devidas(manha)
        env.assert_called_once()
        self.assertEqual(self.r.tarefas_devidas(manha), [])
        self.assertEqual(self.r.tarefas_devidas(dt.datetime(2026, 11, 3, 7, 0)), ["backup"])

    def test_relatorio_mensal_pdf_aprovar_e_enviar(self):
        from haizen import trafego
        c = self._cliente()
        with self.store.conexao() as con:
            con.execute("INSERT INTO trafego_contas(id, nome, cliente_id, ativo) VALUES('act_1','Conta',?,1)", (c["id"],))
        marca = Path(self.dir.name) / "Cliente"
        marca.mkdir()
        dados_mes = {"resumo": "Mês bom.", "nome_resultado": "leads",
                     "kpis": {"investimento": 1000, "resultados": 50, "custo_por_resultado": 20},
                     "anterior": {"resultados": 40}, "proximos_passos": ["Testar vídeo"]}
        with patch("haizen.trafego.mensal.coletar", return_value=dados_mes), \
                patch("haizen.trafego.mensal.montar_pdf", side_effect=lambda c, m, d, dest: (dest.parent.mkdir(parents=True, exist_ok=True), dest.write_bytes(b"%PDF"), dest)[2]):
            rel = self.r.gerar_relatorio("act_1", "2026-10")
        self.assertEqual(rel["status"], "pronto")
        self.assertIn("R$ 1.000,00", rel["mensagem"])
        with patch("haizen.store.pasta_da_marca", return_value=str(marca)):
            rel = self.r.aprovar_relatorio(rel["id"])
        self.assertTrue((marca / "Relatórios de tráfego").is_dir())
        with patch("core.whatsapp_web.run_op", return_value=(True, 200, {})) as op:
            rel = self.r.enviar_relatorio(rel["id"], "Segue o relatório")
        self.assertEqual(rel["status"], "enviado")
        self.assertEqual(op.call_args[0][0]["recipient"], "11999990000")
        self.assertIsNotNone(trafego)

    def test_html_do_relatorio(self):
        from haizen.trafego import mensal
        h = mensal.html_relatorio({"nome": "C", "cliente_nome": "Loja <X>"}, "2026-10",
                                  {"kpis": {"investimento": 10, "custo_por_resultado": 2}, "anterior": {"custo_por_resultado": 3}})
        self.assertIn("Outubro de 2026", h)
        self.assertIn("Loja &lt;X&gt;", h)
        self.assertIn("sobe", h)                         # custo caiu = bom


class SegredoTests(unittest.TestCase):
    def test_ida_e_volta_e_formato_antigo(self):
        from haizen import segredo
        f = segredo.fechar("EAAB123")
        self.assertEqual(segredo.abrir(f), "EAAB123")
        self.assertTrue(segredo.fechado(f))
        self.assertEqual(segredo.abrir("EAABantigo"), "EAABantigo")
        self.assertFalse(segredo.fechado("EAABantigo"))


class QualidadeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        b = Path(self.dir.name)
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": str(b / "d"), "HAIZEN_DB": str(b / "h.db")})
        self.env.start()
        (b / "d").mkdir()
        self.pasta = b / "job"
        self.pasta.mkdir()
        (self.pasta / "01.png").write_bytes(b"png")

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_reprovado_corrige_uma_vez(self):
        from haizen import executor
        t = {"id": 7, "agente": "criativos", "pedido": "post", "titulo": "Post"}
        with patch("haizen.executor.rodar_claude", return_value={"result": '{"nota": 5, "aprovado": false, '
                                                                          '"problemas": ["01.png: título pequeno"]}'}) as qa, \
                patch("haizen.executor.executar_producao", return_value={"result": "Corrigido"}) as prod:
            r = executor.checar_qualidade(t, self.pasta, {"result": "Entreguei", "session_id": "S"}, "opus")
        self.assertIn("Read", qa.call_args[0][0])
        self.assertIn("título pequeno", prod.call_args[0][0])
        self.assertEqual(prod.call_args[1]["sessao"], "S")
        self.assertIn("nota 5/10", r["result"])

    def test_aprovado_so_anota(self):
        from haizen import executor
        t = {"id": 7, "agente": "criativos", "pedido": "post"}
        with patch("haizen.executor.rodar_claude", return_value={"result": '{"nota": 9, "aprovado": true, "problemas": []}'}), \
                patch("haizen.executor.executar_producao") as prod:
            r = executor.checar_qualidade(t, self.pasta, {"result": "Entreguei", "session_id": "S"})
        prod.assert_not_called()
        self.assertIn("nota 9/10", r["result"])

    def test_conhecimento_entra_no_claude_md(self):
        from haizen import executor
        txt = executor.instrucoes_da_pasta(self.pasta, None, None, "video")
        self.assertIn("Conhecimento da sua função", txt)
        self.assertIn("window.timeline", txt)
        self.assertIn("legendar", txt)


if __name__ == "__main__":
    unittest.main()

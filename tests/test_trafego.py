"""Gestor de tráfego: análise só com leitura, propostas, aprovação e aplicação."""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ANALISE = {
    "situacao": "atencao",
    "resumo": "Custo por conversa subiu 35% na semana.",
    "metricas": {"gasto_7d": 700, "resultados_7d": 40, "custo_resultado_7d": 17.5, "nome_resultado": "conversas"},
    "alertas": ["Frequência 3,8 no conjunto Remarketing"],
    "acoes": [
        {"tipo": "pausar", "nivel": "anuncio", "alvo_id": "120200", "alvo_nome": "Vídeo antigo",
         "de": "ACTIVE", "para": "PAUSED", "motivo": "R$ 90 sem conversa", "prioridade": "alta"},
        {"tipo": "orcamento", "nivel": "conjunto", "alvo_id": "120300", "alvo_nome": "Interesses viagem",
         "de": "50", "para": "60", "motivo": "custo 30% abaixo da meta há 5 dias"},
        {"tipo": "criativo", "nivel": "conjunto", "alvo_id": "120400", "alvo_nome": "Remarketing",
         "motivo": "fadiga", "para": "2 vídeos curtos com depoimento"},
        {"tipo": "inventado", "alvo_nome": "x", "motivo": "y"},
    ],
    "relatorio": "## Relatório\n- tudo",
}


class TrafegoTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": str(base / "dados"), "HAIZEN_DB": str(base / "h.db"),
                                           "HAIZEN_TRAFEGO_AGENDA": "0"})
        self.env.start()
        from haizen import trafego
        self.t = trafego
        self.chamadas = []
        self.respostas = []

        def falso(args, prompt, pasta, timeout, env=None):
            self.chamadas.append((args, prompt))
            return self.respostas.pop(0)
        self.p = patch("haizen.executor._rodar_claude", side_effect=falso)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.env.stop()
        self.dir.cleanup()

    def _permitidas(self, i=-1):
        args = self.chamadas[i][0]
        return args[args.index("--allowedTools") + 1].split(",")

    def _conectar(self):
        from haizen.central import dados
        dados.criar("clientes", {"nome": "Viagens Sol"})
        self.respostas.append(json.dumps({"ferramentas": ["ads_get_ad_entities", "ads_get_new_thing", "ads_update_entity"],
                                          "contas": [{"id": "act_1", "nome": "Viagens Sol - Anúncios", "moeda": "BRL"},
                                                     {"id": "2", "nome": "Outra conta"}]}))
        return self.t.descobrir()

    def test_conectar_traz_contas_e_liga_ao_cliente(self):
        r = self._conectar()
        ids = {c["id"]: c for c in r["contas"]}
        self.assertEqual(set(ids), {"act_1", "act_2"})
        self.assertEqual(ids["act_1"]["cliente_nome"], "Viagens Sol")
        self.assertEqual(self._permitidas(), ["mcp__meta-ads__ads_get_ad_accounts"])
        leitura = self.t.ferramentas_leitura()
        self.assertIn("mcp__meta-ads__ads_get_new_thing", leitura)       # descoberta e de leitura
        self.assertNotIn("mcp__meta-ads__ads_update_entity", leitura)

    def test_sem_conexao_avisa_como_conectar(self):
        self.respostas.append('{"erro": "SEM_CONEXAO_META"}')
        with self.assertRaises(ConnectionError) as c:
            self.t.descobrir()
        self.assertIn("conectar-meta.bat", str(c.exception))

    def test_analise_so_le_e_vira_propostas(self):
        self._conectar()
        self.t.atualizar_conta("act_1", {"ativo": True, "meta_cpa": "15,00", "verba_mensal": "3.000"})
        self.respostas.append("```json\n" + json.dumps(ANALISE) + "\n```")
        an = self.t.analisar_conta("act_1")
        self.assertEqual(an["situacao"], "atencao")
        permitidas = self._permitidas()
        self.assertTrue(all(p.startswith("mcp__meta-ads__ads_get") or p.startswith("mcp__meta-ads__ads_insights")
                            or p.startswith("mcp__meta-ads__ads_library") for p in permitidas))
        prompt = self.chamadas[-1][1]
        self.assertIn("R$ 15,00", prompt)
        self.assertIn("verba mensal: R$ 3.000,00", prompt)
        self.assertIn("Nunca pause o único anúncio", prompt)              # o playbook vai junto
        pend = self.t.acoes("proposta")
        self.assertEqual(len(pend), 4)
        self.assertEqual({a["tipo"] for a in pend}, {"pausar", "orcamento", "criativo", "manual"})
        # A análise seguinte substitui as propostas não decididas e conhece o histórico.
        self.respostas.append(json.dumps({**ANALISE, "acoes": []}))
        self.t.analisar_conta("act_1")
        self.assertEqual(self.t.acoes("proposta"), [])
        self.assertIn('pausar anuncio "Vídeo antigo" de ACTIVE para PAUSED', self.chamadas[-1][1])

    def test_aprovar_aplica_so_com_permissao_de_escrita_depois(self):
        self._conectar()
        self.respostas.append(json.dumps(ANALISE))
        self.t.analisar_conta("act_1")
        orc = next(a for a in self.t.acoes("proposta") if a["tipo"] == "orcamento")
        self.respostas.append('{"ok": true, "detalhe": "Orçamento de 50 para 60, conferido."}')
        feito = self.t.aprovar(orc["id"], em_segundo_plano=False)
        self.assertEqual(feito["status"], "aplicada")
        permitidas = self._permitidas()
        self.assertIn("mcp__meta-ads__ads_update_entity", permitidas)
        self.assertNotIn("mcp__meta-ads__ads_create_campaign", permitidas)
        self.assertIn("120300", self.chamadas[-1][1])
        self.assertIn("NÃO altere", self.chamadas[-1][1])
        with self.assertRaises(ValueError):
            self.t.aprovar(orc["id"])                                   # não aplica duas vezes

    def test_falha_ao_aplicar_fica_registrada(self):
        self._conectar()
        a = self.t.propor("act_1", "pausar", "Vídeo antigo", "sem resultado", "anuncio", "120200")
        self.respostas.append('{"ok": false, "detalhe": "o anúncio já estava pausado"}')
        r = self.t.aprovar(a["id"], em_segundo_plano=False)
        self.assertEqual((r["status"], r["resultado"]), ("falhou", "o anúncio já estava pausado"))

    def test_manual_e_rejeitar_nao_chamam_o_claude(self):
        self._conectar()
        n = len(self.chamadas)
        a = self.t.propor("act_1", "manual", "Página", "checkout lento")
        self.assertEqual(self.t.aprovar(a["id"])["status"], "anotada")
        b = self.t.propor("act_1", "pausar", "X", "y", "anuncio", "1")
        self.assertEqual(self.t.rejeitar(b["id"])["status"], "rejeitada")
        self.assertEqual(len(self.chamadas), n)

    def test_criativo_aprovado_vira_projeto(self):
        self._conectar()
        a = self.t.propor("act_1", "criativo", "Remarketing", "fadiga", "conjunto", "9", para="2 vídeos")
        with patch("haizen.worker.iniciar"), patch("haizen.servicos.criar_projeto",
                                                   return_value={"projeto": {"id": 7}, "aviso": ""}) as cp:
            r = self.t.aprovar(a["id"])
        self.assertEqual(r["status"], "aplicada")
        self.assertIn("projeto 7", r["resultado"])
        self.assertEqual(cp.call_args[0][1], "Viagens Sol")

    def test_horario_e_resumo(self):
        self._conectar()
        self.t.salvar_config({"horario": "07:30"})
        self.assertFalse(self.t.hora_de_rodar(dt.datetime(2026, 11, 4, 8, 0)))       # nenhuma conta ativa
        self.t.atualizar_conta("act_1", {"ativo": True})
        self.assertFalse(self.t.hora_de_rodar(dt.datetime(2026, 11, 4, 7, 0)))
        self.assertTrue(self.t.hora_de_rodar(dt.datetime(2026, 11, 4, 7, 31)))
        self.respostas.append(json.dumps(ANALISE))
        with patch.object(self.t, "enviar_whatsapp_resumo") as zap:
            self.t.rodada_diaria()
        zap.assert_called_once()
        self.assertFalse(self.t.hora_de_rodar(dt.datetime.combine(dt.date.today(), dt.time(9, 0))))
        texto = self.t.resumo_texto()
        self.assertIn("Viagens Sol", texto)
        self.assertIn("esperando sua aprovação", texto)
        with self.assertRaises(ValueError):
            self.t.salvar_config({"horario": "25:00"})

    def test_whatsapp_so_para_o_contato_configurado(self):
        from core import whatsapp_web
        with patch.object(whatsapp_web, "run_op", return_value=(True, 0, "ok")) as op:
            self.assertFalse(self.t.enviar_whatsapp_resumo())                     # desligado
            self.t.salvar_config({"whatsapp_ativo": True, "whatsapp_contato": "Eu mesmo"})
            self.assertTrue(self.t.enviar_whatsapp_resumo())
        self.assertEqual(op.call_args[0][0]["recipient"], "Eu mesmo")

    def test_cerebro_le_o_meta_so_depois_de_conectar(self):
        from haizen.central import claude_cerebro
        self.assertFalse(any("meta-ads" in p for p in claude_cerebro.permitidas()))
        self._conectar()
        p = claude_cerebro.permitidas()
        self.assertIn("mcp__meta-ads__ads_get_ad_entities", p)
        self.assertFalse(any(x.endswith(("update_entity", "activate_entity")) for x in p))


if __name__ == "__main__":
    unittest.main()

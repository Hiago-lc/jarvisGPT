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


from contextlib import contextmanager


@contextmanager
def store_patch_anexo(arquivo):
    """Um anexo falso apontando para `arquivo`."""
    with patch("haizen.central.anexos.varios", return_value=[{"id": "x", "nome": arquivo.name,
                                                               "caminho": str(arquivo)}]):
        yield ["x"]


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

        def falso(args, prompt, pasta, timeout, env=None, **kw):
            self.chamadas.append((args, prompt))
            return self.respostas.pop(0)
        self.p = patch("haizen.executor._rodar_claude", side_effect=falso)
        self.p.start()
        self.enviadas = []
        self.pi = patch("haizen.trafego.envio.subir_imagem",
                        side_effect=lambda conta, arq: (self.enviadas.append(arq.name), {"image_hash": "HASH-" + arq.stem,
                                                                                          "image_url": ""})[1])
        self.pi.start()
        self.pt = patch("haizen.trafego.envio.token", return_value="EAA" + "x" * 120)
        self.pt.start()

    def tearDown(self):
        self.pt.stop()
        self.pi.stop()
        self.p.stop()
        self.env.stop()
        self.dir.cleanup()

    def _permitidas(self, i=-1):
        args = self.chamadas[i][0]
        return args[args.index("--allowedTools") + 1].split(",")

    def _conectar(self):
        from haizen.central import dados
        dados.criar("clientes", {"nome": "Viagens Sol"})
        contas = {"data": [{"id": "act_1", "name": "Viagens Sol - Anúncios", "currency": "BRL", "account_status": 1},
                           {"id": "2", "name": "Outra conta", "account_status": 2}]}
        with patch("haizen.trafego.envio._http", return_value=contas):
            return self.t.descobrir()

    def test_conectar_traz_contas_e_liga_ao_cliente(self):
        r = self._conectar()
        ids = {c["id"]: c for c in r["contas"]}
        self.assertEqual(set(ids), {"act_1", "act_2"})
        self.assertEqual(ids["act_1"]["cliente_nome"], "Viagens Sol")
        self.assertEqual(self.chamadas, [])                      # conectar não gasta Claude
        leitura = self.t.ferramentas_leitura()
        self.assertIn("mcp__meta__ads_get_ad_entities", leitura)
        self.assertNotIn("mcp__meta__ads_update_entity", leitura)

    def test_sem_conexao_avisa_como_conectar(self):
        from haizen.trafego import envio
        with patch("haizen.trafego.envio._http", side_effect=envio.ErroEnvio("o token do Meta Ads venceu")):
            with self.assertRaises(ConnectionError) as c:
                self.t.descobrir()
        self.assertIn("Tráfego → Configurar", str(c.exception))

    def test_analise_so_le_e_vira_propostas(self):
        self._conectar()
        self.t.atualizar_conta("act_1", {"ativo": True, "meta_cpa": "15,00", "verba_mensal": "3.000"})
        self.respostas.append("```json\n" + json.dumps(ANALISE) + "\n```")
        an = self.t.analisar_conta("act_1")
        self.assertEqual(an["situacao"], "atencao")
        permitidas = self._permitidas()
        self.assertTrue(all(p.startswith(("mcp__meta__ads_get", "mcp__meta__ads_insights", "mcp__meta__ads_graph_get"))
                            for p in permitidas))
        args = self.chamadas[-1][0]
        self.assertIn("--strict-mcp-config", args)             # só as ferramentas próprias do Jarvis
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
        self.assertIn("mcp__meta__ads_update_entity", permitidas)
        self.assertNotIn("mcp__meta__ads_create_campaign", permitidas)
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
            self.assertFalse(self.t.enviar_whatsapp_resumo())                     # vai no resumo da manhã
            from haizen import rotina
            rotina.salvar_config({"resumo_whatsapp": False})
            self.assertTrue(self.t.enviar_whatsapp_resumo())
        self.assertEqual(op.call_args[0][0]["recipient"], "Eu mesmo")

    def test_diagnostico_e_publico_com_detalhes(self):
        self._conectar()
        self.respostas.append(json.dumps({**ANALISE,
            "diagnostico": {"criativos": "O vídeo com depoimento ganha.", "funil": "Falta remarketing."},
            "ranking_criativos": [{"alvo_id": "1", "nome": "Vídeo depoimento", "veredito": "escalar"}],
            "acoes": [{"tipo": "publico", "nivel": "conjunto", "alvo_id": "555", "alvo_nome": "Interesses",
                       "detalhes": {"idade": "25-45", "excluir": "compradores 30 dias"}, "motivo": "CPM alto"},
                      {"tipo": "subir_criativo", "alvo_nome": "x", "motivo": "y"}]}))
        an = self.t.analisar_conta("act_1")
        self.assertEqual(self.t.analise(an["id"])["diagnostico"]["ranking"][0]["veredito"], "escalar")
        self.assertTrue(self.t.ultimas_analises()["act_1"]["tem_diagnostico"])
        tipos = {a["tipo"]: a for a in self.t.acoes("proposta")}
        self.assertIn("criativo", tipos)                      # subir só pelo fluxo próprio
        pub = tipos["publico"]
        self.respostas.append('{"ok": true, "detalhe": "idade 25-45 e exclusão aplicadas"}')
        self.assertEqual(self.t.aprovar(pub["id"], em_segundo_plano=False)["status"], "aplicada")
        self.assertIn("25-45", self.chamadas[-1][1])
        self.assertIn("mcp__meta__ads_update_entity", self._permitidas())
        self.assertNotIn("mcp__meta__ads_create_ad", self._permitidas())

    def test_subir_criativos_com_legendas_e_aprovacao(self):
        from haizen import store
        self._conectar()
        pasta = Path(self.dir.name) / "CLIENTES" / "Viagens Sol" / "JARVIS - para revisar" / "01 - criativos"
        pasta.mkdir(parents=True)
        (pasta / "01 - Feed.png").write_bytes(b"png")
        (pasta / "02 - Stories.png").write_bytes(b"png")
        (pasta / "Textos.txt").write_text("Feed: Porto Seguro, últimas vagas", encoding="utf-8")
        t = store.criar_trabalho("criativos", "posts", "claude", 1)
        store.atualizar(t["id"], status="aguardando_aprovacao", pasta=str(pasta))
        self.assertEqual([x["id"] for x in self.t.trabalhos_com_pecas()], [t["id"]])
        feed = (pasta / "01 - Feed.png").as_posix()
        self.respostas.append(json.dumps({"alvo_id": "777", "alvo_nome": "Remarketing", "campanha": "Black Friday",
            "page_id": "9", "destino": "WhatsApp", "cta": "WHATSAPP_MESSAGE", "motivo": "melhor conjunto",
            "pecas": [{"arquivo": feed, "texto_principal": "Últimas vagas para Porto Seguro!", "titulo": "Porto Seguro"},
                      {"arquivo": "/outro/lugar.png", "texto_principal": "x"}]}))
        a = self.t.preparar_criativos("act_1", "no Remarketing", t["id"])
        args, prompt = self.chamadas[-1]
        self.assertIn("Read", self._permitidas())
        self.assertFalse(any("create" in p for p in self._permitidas()))       # preparar não cria nada
        self.assertIn(str(pasta), args)                                        # pode abrir as peças
        self.assertIn("Porto Seguro, últimas vagas", prompt)                    # usa os textos da equipe
        d = json.loads(a["detalhes"])
        self.assertEqual(len(d["pecas"]), 1)                                   # só arquivos da lista
        self.assertEqual(self.t.arquivo_da_acao(a["id"], 0), pasta / "01 - Feed.png")
        with self.assertRaises(KeyError):
            self.t.arquivo_da_acao(a["id"], 5)
        # Aprovar sem ativar: cria pausado, sem permissão de ativar.
        self.respostas.append('{"ok": true, "detalhe": "1 anúncio criado pausado"}')
        r = self.t.aprovar(a["id"], em_segundo_plano=False)
        self.assertEqual(r["status"], "aplicada")
        p = self._permitidas()
        self.assertIn("mcp__meta__ads_create_ad", p)
        self.assertNotIn("mcp__meta__ads_activate_entity", p)
        self.assertIn("NÃO ative nada", self.chamadas[-1][1])
        self.assertIn("Últimas vagas para Porto Seguro!", self.chamadas[-1][1])
        self.assertIn("image_hash HASH-01 - Feed", self.chamadas[-1][1])          # a peça já foi enviada à conta
        self.assertEqual(self.enviadas, ["01 - Feed.png"])

    def test_subir_e_ativar_e_falta_de_upload(self):
        self._conectar()
        img = Path(self.dir.name) / "peca.jpg"
        img.write_bytes(b"jpg")
        with store_patch_anexo(img) as ids:
            self.respostas.append(json.dumps({"alvo_id": "1", "alvo_nome": "C", "pecas": [
                {"arquivo": img.as_posix(), "texto_principal": "t", "titulo": "t"}]}))
            a = self.t.preparar_criativos("act_1", "", None, ids)
        self.respostas.append('{"ok": false, "detalhe": "SEM_UPLOAD: pede image_hash"}')
        r = self.t.aprovar(a["id"], em_segundo_plano=False, ativar=True)
        self.assertIn("mcp__meta__ads_activate_entity", self._permitidas())
        self.assertIn("ATIVE o que criou", self.chamadas[-1][1])
        self.assertEqual(r["status"], "falhou")
        self.assertIn("token do Meta Ads", r["resultado"])

    def test_editar_proposta_pelo_chat_e_reenvio_so_do_novo(self):
        self._conectar()
        a1, a2 = Path(self.dir.name) / "a.jpg", Path(self.dir.name) / "b.jpg"
        a1.write_bytes(b"jpg")
        a2.write_bytes(b"jpg")
        with store_patch_anexo(a1) as ids:
            self.respostas.append(json.dumps({"alvo_id": "1", "alvo_nome": "C", "pecas": [
                {"arquivo": a1.as_posix(), "texto_principal": "antigo", "titulo": "t"}]}))
            a = self.t.preparar_criativos("act_1", "", None, ids)
        self.respostas.append('{"ok": false, "detalhe": "conjunto pausado"}')
        self.assertEqual(self.t.aprovar(a["id"], em_segundo_plano=False)["status"], "falhou")
        self.assertEqual(self.enviadas, ["a.jpg"])
        with patch("haizen.central.anexos.caminho", return_value=a2):
            e = self.t.editar(a["id"], {"alvo_id": "52591677986663", "alvo_nome": "Vendas | Público engajado 60 dias",
                                        "nota": "trocar conjunto e acrescentar peça", "detalhes": {"cta": "SHOP_NOW", "pecas": [
                {"arquivo": a1.as_posix(), "texto_principal": "Black Friday Loja", "titulo": "Kit 4 por R$ 399"},
                {"arquivo": "[anexo:20261111-b.jpg]", "texto_principal": "Polos", "titulo": "2 por R$ 398"}]}})
        self.assertEqual((e["status"], e["alvo_id"]), ("proposta", "52591677986663"))
        d = json.loads(e["detalhes"])
        self.assertEqual(d["arquivos"], [str(a1), str(a2)])
        self.assertEqual(d["pecas"][0]["image_hash"], "HASH-a")                 # já enviada: guardada
        self.assertEqual(d["cta"], "SHOP_NOW")
        self.respostas.append('{"ok": true, "detalhe": "2 anúncios criados"}')
        r = self.t.aprovar(a["id"], em_segundo_plano=False)
        self.assertEqual(r["status"], "aplicada")
        self.assertEqual(self.enviadas, ["a.jpg", "b.jpg"])                       # só a nova subiu
        self.assertIn("Black Friday Loja", self.chamadas[-1][1])
        self.assertIn("52591677986663", self.chamadas[-1][1])
        with self.assertRaises(ValueError):
            self.t.editar(a["id"], {"motivo": "x"})                               # aplicada não edita

    def test_sem_token_falha_antes_de_chamar_o_claude(self):
        from haizen.trafego import envio
        self._conectar()
        img = Path(self.dir.name) / "p.jpg"
        img.write_bytes(b"jpg")
        with store_patch_anexo(img) as ids:
            self.respostas.append(json.dumps({"alvo_id": "1", "alvo_nome": "C", "pecas": [
                {"arquivo": img.as_posix(), "texto_principal": "t", "titulo": "t"}]}))
            a = self.t.preparar_criativos("act_1", "", None, ids)
        n = len(self.chamadas)
        with patch.object(envio, "subir_imagem", side_effect=envio.ErroEnvio("sem token do Meta Ads (Tráfego → Configurar)")), \
                patch.object(envio, "endereco_publico", side_effect=envio.ErroEnvio("sem página")):
            r = self.t.aprovar(a["id"], em_segundo_plano=False)
        self.assertEqual(r["status"], "falhou")
        self.assertIn("token do Meta Ads", r["resultado"])
        self.assertEqual(len(self.chamadas), n)

    def test_estrutura_cria_anuncios_e_retoma_de_onde_parou(self):
        self._conectar()
        a = self.t.propor("act_1", "estrutura", "VENDAS | Advantage+", "consolidar", "campanha",
                          detalhes={"anuncios": "criativos 111 e 222"})
        self.respostas.append('{"ok": false, "detalhe": "Criei a campanha 900 e o conjunto 901; faltaram os anúncios."}')
        r = self.t.aprovar(a["id"], em_segundo_plano=False)
        self.assertIn("mcp__meta__ads_create_ad", self._permitidas())
        self.assertEqual(r["status"], "falhou")
        self.respostas.append('{"ok": true, "detalhe": "anúncios criados no conjunto 901"}')
        self.assertEqual(self.t.aprovar(a["id"], em_segundo_plano=False)["status"], "aplicada")
        self.assertIn("NÃO recrie", self.chamadas[-1][1])
        self.assertIn("campanha 900", self.chamadas[-1][1])
        self.assertIn("LIBERADAS nesta aplicação: ads_create_campaign, ads_create_ad_set, ads_create_ad", self.chamadas[-1][1])

    def test_orcamento_nao_ativa_nada_e_nota_do_dono(self):
        self._conectar()
        a = self.t.propor("act_1", "orcamento", "Topo", "folga", "conjunto", "555", de="30", para="22")
        self.respostas.append('{"ok": false, "detalhe": "orçamento atual diferente"}')
        self.t.aprovar(a["id"], em_segundo_plano=False)
        self.assertIn("mcp__meta__ads_update_entity", self._permitidas())
        self.assertNotIn("mcp__meta__ads_activate_entity", self._permitidas())
        self.respostas.append('{"ok": true, "detalhe": "alterado"}')
        self.t.aprovar(a["id"], em_segundo_plano=False, nota="pode mudar mesmo assim")
        self.assertIn("RESPOSTA DO DONO PARA ESTA TENTATIVA", self.chamadas[-1][1])
        self.assertIn("pode mudar mesmo assim", self.chamadas[-1][1])

    def test_cerebro_le_o_meta_so_depois_de_conectar(self):
        from haizen.central import claude_cerebro
        self.assertFalse(any("meta-ads" in p for p in claude_cerebro.permitidas()))
        self._conectar()
        p = claude_cerebro.permitidas()
        self.assertIn("mcp__meta__ads_get_ad_entities", p)
        self.assertFalse(any(x.endswith(("update_entity", "activate_entity")) for x in p))


if __name__ == "__main__":
    unittest.main()


class EnvioMetaTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": self.dir.name})
        self.env.start()
        from haizen.trafego import envio
        self.e = envio

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_token_imagem_video_e_reaproveita(self):
        import urllib.parse as up
        with self.assertRaises(ValueError):
            self.e.salvar_token("abc")
        self.e.salvar_token("EAA" + "y" * 150)
        self.assertTrue(self.e.token_proprio().startswith("EAA"))
        img = Path(self.dir.name) / "a.png"
        img.write_bytes(b"\x89PNG")
        vid = Path(self.dir.name) / "v.mp4"
        vid.write_bytes(b"mp4")
        chamadas = []

        def http(metodo, url, dados=None, cab=None, timeout=300):
            chamadas.append((metodo, url, dados))
            if "/adimages" in url:
                f = dict(up.parse_qsl(dados.decode()))
                assert f["access_token"].startswith("EAA") and f["bytes"]
                return {"images": {"a.png": {"hash": "H1", "url": "https://x/a.png"}}}
            if "/advideos" in url:
                return {"id": "V1"}
            if "/V1?" in url:
                return {"status": {"video_status": "ready"}, "picture": "https://x/thumb.jpg"}
            if "debug_token" in url:
                return {"data": {"is_valid": True, "scopes": ["ads_management"], "expires_at": 0}}
            return {}
        with patch.object(self.e, "_http", side_effect=http):
            pecas = [{"arquivo": str(img)}, {"arquivo": str(vid), "titulo": "Vídeo"}, {"arquivo": str(img), "image_hash": "JA"}]
            self.e.preparar_pecas("123", pecas)
            self.assertTrue(self.e.situacao()["pronto"])
        self.assertEqual(pecas[0]["image_hash"], "H1")
        self.assertEqual((pecas[1]["video_id"], pecas[1]["thumbnail_url"]), ("V1", "https://x/thumb.jpg"))
        self.assertIn("/act_123/adimages", chamadas[0][1])
        self.assertEqual(sum(1 for c in chamadas if "/adimages" in c[1]), 1)       # a que já tinha hash não sobe

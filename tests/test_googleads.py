"""Google Ads: OAuth no PC, contas pela MCC, métricas, propostas validadas e aplicação só com aprovação."""
import datetime as dt
import json
import os
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

HOJE = dt.date(2026, 11, 10)


def _met(custo, cliques, conv, valor=0, imp=1000):
    return {"costMicros": str(int(custo * 1_000_000)), "clicks": str(cliques), "conversions": conv,
            "conversionsValue": valor, "impressions": str(imp)}


class GoogleAdsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        b = Path(self.dir.name)
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": str(b / "d"), "HAIZEN_DB": str(b / "h.db"),
                                           "HAIZEN_NOTIFICAR_WINDOWS": "0", "JARVIS_CEREBRO": "local",
                                           "HAIZEN_GADS_API": ""})
        self.env.start()
        (b / "d").mkdir()
        from haizen import googleads
        from haizen.googleads import api
        self.ga, self.api = googleads, api
        self.chamadas = []
        self.versao_off = "v25"

        def http(metodo, url, dados=None, cab=None, timeout=60):
            self.chamadas.append((metodo, url, dados, cab or {}))
            if url.startswith("https://oauth2.googleapis.com/token"):
                f = dict(urllib.parse.parse_qsl(dados.decode()))
                if f["grant_type"] == "authorization_code":
                    assert f["code_verifier"]
                    return {"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3599}
                return {"access_token": "AT2", "expires_in": 3599}
            if f"/{self.versao_off}/" in url:
                raise api.ErroGoogleAds("HTTP 404")
            if url.endswith("customers:listAccessibleCustomers"):
                return {"resourceNames": ["customers/1112223333"]}
            corpo = json.loads(dados or b"{}")
            q = corpo.get("query", "")
            if "FROM customer_client" in q:
                return {"results": [
                    {"customerClient": {"id": "1112223333", "descriptiveName": "HAIZEN MCC", "manager": True, "status": "ENABLED"}},
                    {"customerClient": {"id": "4445556666", "descriptiveName": "Loja Exemplo", "manager": False,
                                        "status": "ENABLED", "currencyCode": "BRL"}}]}
            if "FROM campaign WHERE" in q and "campaign_budget.amount_micros" in q:
                return {"results": [
                    {"campaign": {"id": "11", "name": "Search Marca", "status": "ENABLED", "advertisingChannelType": "SEARCH"},
                     "campaignBudget": {"amountMicros": "100000000", "resourceName": "customers/4445556666/campaignBudgets/91"},
                     "metrics": {**_met(2400, 800, 60, 12000), "searchBudgetLostImpressionShare": 0.22}},
                    {"campaign": {"id": "12", "name": "PMax", "status": "ENABLED", "advertisingChannelType": "PERFORMANCE_MAX"},
                     "campaignBudget": {"amountMicros": "50000000", "resourceName": "customers/4445556666/campaignBudgets/92",
                                        "explicitlyShared": True},
                     "metrics": _met(1500, 300, 5)}]}
            if "FROM campaign WHERE" in q:
                return {"results": [{"campaign": {"id": "11"}, "metrics": _met(2000, 700, 40, 9000)}]}
            if "segments.date," in q:
                return {"results": [{"segments": {"date": (HOJE - dt.timedelta(days=1)).isoformat()}, "metrics": _met(130, 40, 3)}]}
            if "FROM customer WHERE" in q:
                return {"results": [{"metrics": _met(900, 300, 20)}]}
            if "FROM keyword_view" in q:
                return {"results": [{"adGroupCriterion": {"resourceName": "customers/4445556666/adGroupCriteria/5~7",
                                                          "keyword": {"text": "loja exemplo", "matchType": "PHRASE"},
                                                          "status": "ENABLED", "qualityInfo": {"qualityScore": 3}},
                                     "campaign": {"id": "11", "name": "Search Marca"}, "adGroup": {"name": "G1"},
                                     "metrics": _met(300, 90, 0)}]}
            if "FROM search_term_view" in q:
                return {"results": [
                    {"searchTermView": {"searchTerm": "vagas emprego loja"}, "campaign": {"id": "11", "name": "Search Marca"},
                     "metrics": _met(120, 50, 0)},
                    {"searchTermView": {"searchTerm": "comprar loja exemplo"}, "campaign": {"id": "11", "name": "Search Marca"},
                     "metrics": _met(200, 70, 9)}]}
            if "FROM ad_group_ad" in q:
                return {"results": []}
            if url.endswith("geoTargetConstants:suggest"):
                return {"geoTargetConstantSuggestions": [
                    {"searchTerm": "São Paulo", "geoTargetConstant": {"resourceName": "geoTargetConstants/1001773",
                                                                       "name": "São Paulo", "status": "ENABLED"}}]}
            if url.endswith("googleAds:mutate"):
                return {"mutateOperationResponses": [{"campaignBudgetResult": {}},
                                                     {"campaignResult": {"resourceName": "customers/4445556666/campaigns/77"}}]}
            if url.endswith(":mutate"):
                return {"results": [{"resourceName": "ok"}]}
            return {}
        self.p = patch.object(api, "_http", side_effect=http)
        self.p.start()
        self.respostas = []

        def claude(args, prompt, pasta, timeout, env=None, **kw):
            self.prompt = (prompt, kw)
            return self.respostas.pop(0)
        self.pc = patch("haizen.executor._rodar_claude", side_effect=claude)
        self.pc.start()

    def tearDown(self):
        self.pc.stop()
        self.p.stop()
        self.env.stop()
        self.dir.cleanup()

    def _conectar(self):
        self.ga.salvar_config({"client_id": json.dumps({"installed": {"client_id": "123-abc.apps.googleusercontent.com",
                                                                       "client_secret": "GOCSPX-segredo123"}})})
        url = self.api.url_autorizacao("http://127.0.0.1:8765/oauth/google-ads")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        self.assertEqual((q["scope"], q["code_challenge_method"], q["access_type"]),
                         ("https://www.googleapis.com/auth/adwords https://www.googleapis.com/auth/youtube.upload", "S256", "offline"))
        with self.assertRaises(ValueError):
            self.api.concluir("state-errado", "code")
        self.api.concluir(q["state"], "CODE")
        self.assertTrue(self.api.conectado())
        self.ga.sincronizar_contas()
        return self.ga.editar_conta("4445556666", {"ativo": True, "meta_cpa": "45"})

    def test_conexao_mcc_e_segredo_fora_do_banco(self):
        c = self._conectar()
        self.assertEqual((c["nome"], c["login_id"], c["id_formatado"]), ("Loja Exemplo", "1112223333", "444-555-6666"))
        self.assertEqual([x["id"] for x in self.ga.contas()], ["4445556666"])      # a MCC não entra
        self.assertNotIn(b"RT1", (Path(self.dir.name) / "h.db").read_bytes())
        self.assertNotIn("GOCSPX", json.dumps(self.ga.painel()))
        busca = [x for x in self.chamadas if "googleAds:search" in x[1]][-1]
        self.assertEqual(busca[3]["login-customer-id"], "1112223333")
        self.assertIn("/v24/", busca[1])                                           # v25 fora do ar: caiu para a v24

    def test_metricas(self):
        c = self._conectar()
        m = self.ga.coletar(c, HOJE)
        self.assertEqual(m["ult30"]["custo"], 3900)
        self.assertEqual(m["campanhas"][0]["cpa"], 40)
        self.assertEqual(m["campanhas"][0]["perda_orcamento"], 22.0)
        self.assertEqual(m["campanhas"][0]["var_cpa"], -20.0)                      # 50 → 40
        self.assertEqual([t["termo"] for t in m["termos_sem_conversao"]], ["vagas emprego loja"])
        self.assertEqual(m["desperdicio_termos"], 120)
        self.assertEqual(m["ontem"]["custo"], 130)
        self.assertFalse(m["rastreamento_suspeito"])

    def test_analise_valida_e_aplica_so_com_aprovacao(self):
        c = self._conectar()
        self.respostas.append(json.dumps({"resumo": "Search com CPA bom e limitado por orçamento.", "saude": 74,
                                          "alertas": ["Índice de qualidade 3 em 'loja exemplo'"], "acoes": [
            {"tipo": "orcamento", "titulo": "Subir verba Search", "detalhes": {"campanha_id": "11", "orcamento_diario": 125}},
            {"tipo": "orcamento", "titulo": "exagero", "detalhes": {"campanha_id": "11", "orcamento_diario": 400}},
            {"tipo": "orcamento", "titulo": "compartilhado", "detalhes": {"campanha_id": "12", "orcamento_diario": 60}},
            {"tipo": "negativar_termos", "titulo": "Negativar emprego",
             "detalhes": {"campanha_id": "11", "termos": ["Vagas  Emprego", "vagas emprego", "grátis"]}},
            {"tipo": "pausar_campanha", "titulo": "inventada", "detalhes": {"campanha_id": "999"}}]}))
        an = self.ga.analisar(c["id"], HOJE)
        self.assertEqual(an["saude"], 74)
        self.assertIn("CPA alvo: 45", self.prompt[0])
        self.assertEqual(self.prompt[1]["origem"], "googleads")
        props = {a["titulo"]: a for a in self.ga.acoes(c["id"])}
        self.assertEqual(set(props), {"Subir verba Search", "Negativar emprego"})
        self.assertFalse([x for x in self.chamadas if x[1].endswith(":mutate")])     # nada aplicado sozinho
        neg = props["Negativar emprego"]
        self.assertEqual(neg["detalhes"]["termos"], ["vagas emprego", "grátis"])
        r = self.ga.aprovar(props["Subir verba Search"]["id"])
        self.assertEqual(r["status"], "aplicada", r["resultado"])
        self.assertIn("R$ 100,00 → R$ 125,00", r["resultado"])
        mut = [x for x in self.chamadas if x[1].endswith("campaignBudgets:mutate")][-1]
        self.assertEqual(json.loads(mut[2])["operations"][0], {"update": {
            "resourceName": "customers/4445556666/campaignBudgets/91", "amountMicros": "125000000"}, "updateMask": "amount_micros"})
        self.ga.aprovar(neg["id"])
        mut = [x for x in self.chamadas if x[1].endswith("campaignCriteria:mutate")][-1]
        ops = json.loads(mut[2])["operations"]
        self.assertEqual(ops[0]["create"], {"campaign": "customers/4445556666/campaigns/11", "negative": True,
                                            "keyword": {"text": "vagas emprego", "matchType": "PHRASE"}})
        with self.assertRaises(ValueError):
            self.ga.aprovar(neg["id"])
        self.assertTrue(any("Google Ads" in x or "Loja Exemplo" in x for x in self.ga.resumo_linhas()))

    def test_pedido_manual_e_erro_da_api(self):
        c = self._conectar()
        self.respostas.append(json.dumps({"resumo": "ok", "acoes": []}))
        self.ga.analisar(c["id"], HOJE)
        a = self.ga.propor(c["id"], "pausar_palavra", "Pausar palavra cara", "",
                           {"recurso": "customers/4445556666/adGroupCriteria/5~7"})
        with patch.object(self.api, "mutate", side_effect=self.api.ErroGoogleAds("CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION")):
            r = self.ga.aprovar(a["id"])
        self.assertEqual(r["status"], "erro")
        with self.assertRaises(ValueError):
            self.ga.propor(c["id"], "pausar_palavra", "x", "", {"recurso": "customers/1/adGroupCriteria/9~9"})

    def test_uma_analise_por_vez_e_proposta_substituida_explicada(self):
        import threading
        c = self._conectar()
        segura, entrou = threading.Event(), threading.Event()
        with patch.object(self.ga, "analisar", side_effect=lambda *a, **k: (entrou.set(), segura.wait(5))):
            self.assertTrue(self.ga.analisar_em_segundo_plano(c["id"]))
            self.assertTrue(entrou.wait(5))
            self.assertFalse(self.ga.analisar_em_segundo_plano(c["id"]))          # clique duplo não roda outra
            segura.set()
            for _ in range(100):
                if self.ga._UMA_POR_VEZ.acquire(blocking=False):
                    self.ga._UMA_POR_VEZ.release()
                    break
                import time
                time.sleep(0.02)
        for _ in range(2):
            self.respostas.append(json.dumps({"resumo": "ok", "acoes": [{"tipo": "alerta", "titulo": "Conferir tag"}]}))
        self.ga.analisar(c["id"], HOJE)
        velha = self.ga.acoes(c["id"])[0]
        self.ga.analisar(c["id"], HOJE)
        with self.assertRaises(ValueError) as e:
            self.ga.aprovar(velha["id"])
        self.assertIn("análise mais nova", str(e.exception))

    def test_criar_campanha_de_pesquisa(self):
        c = self._conectar()
        grupo = {"nome": "Camisetas", "palavras": [{"texto": "camiseta masculina", "correspondencia": "PHRASE"}, "camiseta básica"],
                 "titulos": ["Camisetas Masculinas", "Frete Grátis Acima de R$199", "Compre na Loja Exemplo"],
                 "descricoes": ["Algodão premium, caimento perfeito. Troca grátis em 30 dias.", "Peça já a sua."],
                 "caminho1": "camisetas", "caminho2": "masculinas"}
        base = {"nome": "Pesquisa | Camisetas", "orcamento_diario": 50, "lance": "conversoes", "locais": ["São Paulo"],
                "url_final": "https://loja.exemplo.com/camisetas", "negativas": ["vagas", "grátis"], "grupos": [grupo]}
        ruim = {**base, "grupos": [{**grupo, "titulos": ["Um título que passa e muito dos trinta caracteres", "a"]}]}
        with self.assertRaises(ValueError) as e:
            self.ga.propor(c["id"], "criar_campanha_pesquisa", "x", "", ruim)
        self.assertIn("de 3 a 15 títulos", str(e.exception))
        self.assertIn("passam do limite", str(e.exception))
        a = self.ga.propor(c["id"], "criar_campanha_pesquisa", "Campanha camisetas", "", base)
        self.assertFalse([x for x in self.chamadas if "mutate" in x[1]])
        r = self.ga.aprovar(a["id"], ativar=False)
        self.assertEqual(r["status"], "aplicada", r["resultado"])
        self.assertIn("PAUSADA", r["resultado"])
        ops = json.loads([x for x in self.chamadas if x[1].endswith("googleAds:mutate")][-1][2])["mutateOperations"]
        camp = ops[1]["campaignOperation"]["create"]
        self.assertEqual((camp["status"], camp["advertisingChannelType"], camp["campaignBudget"]),
                         ("PAUSED", "SEARCH", "customers/4445556666/campaignBudgets/-1"))
        self.assertEqual(ops[0]["campaignBudgetOperation"]["create"]["amountMicros"], "50000000")
        crits = [o["campaignCriterionOperation"]["create"] for o in ops if "campaignCriterionOperation" in o]
        self.assertIn({"campaign": "customers/4445556666/campaigns/-2", "location": {"geoTargetConstant": "geoTargetConstants/1001773"}}, crits)
        self.assertEqual(sum(1 for x in crits if x.get("negative")), 2)
        ad = [o for o in ops if "adGroupAdOperation" in o][0]["adGroupAdOperation"]["create"]["ad"]
        self.assertEqual(ad["finalUrls"], ["https://loja.exemplo.com/camisetas"])
        self.assertEqual(len(ad["responsiveSearchAd"]["headlines"]), 3)
        kws = [o["adGroupCriterionOperation"]["create"]["keyword"] for o in ops if "adGroupCriterionOperation" in o]
        self.assertEqual(kws[1], {"text": "camiseta básica", "matchType": "PHRASE"})

    def _anexos(self):
        import io
        import subprocess
        from PIL import Image
        from haizen.central import anexos
        from haizen.producao.ferramentas import ffmpeg
        b = io.BytesIO(); Image.new("RGB", (1600, 1000), (200, 50, 50)).save(b, "JPEG")
        foto = anexos.salvar("criativo.jpg", b.getvalue())["id"]
        b = io.BytesIO(); Image.new("RGBA", (400, 160), (0, 0, 0, 255)).save(b, "PNG")
        logo = anexos.salvar("logo.png", b.getvalue())["id"]
        mov = Path(self.dir.name) / "YOUTUBE.mov"
        subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=12:s=1280x720:r=25",
                        "-pix_fmt", "yuv420p", str(mov)], check=True)
        video = anexos.salvar("YOUTUBE.mov", mov.read_bytes())["id"]
        return foto, logo, video

    def test_demand_gen_com_video_do_anexo_e_imagem(self):
        from haizen.googleads import midia
        c = self._conectar()
        foto, logo, video = self._anexos()
        info = midia.info_video(video)
        self.assertEqual((info["segundos"], info["largura"], info["proporcao"]), (12.0, 1280, "16:9 (horizontal)"))
        with self.assertRaises(ValueError):
            midia.arquivo("/etc/passwd")
        det = {"nome": "YouTube | Camisetas", "orcamento_diario": 40, "url_final": "https://loja.exemplo.com",
               "nome_empresa": "Loja Exemplo", "logo": f"[anexo:{logo}]",
               "anuncio_video": {"videos": [f"anexo:{video}"], "titulos": ["Camisetas que duram"],
                                 "titulos_longos": ["Camisetas premium com frete grátis acima de R$ 199"],
                                 "descricoes": ["Algodão de verdade. Troca grátis."], "cta": "SHOP_NOW"},
               "anuncio_imagem": {"imagens": [foto], "titulos": ["Nova coleção"], "descricoes": ["Peça já a sua."]}}
        with self.assertRaises(ValueError) as e:
            self.ga.propor(c["id"], "criar_campanha_demand_gen", "x", "", {**det, "nome_empresa": "Um nome de empresa longo demais aqui"})
        self.assertIn("nome_empresa", str(e.exception))
        a = self.ga.propor(c["id"], "criar_campanha_demand_gen", "Campanha YouTube", "", det)
        with patch.object(midia, "subir_youtube", return_value="dQw4w9WgXcQ") as up:
            r = self.ga.aprovar(a["id"], ativar=False, em_segundo_plano=False)
        self.assertEqual(r["status"], "aplicada", r["resultado"])
        up.assert_called_once()
        ops = json.loads([x for x in self.chamadas if x[1].endswith("googleAds:mutate")][-1][2])["mutateOperations"]
        camp = [o for o in ops if "campaignOperation" in o][0]["campaignOperation"]["create"]
        self.assertEqual((camp["advertisingChannelType"], camp["status"]), ("DEMAND_GEN", "PAUSED"))
        assets = [o["assetOperation"]["create"] for o in ops if "assetOperation" in o]
        self.assertIn({"youtubeVideoId": "dQw4w9WgXcQ"}, [x.get("youtubeVideoAsset") for x in assets])
        self.assertEqual(sum(1 for x in assets if x.get("type") == "IMAGE"), 4)           # logo + 3 cortes
        ads = [o["adGroupAdOperation"]["create"]["ad"] for o in ops if "adGroupAdOperation" in o]
        dv = ads[0]["demandGenVideoResponsiveAd"]
        self.assertEqual(dv["businessName"], {"text": "Loja Exemplo"})
        self.assertTrue(ads[1]["demandGenMultiAssetAd"]["squareMarketingImages"])
        crit = [o["adGroupCriterionOperation"]["create"] for o in ops if "adGroupCriterionOperation" in o]
        self.assertIn({"adGroup": crit[0]["adGroup"], "language": {"languageConstant": "languageConstants/1014"}}, crit)

    def test_display_em_segundo_plano(self):
        import time as _t
        c = self._conectar()
        foto, logo, _ = self._anexos()
        a = self.ga.propor(c["id"], "criar_campanha_display", "Display", "", {
            "nome": "Display | Remarketing", "orcamento_diario": 20, "url_final": "https://loja.exemplo.com",
            "nome_empresa": "Loja Exemplo", "logo": logo, "imagens": [foto], "titulos": ["Volte e ganhe 10%"],
            "titulo_longo": "Sua camiseta favorita está esperando por você", "descricoes": ["Frete grátis acima de R$ 199."]})
        r = self.ga.aprovar(a["id"])
        self.assertEqual(r["status"], "aplicando")
        for _ in range(100):
            if self.ga.acao(a["id"])["status"] != "aplicando":
                break
            _t.sleep(0.05)
        self.assertEqual(self.ga.acao(a["id"])["status"], "aplicada", self.ga.acao(a["id"])["resultado"])
        ops = json.loads([x for x in self.chamadas if x[1].endswith("googleAds:mutate")][-1][2])["mutateOperations"]
        ad = [o for o in ops if "adGroupAdOperation" in o][0]["adGroupAdOperation"]["create"]["ad"]["responsiveDisplayAd"]
        self.assertEqual(ad["longHeadline"], {"text": "Sua camiseta favorita está esperando por você"})
        self.assertTrue(ad["marketingImages"] and ad["squareMarketingImages"] and ad["squareLogoImages"])

    def test_mensagens_de_erro_claras(self):
        corpo = {"error": {"message": "x", "details": [{"errors": [{"errorCode": {"authorizationError":
                 "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"}, "message": "no"}]}]}}
        self.assertIn("Explorer", self.api._mensagem(403, corpo))
        self.assertIn("conecte de novo", self.api._mensagem(400, {"error": "invalid_grant"}))


if __name__ == "__main__":
    unittest.main()

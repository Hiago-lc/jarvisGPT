"""Social: Instagram da HAIZEN (API oficial falsa), análise, raio-x, calendário,
produção pela equipe e publicação só com a sua ordem."""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

POSTS = {"data": [
    {"id": "m1", "caption": "Antes e depois da marca X", "media_type": "CAROUSEL_ALBUM", "media_product_type": "FEED",
     "timestamp": "2026-11-01T12:00:00+0000", "like_count": 120, "comments_count": 9, "permalink": "https://instagram.com/p/AAA/",
     "media_url": "https://cdn/x.jpg"},
    {"id": "m2", "caption": "Bastidor", "media_type": "VIDEO", "media_product_type": "REELS",
     "timestamp": "2026-10-29T12:00:00+0000", "like_count": 40, "comments_count": 2, "permalink": "https://instagram.com/reel/BBB/",
     "thumbnail_url": "https://cdn/y.jpg"}]}

ANALISE = {"nota": 62, "criterios": [{"nome": "Bio e posicionamento", "nota": 5, "comentario": "não diz o serviço"}],
           "resumo": "Carrossel de antes e depois puxa o alcance.", "kpis": {"seguidores": 1800},
           "melhores": [{"id": "m1", "porque": "antes e depois"}],
           "melhorias": [{"prioridade": "alta", "o_que": "Bio com serviço", "como": "HAIZEN | Branding e Sites"}],
           "bio_sugerida": "HAIZEN | Marcas e sites que vendem",
           "calendario": [{"data": "2026-11-09", "formato": "carrossel", "tema": "3 erros de marca", "gancho": "Sua marca...",
                           "roteiro": "1. capa", "legenda": "Salve!", "cta": "salve"},
                          {"data": "2026-11-11", "formato": "Reels", "tema": "Bastidor de um logo", "legenda": "x"}],
           "relatorio": "## ok"}


class SocialTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": str(base / "d"), "HAIZEN_DB": str(base / "h.db"),
                                           "HAIZEN_ENTREGAS_DIR": str(base / "e"), "HAIZEN_NOTIFICAR_WINDOWS": "0",
                                           "HAIZEN_IG_TOKEN": ""})
        self.env.start()
        from haizen import social
        from haizen.social import instagram
        self.s, self.ig = social, instagram
        self.http = []
        self.publicados = []

        def http(metodo, url, dados=None, cab=None, timeout=60):
            self.http.append((metodo, url, dados))
            if "me/accounts" in url:
                return {"data": [{"id": "PG1", "name": "HAIZEN", "access_token": "PAGETOKEN",
                                  "instagram_business_account": {"id": "IG1", "username": "haizen.agencia"}}]}
            if "/IG1/media?" in url and metodo == "GET":
                return POSTS
            if "/insights" in url:
                return {"data": [{"name": "reach", "values": [{"value": 900}]}, {"name": "saved", "values": [{"value": 30}]}]}
            if "business_discovery" in url:
                return {"business_discovery": {"username": "ref", "followers_count": 50000, "biography": "b",
                                               "media": {"data": [{"id": "r1", "caption": "gancho forte", "media_type": "IMAGE",
                                                                   "permalink": "https://www.instagram.com/reel/XYZ/",
                                                                   "media_url": "https://cdn/r.jpg", "like_count": 4000}]}}}
            if url.endswith("/PG1/photos"):
                return {"id": "FOTO1"}
            if "/FOTO1?" in url:
                return {"images": [{"width": 1080, "source": "https://scontent/foto.jpg"}]}
            if "media_publish" in url:
                return {"id": "PUB1"}
            if "/IG1/media" in url and metodo == "POST":
                return {"id": "C1"}
            if "/C1?" in url:
                return {"status_code": "FINISHED"}
            if "media_publish" in url:
                return {"id": "PUB1"}
            if "/PUB1?" in url:
                return {"permalink": "https://instagram.com/p/NOVO/"}
            if "IG1?" in url:
                return {"id": "IG1", "username": "haizen.agencia", "followers_count": 1800, "biography": "Agência"}
            return {}
        self.p = [patch.object(instagram, "_http", side_effect=http),
                  patch("haizen.social._baixar", side_effect=lambda url, d: (d.write_bytes(b"jpg"), d)[1])]
        for x in self.p:
            x.start()
        self.respostas = []
        self.prompts = []

        def claude(args, prompt, pasta, timeout, env=None, **kw):
            self.prompts.append((args, prompt, kw))
            return self.respostas.pop(0)
        self.pc = patch("haizen.executor._rodar_claude", side_effect=claude)
        self.pc.start()

    def tearDown(self):
        self.pc.stop()
        for x in self.p:
            x.stop()
        self.env.stop()
        self.dir.cleanup()

    def _conectar(self):
        r = self.s.conectar("EAAB" + "x" * 160)
        self.assertEqual(r["escolhida"]["username"], "haizen.agencia")

    def test_token_fica_fora_do_repo_e_e_validado(self):
        with self.assertRaises(ValueError):
            self.s.conectar("curto")
        self._conectar()
        self.assertTrue(str(self.ig._arq_token()).startswith(self.dir.name))
        self.assertTrue(self.s.painel()["conectado"])

    def test_token_errado_nao_apaga_o_que_funcionava(self):
        self._conectar()
        bom = self.ig.token()
        with self.assertRaises(ValueError) as e:
            self.s.conectar("0123456789abcdef0123456789abcdef")             # "Token do cliente" do app
        self.assertIn("Token do cliente", str(e.exception))
        with self.assertRaises(ValueError):
            self.s.conectar("123456789012345")                               # ID do app
        with patch.object(self.ig, "contas", side_effect=self.ig.ErroInstagram("Invalid OAuth access token")):
            with self.assertRaises(ValueError) as e:
                self.s.conectar("EAAB" + "y" * 160)
        self.assertIn("anterior continua guardado", str(e.exception))
        self.assertEqual(self.ig.token(), bom)

    def test_permissao_que_falta_aparece(self):
        self._conectar()
        with patch.object(self.ig, "info_do_token", return_value={"valido": True, "vence_em": 0,
                                                                  "escopos": ["instagram_basic", "pages_show_list"]}):
            self.s.conferir_token(forcar=True)
        self.assertIn("instagram_content_publish", self.s.painel()["config"]["token_faltando"])
        import io
        import urllib.error
        corpo = io.BytesIO(json.dumps({"error": {"code": 10, "message": "(#10) Requires instagram_content_publish "
                                                                       "permission to manage the object"}}).encode())
        err = urllib.error.HTTPError("u", 403, "x", {}, corpo)
        self.p[0].stop()
        try:
            with patch("urllib.request.urlopen", side_effect=err):
                with self.assertRaises(self.ig.ErroInstagram) as e:
                    self.ig._http("POST", "https://graph/x")
        finally:
            self.p[0].start()
        self.assertIn("não tem a permissão instagram_content_publish", str(e.exception))

    def test_analise_ve_a_grade_e_monta_o_calendario(self):
        self._conectar()
        self.respostas.append(json.dumps(ANALISE))
        an = self.s.analisar()
        self.assertEqual(an["nota"], 62)
        args, prompt, kw = self.prompts[-1]
        self.assertEqual(kw["origem"], "social")
        self.assertIn("Read", args[args.index("--allowedTools") + 1])
        self.assertIn("grade", " ".join(args))
        self.assertIn('"reach": 900', prompt)                         # os números vão para o Claude
        self.assertIn("Antes e depois da marca X", prompt)
        its = self.s.itens()
        self.assertEqual([(i["formato"], i["status"]) for i in its], [("carrossel", "ideia"), ("reels", "ideia")])
        # Nova análise troca as ideias que você não aprovou.
        self.respostas.append(json.dumps({**ANALISE, "calendario": [{"tema": "novo", "formato": "estatico"}]}))
        self.s.analisar()
        self.assertEqual([i["tema"] for i in self.s.itens()], ["novo"])

    def test_item_aprovado_vira_trabalho_e_fica_pronto_com_a_peca_aprovada(self):
        from haizen import store
        self._conectar()
        it = self.s.criar_item({"tema": "3 erros de marca", "formato": "carrossel", "legenda": "Salve!"})
        with patch("haizen.worker.iniciar"), patch("haizen.executor.claude_disponivel", return_value="claude"):
            it = self.s.aprovar_item(it["id"])
        self.assertEqual(it["status"], "produzindo")
        t = store.trabalho(it["trabalho_id"])
        self.assertEqual(t["agente"], "criativos")
        self.assertIn("Instagram da própria HAIZEN", t["pedido"])
        pasta = Path(self.dir.name) / "job"
        pasta.mkdir()
        (pasta / "01.png").write_bytes(b"png")
        (pasta / "02.png").write_bytes(b"png")
        store.atualizar(t["id"], status="aprovado", pasta=str(pasta))
        self.s.sincronizar()
        it = self.s.item_(it["id"])
        self.assertEqual(it["status"], "pronto")
        self.assertEqual(len(it["arquivos"]), 2)

    def test_publicar_so_pronto_carrossel_e_agendado(self):
        self._conectar()
        it = self.s.criar_item({"tema": "t", "formato": "carrossel", "legenda": "Legenda final"})
        with self.assertRaises(ValueError):
            self.s.publicar_item(it["id"])                              # ainda não tem peça aprovada
        pasta = Path(self.dir.name) / "p"
        pasta.mkdir()
        from PIL import Image
        for n in ("a.png", "b.png"):
            Image.new("RGB", (20, 20), (255, 0, 0)).save(pasta / n)
        self.s._mudar(it["id"], status="pronto", arquivos=[str(pasta / "a.png"), str(pasta / "b.png")])
        quando = (dt.datetime.now() + dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        self.assertEqual(self.s.publicar_item(it["id"], quando)["status"], "agendado")
        feito = self.s.publicar_item(it["id"], em_segundo_plano=False)
        self.assertEqual((feito["status"], feito["permalink"]), ("publicado", "https://instagram.com/p/NOVO/"))
        posts = [(m, u, d) for m, u, d in self.http if m == "POST"]
        self.assertTrue(any(u.endswith("/PG1/photos") for _, u, _ in posts))     # imagem via foto não publicada
        self.assertTrue(any(b"is_carousel_item=true" in (d or b"") for _, _, d in posts))
        self.assertTrue(any(b"CAROUSEL" in (d or b"") and b"Legenda+final" in (d or b"") for _, _, d in posts))
        self.assertTrue((pasta / "a.instagram.jpg").is_file())                  # PNG vira JPEG

    def test_raio_x_de_referencia_e_adaptacao(self):
        self._conectar()
        self.respostas.append(json.dumps({"titulo": "Gancho de dor", "nota": 8, "gancho": "pergunta direta",
                                          "adaptacoes": [{"tema": "Sua marca parece amadora?", "formato": "reels"}]}))
        r = self.s.raio_x("@ref https://www.instagram.com/reel/XYZ/?igsh=1")
        self.assertEqual(r["dados"]["usuario"], "ref")
        self.assertIn("gancho forte", self.prompts[-1][1])
        it = self.s.adaptar(r["id"], 0)
        self.assertEqual((it["formato"], it["status"], it["origem"]), ("reels", "ideia", "raiox"))
        with self.assertRaises(ValueError):
            self.s.raio_x("só um link sem perfil https://site.com")

    def test_agenda_semanal(self):
        self._conectar()
        self.s.salvar_config({"dia": 0, "horario": "08:00"})
        seg = dt.datetime(2026, 11, 9, 8, 30)          # segunda
        self.assertTrue(self.s.hora_da_semana(seg))
        self.assertFalse(self.s.hora_da_semana(seg.replace(hour=7)))
        self.assertFalse(self.s.hora_da_semana(dt.datetime(2026, 11, 10, 9, 0)))


if __name__ == "__main__":
    unittest.main()

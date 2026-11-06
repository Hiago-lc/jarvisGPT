"""E-commerce: Shopify e Tray falsas, métricas, análise com propostas, aplicação só com aprovação."""
import datetime as dt
import json
import os
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

HOJE = dt.date(2026, 11, 6)


def _pedido(i, dia, total, itens, cupom=None, desconto=0, cancelado=False):
    return {"id": f"gid://shopify/Order/{i}", "name": f"#{i}", "createdAt": f"{dia}T12:00:00Z",
            "cancelledAt": "2026-01-01" if cancelado else None, "discountCodes": [cupom] if cupom else [],
            "currentTotalPriceSet": {"shopMoney": {"amount": str(total)}},
            "totalDiscountsSet": {"shopMoney": {"amount": str(desconto)}},
            "lineItems": {"nodes": [{"title": n, "quantity": q, "product": {"id": pid},
                                     "originalTotalSet": {"shopMoney": {"amount": str(v)}}} for pid, n, q, v in itens]}}


CAMISA, CANECA, PARADO = "gid://shopify/Product/1", "gid://shopify/Product/2", "gid://shopify/Product/3"
PEDIDOS = [_pedido(i, (HOJE - dt.timedelta(days=i % 20)).isoformat(), 150, [(CAMISA, "Camisa", 2, 120), (CANECA, "Caneca", 1, 30)],
                   cupom="BEMVINDO" if i % 5 == 0 else None, desconto=10 if i % 5 == 0 else 0) for i in range(1, 41)]
PEDIDOS.append(_pedido(99, HOJE.isoformat(), 999, [(CAMISA, "Camisa", 1, 999)], cancelado=True))
PRODUTOS = [
    {"id": CAMISA, "title": "Camisa", "status": "ACTIVE", "totalInventory": 4, "createdAt": "2025-01-01T00:00:00Z",
     "seo": {"title": "", "description": ""}, "variants": {"nodes": [{"id": "gid://shopify/ProductVariant/11", "price": "60.00",
                                                                      "compareAtPrice": None, "inventoryQuantity": 4}]}},
    {"id": CANECA, "title": "Caneca", "status": "ACTIVE", "totalInventory": 200, "createdAt": "2025-01-01T00:00:00Z",
     "seo": {"title": "Caneca", "description": "x"}, "variants": {"nodes": [{"id": "gid://shopify/ProductVariant/21", "price": "30.00"}]}},
    {"id": PARADO, "title": "Boné parado", "status": "ACTIVE", "totalInventory": 50, "createdAt": "2025-01-01T00:00:00Z",
     "seo": {"title": "", "description": ""}, "variants": {"nodes": [{"id": "gid://shopify/ProductVariant/31", "price": "80.00",
                                                                      "compareAtPrice": None}]}},
]


class EcommerceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        b = Path(self.dir.name)
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": str(b / "d"), "HAIZEN_DB": str(b / "h.db"),
                                           "HAIZEN_NOTIFICAR_WINDOWS": "0", "JARVIS_CEREBRO": "local"})
        self.env.start()
        (b / "d").mkdir()
        from haizen import ecommerce
        from haizen.ecommerce import shopify, tray
        self.ec, self.sh, self.tr = ecommerce, shopify, tray
        self.gql = []
        self.precos = {"gid://shopify/ProductVariant/31": ("80.00", None)}

        def http_shopify(metodo, url, dados=None, cab=None, timeout=60):
            corpo = json.loads(dados or b"{}")
            q, v = corpo.get("query", ""), corpo.get("variables") or {}
            self.gql.append((q, v, cab))
            if "shop {" in q:
                return {"data": {"shop": {"name": "Loja Teste", "myshopifyDomain": "teste.myshopify.com"}}}
            if "orders(" in q:
                return {"data": {"orders": {"nodes": PEDIDOS, "pageInfo": {"hasNextPage": False}}}}
            if "products(" in q:
                return {"data": {"products": {"nodes": PRODUTOS, "pageInfo": {"hasNextPage": False}}}}
            if "discountNodes" in q:
                return {"data": {"discountNodes": {"nodes": [{"id": "gid://shopify/DiscountCodeNode/7", "discount": {
                    "__typename": "DiscountCodeBasic", "title": "Bem-vindo", "status": "ACTIVE", "startsAt": "2026-01-01",
                    "endsAt": None, "asyncUsageCount": 8, "codes": {"nodes": [{"code": "BEMVINDO"}]}}}]}}}
            if "shopifyqlQuery" in q:
                return {"data": {"shopifyqlQuery": {"tableData": {"columns": [{"name": "sessions"}, {"name": "conversion_rate"}],
                                                                  "rows": [{"sessions": "4000", "conversion_rate": "0.0125"}]}}}}
            if "discountCodeBasicCreate" in q:
                return {"data": {"discountCodeBasicCreate": {"codeDiscountNode": {"id": "gid://shopify/DiscountCodeNode/9"},
                                                             "userErrors": []}}}
            if "product(id:" in q:
                return {"data": {"product": {"variants": {"nodes": [{"id": k, "price": p, "compareAtPrice": c}
                                                                    for k, (p, c) in self.precos.items()]}}}}
            if "productVariantsBulkUpdate" in q:
                for x in v["v"]:
                    self.precos[x["id"]] = (x["price"], x.get("compareAtPrice"))
                return {"data": {"productVariantsBulkUpdate": {"productVariants": v["v"], "userErrors": []}}}
            if "productUpdate" in q:
                return {"data": {"productUpdate": {"product": {"id": v["p"]["id"]}, "userErrors": []}}}
            return {"data": {}}
        self.p = patch.object(shopify, "_http", side_effect=http_shopify)
        self.p.start()
        self.respostas, self.prompts = [], []

        def claude(args, prompt, pasta, timeout, env=None, **kw):
            self.prompts.append((args, prompt, kw))
            return self.respostas.pop(0)
        self.pc = patch("haizen.executor._rodar_claude", side_effect=claude)
        self.pc.start()

    def tearDown(self):
        self.pc.stop()
        self.p.stop()
        self.env.stop()
        self.dir.cleanup()

    def _shopify(self):
        return self.ec.conectar_loja({"plataforma": "shopify", "nome": "Loja Teste", "dominio": "https://teste.myshopify.com/admin",
                                      "token": "shpat_segredo123"})

    def test_conexao_guarda_token_cifrado_fora_do_banco(self):
        lj = self._shopify()
        self.assertEqual((lj["id"], lj["dominio"]), ("shopify-loja-teste", "teste.myshopify.com"))
        self.assertTrue(lj["conectado_em"])
        self.assertEqual(self.gql[-1][2]["X-Shopify-Access-Token"], "shpat_segredo123")
        banco = (Path(self.dir.name) / "h.db").read_bytes()
        self.assertNotIn(b"shpat_segredo123", banco)
        self.assertNotIn("shpat_segredo123", json.dumps(self.ec.painel()))
        with self.assertRaises(ValueError):
            self.ec.conectar_loja({"plataforma": "shopify", "dominio": "nao é dominio"})

    def test_metricas_sem_claude(self):
        lj = self._shopify()
        m = self.ec.coletar(lj, HOJE)
        self.assertEqual(m["ult30"]["pedidos"], 40)                  # cancelado fora
        self.assertEqual(m["ult30"]["ticket"], 150)
        self.assertEqual(m["top"][0]["nome"], "Camisa")
        self.assertIn(CAMISA, m["campeoes"])
        self.assertEqual(m["estoque_baixo"][0]["id"], CAMISA)        # 4 un. vendendo ~5/dia
        self.assertEqual([p["id"] for p in m["parados"]], [PARADO])
        self.assertEqual(m["cupons_usados"][0]["codigo"], "BEMVINDO")
        self.assertEqual(m["visitas"], {"sessoes": 4000, "conversao": 1.25})
        self.assertEqual(len(m["por_dia"]), 30)

    def test_analise_gera_propostas_validas_e_nada_muda_sozinho(self):
        lj = self._shopify()
        self.respostas.append(json.dumps({
            "resumo": "Loja estável; camisa acabando.", "saude": 72, "alertas": ["Repor a Camisa"],
            "acoes": [
                {"tipo": "preco_promocional", "titulo": "Promo do boné", "motivo": "30 dias sem venda",
                 "detalhes": {"produto_id": PARADO, "preco_promocional": 64.9, "inicio": "2026-11-06", "fim": "2026-11-15"}},
                {"tipo": "cupom", "titulo": "Black", "detalhes": {"codigo": "black 15", "tipo": "percentual", "valor": 15,
                                                                 "inicio": "2026-11-20", "fim": "2026-11-30"}},
                {"tipo": "preco", "titulo": "inventado", "detalhes": {"produto_id": "gid://shopify/Product/999", "preco_novo": 1}},
                {"tipo": "cupom", "titulo": "absurdo", "detalhes": {"codigo": "X99", "valor": 95}}]}))
        an = self.ec.analisar(lj["id"], HOJE)
        self.assertEqual(an["saude"], 72)
        _, prompt, kw = self.prompts[-1]
        self.assertEqual(kw["origem"], "ecommerce")
        self.assertIn("Black Friday", prompt)                       # datas comerciais próximas
        self.assertNotIn("shpat_", prompt)
        props = self.ec.acoes(lj["id"])
        self.assertEqual(sorted(a["tipo"] for a in props), ["cupom", "preco_promocional"])   # inválidas descartadas
        self.assertEqual([a for a in props if a["tipo"] == "cupom"][0]["detalhes"]["codigo"], "BLACK15")
        self.assertFalse(any("Create" in q or "Update" in q for q, _, _ in self.gql))      # nada aplicado

    def test_aprovar_cupom_e_promocao_que_volta_sozinha(self):
        lj = self._shopify()
        c = self.ec.propor(lj["id"], "cupom", "Black", "", {"codigo": "BLACK15", "valor": 15, "fim": "2026-11-30",
                                                            "produtos": ["1"], "minimo": 200})
        r = self.ec.aprovar(c["id"])
        self.assertEqual(r["status"], "aplicada", r["resultado"])
        q, v, _ = [g for g in self.gql if "discountCodeBasicCreate" in g[0]][-1]
        d = v["d"]
        self.assertEqual((d["code"], d["customerGets"]["value"]), ("BLACK15", {"percentage": 0.15}))
        self.assertEqual(d["customerGets"]["items"], {"products": {"productsToAdd": ["gid://shopify/Product/1"]}})
        self.assertEqual(d["minimumRequirement"]["subtotal"]["greaterThanOrEqualToSubtotal"], "200")
        with self.assertRaises(ValueError):
            self.ec.aprovar(c["id"])                                   # não aplica duas vezes
        p = self.ec.propor(lj["id"], "preco_promocional", "Promo", "", {"produto_id": PARADO, "preco_promocional": 64.9,
                                                                          "fim": "2026-11-15"})
        self.assertEqual(self.ec.aprovar(p["id"])["status"], "aplicada")
        self.assertEqual(self.precos["gid://shopify/ProductVariant/31"], ("64.9", "80.0"))     # de 80 por 64,90
        self.assertEqual(self.ec.reverter_promocoes(dt.date(2026, 11, 15)), 0)                # ainda no prazo
        self.assertEqual(self.ec.reverter_promocoes(dt.date(2026, 11, 16)), 1)
        self.assertEqual(self.precos["gid://shopify/ProductVariant/31"], ("80.00", None))
        self.assertEqual(self.ec.acao(p["id"])["status"], "revertida")

    def test_ajuste_na_aprovacao_e_erro_da_loja(self):
        lj = self._shopify()
        a = self.ec.propor(lj["id"], "preco", "Ajuste", "", {"produto_id": PARADO, "preco_novo": 75})
        r = self.ec.aprovar(a["id"], {"produto_id": PARADO, "preco_novo": 72})
        self.assertEqual(self.precos["gid://shopify/ProductVariant/31"][0], "72.0")
        self.assertIn("72,00", r["resultado"])
        with patch.object(self.sh, "mudar_precos", side_effect=self.sh.ErroShopify("price: inválido")):
            b = self.ec.propor(lj["id"], "preco", "x", "", {"produto_id": PARADO, "preco_novo": 70})
            self.assertEqual(self.ec.aprovar(b["id"])["status"], "erro")
        with self.assertRaises(ValueError):
            self.ec.propor(lj["id"], "cupom", "x", "", {"codigo": "A", "valor": 10})

    def test_resumo_da_manha_tem_as_lojas(self):
        lj = self._shopify()
        self.respostas.append(json.dumps({"resumo": "ok", "saude": 80, "alertas": [], "acoes": [
            {"tipo": "alerta", "titulo": "Repor Camisa"}]}))
        self.ec.analisar(lj["id"], HOJE)
        linhas = self.ec.resumo_linhas()
        self.assertTrue(any("Loja Teste: ontem" in x for x in linhas))
        self.assertTrue(any("1 proposta" in x for x in linhas))


class TrayTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        b = Path(self.dir.name)
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": str(b / "d"), "HAIZEN_DB": str(b / "h.db"),
                                           "HAIZEN_NOTIFICAR_WINDOWS": "0"})
        self.env.start()
        (b / "d").mkdir()
        from haizen import ecommerce
        from haizen.ecommerce import cofre, tray
        self.ec, self.tr, self.cofre = ecommerce, tray, cofre
        self.chamadas = []
        hoje = dt.date.today()

        def http(metodo, url, dados=None, cab=None, timeout=60):
            self.chamadas.append((metodo, url, dados, cab))
            if url.endswith("/auth") and metodo == "POST":
                return {"access_token": "TK1", "refresh_token": "RF1", "date_expiration_access_token": "2000-01-01 00:00:00",
                        "api_host": "https://loja.com.br/web_api"}
            if "/auth?refresh_token=RF1" in url:
                return {"access_token": "TK2", "refresh_token": "RF2",
                        "date_expiration_access_token": (dt.datetime.now() + dt.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")}
            if "/web_api/info?" in url:
                return {"Info": {"name": "Loja Tray"}}
            if "/web_api/orders?" in url:
                return {"paging": {"total": 2, "limit": 50}, "Orders": [
                    {"Order": {"id": "10", "date": hoje.isoformat(), "total": "200.00", "status": "A ENVIAR", "discount": "0"}},
                    {"Order": {"id": "9", "date": (hoje - dt.timedelta(days=90)).isoformat(), "total": "50.00", "status": "FINALIZADO"}}]}
            if "/web_api/products_solds?" in url:
                return {"ProductsSolds": [{"ProductsSold": {"order_id": "10", "product_id": "5", "name": "Vestido", "quantity": "2",
                                                             "price": "100.00"}}]}
            if "/web_api/products?" in url:
                return {"paging": {"total": 1, "limit": 50}, "Products": [{"Product": {
                    "id": "5", "name": "Vestido", "price": "120.00", "promotional_price": "100.00",
                    "start_promotion": "2000-01-01", "end_promotion": "2099-01-01", "stock": "7", "available": "1"}}]}
            if "/web_api/discount_coupons?" in url and metodo == "POST":
                return {"message": "Created", "id": "77"}
            if "/discount_coupons/create_relationship/77" in url:
                return {"message": "Created"}
            if "/web_api/discount_coupons?" in url:
                return {"DiscountCoupons": []}
            if "/web_api/products/5?" in url and metodo == "PUT":
                return {"message": "Saved", "code": 200}
            return {}
        self.p = patch.object(tray, "_http", side_effect=http)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.env.stop()
        self.dir.cleanup()

    def test_fluxo_tray(self):
        with self.assertRaises(ValueError):
            self.ec.conectar_loja({"plataforma": "tray", "nome": "Loja Tray", "dominio": "https://loja.com.br/web_api",
                                   "code": "abc"})                          # sem as chaves do app da HAIZEN
        self.ec.salvar_config({"tray_consumer_key": "chave-do-app-123", "tray_consumer_secret": "segredo-do-app-456"})
        lj = self.ec.conectar_loja({"plataforma": "tray", "nome": "Loja Tray", "dominio": "loja.com.br/web_api", "code": "abc"})
        self.assertTrue(lj["conectado_em"])
        auth = json.loads(self.chamadas[0][2])
        self.assertEqual((auth["consumer_key"], auth["code"]), ("chave-do-app-123", "abc"))
        self.assertEqual(self.cofre.ler(lj["id"])["access_token"], "TK2")          # vencido: renovou sozinho
        m = self.ec.coletar(lj)
        self.assertEqual(m["ult30"]["pedidos"], 1)
        self.assertEqual(m["top"][0]["nome"], "Vestido")
        self.assertEqual(m["visitas"], {})
        with self.assertRaises(ValueError):
            self.ec.propor(lj["id"], "desconto_automatico", "x", "", {"valor": 10})
        c = self.ec.propor(lj["id"], "cupom", "Vestido 10", "", {"codigo": "VEST10", "valor": 10, "produtos": ["5"],
                                                                 "fim": "2026-12-01", "frete_gratis": True})
        self.assertEqual(self.ec.aprovar(c["id"])["status"], "aplicada")
        post = [x for x in self.chamadas if "discount_coupons?" in x[1] and x[0] == "POST"][-1]
        form = dict(urllib.parse.parse_qsl(post[2].decode()))
        self.assertEqual((form["DiscountCoupon[code]"], form["DiscountCoupon[type]"], form["DiscountCoupon[value]"]),
                         ("VEST10", "%", "10.00"))
        self.assertEqual(form["DiscountCoupon[local_application]"], "produtos")
        self.assertEqual(form["DiscountCoupon[freight_application]"], "frete_gratis")
        rel = [x for x in self.chamadas if "create_relationship/77" in x[1]][-1]
        self.assertEqual(json.loads(rel[2]), {"DiscountCouponProduct": [{"product_id": "5"}]})
        p = self.ec.propor(lj["id"], "preco_promocional", "Promo", "", {"produto_id": "5", "preco_promocional": 89.9,
                                                                         "inicio": "2026-11-10", "fim": "2026-11-20"})
        self.ec.aprovar(p["id"])
        put = [x for x in self.chamadas if x[0] == "PUT"][-1]
        self.assertEqual(json.loads(put[2]), {"Product": {"promotional_price": "89.90", "start_promotion": "2026-11-10",
                                                          "end_promotion": "2026-11-20"}})


class DatasTests(unittest.TestCase):
    def test_datas_do_varejo(self):
        from haizen import ecommerce
        nomes = {d["nome"]: d["data"] for d in ecommerce.datas_comerciais(dt.date(2026, 11, 6), 60)}
        self.assertEqual(nomes["Black Friday"], "2026-11-27")
        self.assertEqual(nomes["Cyber Monday"], "2026-11-30")
        self.assertEqual(nomes["Natal"], "2026-12-25")
        self.assertEqual(ecommerce._n_domingo(2027, 5, 2).isoformat(), "2027-05-09")


if __name__ == "__main__":
    unittest.main()

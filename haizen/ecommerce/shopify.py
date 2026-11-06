"""Shopify pela Admin API (GraphQL), com o acesso de um app da própria loja.

Acesso aceito: um token de administrador (shpat_...) ou o par Client ID +
Client secret de um app do Dev Dashboard (o token de 24 h é pedido e renovado
sozinho). Tudo devolvido aqui já vem no formato comum do módulo e-commerce.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from haizen.ecommerce import cofre

VERSAO = os.environ.get("HAIZEN_SHOPIFY_API", "2026-07")


class ErroShopify(RuntimeError):
    pass


def _http(metodo: str, url: str, dados: bytes | None = None, cab: dict | None = None, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            corpo = e.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001
            corpo = ""
        if e.code in (401, 403):
            raise ErroShopify(f"a Shopify recusou o acesso (HTTP {e.code}): confira o token e as permissões do app. "
                              f"{corpo}") from None
        raise ErroShopify(f"HTTP {e.code}: {corpo}") from None
    except urllib.error.URLError as e:
        raise ErroShopify(f"sem conexão com a Shopify: {e.reason}") from None


def dominio_limpo(d: str) -> str:
    d = (d or "").strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0]
    if d and "." not in d:
        d += ".myshopify.com"
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]+\.[a-z]{2,}", d):
        raise ValueError("domínio da loja inválido: use algo como minhaloja.myshopify.com")
    return d


def _token(loja: dict) -> str:
    a = cofre.ler(loja["id"])
    if a.get("token"):
        return a["token"]
    if a.get("client_id") and a.get("client_secret"):
        if a.get("token_temp") and float(a.get("expira", 0)) > time.time() + 300:
            return a["token_temp"]
        r = _http("POST", f"https://{loja['dominio']}/admin/oauth/access_token",
                  urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": a["client_id"],
                                          "client_secret": a["client_secret"]}).encode(),
                  {"Content-Type": "application/x-www-form-urlencoded"})
        if not r.get("access_token"):
            raise ErroShopify(f"a Shopify não liberou o acesso com o Client ID/secret: {r}")
        a.update(token_temp=r["access_token"], expira=time.time() + int(r.get("expires_in") or 86000))
        cofre.gravar(loja["id"], a)
        return a["token_temp"]
    raise ErroShopify("a loja ainda não está conectada (falta o token ou o Client ID/secret)")


def gql(loja: dict, consulta: str, variaveis: dict | None = None) -> dict:
    r = _http("POST", f"https://{loja['dominio']}/admin/api/{VERSAO}/graphql.json",
              json.dumps({"query": consulta, "variables": variaveis or {}}).encode(),
              {"Content-Type": "application/json", "X-Shopify-Access-Token": _token(loja)}, timeout=90)
    if r.get("errors"):
        msgs = "; ".join(str(e.get("message", e)) for e in r["errors"]) if isinstance(r["errors"], list) else str(r["errors"])
        if "throttled" in msgs.lower():
            time.sleep(4)
            return gql(loja, consulta, variaveis)
        raise ErroShopify(msgs[:500])
    return r.get("data") or {}


def _erros(res: dict) -> None:
    erros = (res or {}).get("userErrors") or []
    if erros:
        raise ErroShopify("; ".join(f"{'.'.join(e.get('field') or [])}: {e.get('message')}" for e in erros)[:500])


# ── leitura ─────────────────────────────────────────────────────────────────
def info(loja: dict) -> dict:
    d = gql(loja, "{ shop { name currencyCode myshopifyDomain primaryDomain { url } plan { displayName } } }")
    s = d.get("shop") or {}
    return {"nome": s.get("name"), "moeda": s.get("currencyCode"), "dominio": s.get("myshopifyDomain"),
            "site": (s.get("primaryDomain") or {}).get("url"), "plano": (s.get("plan") or {}).get("displayName")}


_PEDIDOS = """query($q: String!, $depois: String) {
  orders(first: 100, after: $depois, query: $q, sortKey: CREATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    nodes { id name createdAt cancelledAt discountCodes
      currentTotalPriceSet { shopMoney { amount } }
      totalDiscountsSet { shopMoney { amount } }
      lineItems(first: 30) { nodes { title quantity product { id } originalTotalSet { shopMoney { amount } } } } } } }"""


def _valor(x) -> float:
    try:
        return float(((x or {}).get("shopMoney") or {}).get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def pedidos(loja: dict, desde: dt.date, maximo: int = 3000) -> list[dict]:
    out, cursor = [], None
    while len(out) < maximo:
        d = gql(loja, _PEDIDOS, {"q": f"created_at:>={desde.isoformat()}", "depois": cursor})["orders"]
        for o in d.get("nodes") or []:
            out.append({
                "id": o["id"], "numero": o.get("name"), "data": str(o.get("createdAt") or "")[:10],
                "total": _valor(o.get("currentTotalPriceSet")), "desconto": _valor(o.get("totalDiscountsSet")),
                "cupons": [str(c).upper() for c in (o.get("discountCodes") or [])],
                "cancelado": bool(o.get("cancelledAt")),
                "itens": [{"produto_id": (i.get("product") or {}).get("id") or "", "nome": i.get("title") or "",
                           "qtd": int(i.get("quantity") or 0), "valor": _valor(i.get("originalTotalSet"))}
                          for i in ((o.get("lineItems") or {}).get("nodes") or [])]})
        pi = d.get("pageInfo") or {}
        if not pi.get("hasNextPage"):
            break
        cursor = pi.get("endCursor")
    return out


_PRODUTOS = """query($depois: String) {
  products(first: 100, after: $depois, sortKey: UPDATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    nodes { id title handle status totalInventory createdAt onlineStoreUrl productType
      seo { title description }
      variants(first: 10) { nodes { id title price compareAtPrice inventoryQuantity sku } } } } }"""


def produtos(loja: dict, maximo: int = 500) -> list[dict]:
    out, cursor = [], None
    while len(out) < maximo:
        d = gql(loja, _PRODUTOS, {"depois": cursor})["products"]
        for p in d.get("nodes") or []:
            vs = (p.get("variants") or {}).get("nodes") or []
            precos = [float(v["price"]) for v in vs if v.get("price") not in (None, "")]
            compara = [float(v["compareAtPrice"]) for v in vs if v.get("compareAtPrice") not in (None, "")]
            out.append({
                "id": p["id"], "nome": p.get("title") or "", "ativo": p.get("status") == "ACTIVE",
                "status": p.get("status"), "estoque": p.get("totalInventory"), "criado": str(p.get("createdAt") or "")[:10],
                "preco": min(precos) if precos else None, "preco_de": max(compara) if compara else None,
                "tipo": p.get("productType") or "", "link": p.get("onlineStoreUrl") or "",
                "seo_titulo": (p.get("seo") or {}).get("title") or "", "seo_descricao": (p.get("seo") or {}).get("description") or "",
                "variantes": [{"id": v["id"], "nome": v.get("title"), "preco": v.get("price"),
                               "preco_de": v.get("compareAtPrice"), "estoque": v.get("inventoryQuantity"),
                               "sku": v.get("sku")} for v in vs]})
        pi = d.get("pageInfo") or {}
        if not pi.get("hasNextPage"):
            break
        cursor = pi.get("endCursor")
    return out


_CUPONS = """{ discountNodes(first: 40, reverse: true, sortKey: CREATED_AT) { nodes { id discount { __typename
  ... on DiscountCodeBasic { title status startsAt endsAt asyncUsageCount codes(first: 1) { nodes { code } } }
  ... on DiscountCodeFreeShipping { title status startsAt endsAt asyncUsageCount codes(first: 1) { nodes { code } } }
  ... on DiscountCodeBxgy { title status startsAt endsAt asyncUsageCount codes(first: 1) { nodes { code } } }
  ... on DiscountAutomaticBasic { title status startsAt endsAt asyncUsageCount }
  ... on DiscountAutomaticBxgy { title status startsAt endsAt asyncUsageCount } } } } }"""


def cupons(loja: dict) -> list[dict]:
    out = []
    for n in (gql(loja, _CUPONS).get("discountNodes") or {}).get("nodes") or []:
        d = n.get("discount") or {}
        codigos = ((d.get("codes") or {}).get("nodes") or [])
        out.append({"id": n["id"], "codigo": codigos[0]["code"] if codigos else "", "titulo": d.get("title") or "",
                    "automatico": "Automatic" in str(d.get("__typename")), "status": str(d.get("status") or "").lower(),
                    "inicio": str(d.get("startsAt") or "")[:10], "fim": str(d.get("endsAt") or "")[:10],
                    "usos": d.get("asyncUsageCount")})
    return out


def visitas(loja: dict, dias: int = 30) -> dict:
    """Sessões e conversão (relatórios da Shopify, quando o plano e a permissão read_reports deixam)."""
    q = f"FROM sessions SHOW sessions, conversion_rate SINCE -{int(dias)}d UNTIL today"
    try:
        d = gql(loja, "query($q: String!) { shopifyqlQuery(query: $q) { tableData { columns { name } rows } "
                      "parseErrors } }", {"q": q})
    except ErroShopify:
        return {}
    t = ((d.get("shopifyqlQuery") or {}).get("tableData") or {})
    cols = [c.get("name") for c in t.get("columns") or []]
    linhas = t.get("rows") or []
    if not cols or not linhas:
        return {}
    linha = linhas[0] if isinstance(linhas[0], dict) else dict(zip(cols, linhas[0]))
    try:
        return {"sessoes": int(float(linha.get("sessions") or 0)),
                "conversao": round(float(linha.get("conversion_rate") or 0) * (100 if float(linha.get("conversion_rate") or 0) < 1 else 1), 2)}
    except (TypeError, ValueError):
        return {}


# ── escrita ─────────────────────────────────────────────────────────────────
def _gid(tipo: str, x) -> str:
    x = str(x)
    return x if x.startswith("gid://") else f"gid://shopify/{tipo}/{x}"


def _quando(d: str | None, fim: bool = False) -> str | None:
    if not d:
        return None
    if "T" in d:
        return d
    return f"{d}T{'23:59:59' if fim else '00:00:00'}-03:00"


def _clientes_ganham(det: dict) -> dict:
    if det.get("tipo") == "valor":
        valor = {"discountAmount": {"amount": str(det["valor"]), "appliesOnEachItem": False}}
    else:
        valor = {"percentage": round(float(det["valor"]) / 100, 4)}
    prods = [_gid("Product", p) for p in det.get("produtos") or []]
    itens = {"products": {"productsToAdd": prods}} if prods else {"all": True}
    return {"value": valor, "items": itens}


def _minimo(det: dict) -> dict | None:
    if det.get("minimo"):
        return {"subtotal": {"greaterThanOrEqualToSubtotal": str(det["minimo"])}}
    return None


def criar_cupom(loja: dict, det: dict) -> dict:
    entrada = {"title": det.get("titulo") or det["codigo"], "code": det["codigo"].upper(),
               "startsAt": _quando(det.get("inicio")) or dt.datetime.now(dt.timezone.utc).isoformat(),
               "endsAt": _quando(det.get("fim"), fim=True), "customerGets": _clientes_ganham(det),
               "appliesOncePerCustomer": bool(det.get("uma_vez_por_cliente")),
               "context": {"all": "ALL"}}
    if det.get("limite_usos"):
        entrada["usageLimit"] = int(det["limite_usos"])
    if _minimo(det):
        entrada["minimumRequirement"] = _minimo(det)
    m = """mutation($d: DiscountCodeBasicInput!) { discountCodeBasicCreate(basicCodeDiscount: $d) {
           codeDiscountNode { id } userErrors { field message } } }"""
    try:
        r = gql(loja, m, {"d": entrada})["discountCodeBasicCreate"]
        _erros(r)
    except ErroShopify as e:
        if "context" not in str(e).lower():
            raise
        entrada.pop("context")                              # versões antigas: customerSelection
        entrada["customerSelection"] = {"all": True}
        r = gql(loja, m, {"d": entrada})["discountCodeBasicCreate"]
        _erros(r)
    return {"id": r["codeDiscountNode"]["id"], "codigo": entrada["code"]}


def criar_desconto_automatico(loja: dict, det: dict) -> dict:
    entrada = {"title": det.get("titulo") or "Promoção", "startsAt": _quando(det.get("inicio")) or
               dt.datetime.now(dt.timezone.utc).isoformat(), "endsAt": _quando(det.get("fim"), fim=True),
               "customerGets": _clientes_ganham(det)}
    if _minimo(det):
        entrada["minimumRequirement"] = _minimo(det)
    r = gql(loja, """mutation($d: DiscountAutomaticBasicInput!) { discountAutomaticBasicCreate(automaticBasicDiscount: $d) {
               automaticDiscountNode { id } userErrors { field message } } }""", {"d": entrada})["discountAutomaticBasicCreate"]
    _erros(r)
    return {"id": r["automaticDiscountNode"]["id"]}


def desativar_cupom(loja: dict, cupom_id: str, automatico: bool = False) -> dict:
    if automatico or "DiscountAutomatic" in str(cupom_id):
        r = gql(loja, "mutation($id: ID!) { discountAutomaticDeactivate(id: $id) { userErrors { field message } } }",
                {"id": cupom_id})["discountAutomaticDeactivate"]
    else:
        r = gql(loja, "mutation($id: ID!) { discountCodeDeactivate(id: $id) { userErrors { field message } } }",
                {"id": _gid("DiscountCodeNode", cupom_id)})["discountCodeDeactivate"]
    _erros(r)
    return {"desativado": cupom_id}


def _variantes(loja: dict, produto_id: str) -> list[dict]:
    d = gql(loja, "query($id: ID!) { product(id: $id) { variants(first: 100) { nodes { id price compareAtPrice } } } }",
            {"id": _gid("Product", produto_id)})
    return ((d.get("product") or {}).get("variants") or {}).get("nodes") or []


def mudar_precos(loja: dict, produto_id: str, mudancas: list[dict]) -> dict:
    """mudancas: [{id, price, compareAtPrice}] (compareAtPrice None limpa o "de")."""
    r = gql(loja, """mutation($p: ID!, $v: [ProductVariantsBulkInput!]!) { productVariantsBulkUpdate(productId: $p, variants: $v) {
               productVariants { id price compareAtPrice } userErrors { field message } } }""",
            {"p": _gid("Product", produto_id), "v": mudancas})["productVariantsBulkUpdate"]
    _erros(r)
    return {"variantes": r.get("productVariants") or []}


def preco_promocional(loja: dict, det: dict) -> dict:
    """Promoção: o preço cai e o antigo vira o "de" riscado. Guarda os preços de antes
    para voltar sozinho no fim."""
    antes = _variantes(loja, det["produto_id"])
    alvo = set(det.get("variante_ids") or [])
    mud, guardado = [], []
    for v in antes:
        if alvo and v["id"] not in alvo:
            continue
        original = float(det.get("preco_original") or v["price"])
        mud.append({"id": v["id"], "price": str(det["preco_promocional"]), "compareAtPrice": str(original)})
        guardado.append({"id": v["id"], "price": v["price"], "compareAtPrice": v.get("compareAtPrice")})
    if not mud:
        raise ErroShopify("nenhuma variante encontrada para a promoção")
    mudar_precos(loja, det["produto_id"], mud)
    return {"reverter": guardado, "reverter_em": det.get("fim") or ""}


def reverter_precos(loja: dict, produto_id: str, guardado: list[dict]) -> dict:
    return mudar_precos(loja, produto_id, [{"id": g["id"], "price": str(g["price"]),
                                            "compareAtPrice": (str(g["compareAtPrice"]) if g.get("compareAtPrice") else None)}
                                           for g in guardado])


def preco(loja: dict, det: dict) -> dict:
    antes = _variantes(loja, det["produto_id"])
    alvo = set(det.get("variante_ids") or [])
    mud = [{"id": v["id"], "price": str(det["preco_novo"])} for v in antes if not alvo or v["id"] in alvo]
    return mudar_precos(loja, det["produto_id"], mud)


def atualizar_produto(loja: dict, produto_id: str, campos: dict) -> dict:
    entrada = {"id": _gid("Product", produto_id)}
    if campos.get("descricao_html"):
        entrada["descriptionHtml"] = campos["descricao_html"]
    if campos.get("titulo"):
        entrada["title"] = campos["titulo"]
    seo = {k2: campos[k1] for k1, k2 in (("seo_titulo", "title"), ("seo_descricao", "description")) if campos.get(k1)}
    if seo:
        entrada["seo"] = seo
    if campos.get("status"):
        entrada["status"] = campos["status"]
    r = gql(loja, """mutation($p: ProductUpdateInput!) { productUpdate(product: $p) { product { id status } userErrors { field message } } }""",
            {"p": entrada})["productUpdate"]
    _erros(r)
    return {"produto": (r.get("product") or {}).get("id")}

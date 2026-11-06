"""Tray (API REST oficial), com o app de parceiro da HAIZEN instalado na loja.

Conexão: as chaves do app (consumer_key/secret, uma vez só, de quando a HAIZEN
virou parceira) + o endereço da API da loja e o "code" que aparece em Meus
aplicativos depois de instalar o app. A chave de acesso vence em poucas horas e
é renovada sozinha pelo refresh_token.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from haizen.ecommerce import cofre

APP = "_app_tray"          # onde ficam as chaves do app da HAIZEN no cofre


class ErroTray(RuntimeError):
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
        if e.code == 401:
            raise ErroTray(f"a Tray recusou o acesso (401): {corpo}") from None
        if e.code == 429:
            raise ErroTray("a Tray pediu para ir mais devagar (limite de chamadas): tente de novo em alguns minutos") from None
        raise ErroTray(f"HTTP {e.code}: {corpo}") from None
    except urllib.error.URLError as e:
        raise ErroTray(f"sem conexão com a Tray: {e.reason}") from None


def api_limpa(endereco: str) -> str:
    e = (endereco or "").strip().rstrip("/")
    if not e:
        raise ValueError("falta o endereço da API da loja (ex.: https://www.sualoja.com.br/web_api)")
    if not e.startswith("http"):
        e = "https://" + e
    if not re.fullmatch(r"https://[\w.-]+(/[\w./-]*)?", e):
        raise ValueError("endereço da API inválido")
    return e


def salvar_app(consumer_key: str, consumer_secret: str) -> None:
    if len((consumer_key or "").strip()) < 10 or len((consumer_secret or "").strip()) < 10:
        raise ValueError("chaves do app Tray incompletas")
    cofre.gravar(APP, {"consumer_key": consumer_key.strip(), "consumer_secret": consumer_secret.strip()})


def app_configurado() -> bool:
    return bool(cofre.ler(APP).get("consumer_key"))


def _expira(texto: str) -> float:
    try:
        return dt.datetime.strptime(str(texto)[:19], "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return time.time() + 2 * 3600


def conectar(loja: dict, code: str) -> None:
    app = cofre.ler(APP)
    if not app.get("consumer_key"):
        raise ErroTray("primeiro cadastre as chaves do app da HAIZEN na Tray (consumer key e secret)")
    r = _http("POST", f"{loja['dominio']}/auth", json.dumps({"consumer_key": app["consumer_key"],
                                                             "consumer_secret": app["consumer_secret"],
                                                             "code": code.strip()}).encode(),
              {"Content-Type": "application/json"})
    if not r.get("access_token"):
        raise ErroTray(f"a Tray não liberou o acesso: {r.get('message') or r}")
    cofre.gravar(loja["id"], {"access_token": r["access_token"], "refresh_token": r.get("refresh_token", ""),
                              "expira": _expira(r.get("date_expiration_access_token")),
                              "api": (r.get("api_host") or loja["dominio"]).rstrip("/")})


def _acesso(loja: dict) -> tuple[str, str]:
    a = cofre.ler(loja["id"])
    if not a.get("access_token"):
        raise ErroTray("a loja ainda não está conectada (falta o code de Meus aplicativos)")
    api = a.get("api") or loja["dominio"]
    if float(a.get("expira", 0)) < time.time() + 120 and a.get("refresh_token"):
        r = _http("GET", f"{api}/auth?{urllib.parse.urlencode({'refresh_token': a['refresh_token']})}")
        if r.get("access_token"):
            a.update(access_token=r["access_token"], refresh_token=r.get("refresh_token") or a["refresh_token"],
                     expira=_expira(r.get("date_expiration_access_token")))
            cofre.gravar(loja["id"], a)
    return api, a["access_token"]


def _req(loja: dict, metodo: str, caminho: str, params: dict | None = None, corpo: dict | None = None,
         form: dict | None = None) -> dict:
    api, tk = _acesso(loja)
    q = urllib.parse.urlencode({"access_token": tk, **(params or {})})
    dados, cab = None, {}
    if corpo is not None:
        dados, cab = json.dumps(corpo).encode(), {"Content-Type": "application/json"}
    elif form is not None:
        dados, cab = urllib.parse.urlencode(form).encode(), {"Content-Type": "application/x-www-form-urlencoded"}
    return _http(metodo, f"{api}/{caminho.lstrip('/')}?{q}", dados, cab)


def _num(x) -> float:
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _data(x) -> str:
    s = str(x or "")[:10]
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else ""


# ── leitura ─────────────────────────────────────────────────────────────────
def info(loja: dict) -> dict:
    try:
        r = _req(loja, "GET", "info")
        s = r.get("Info") or r.get("Store") or r
        return {"nome": s.get("name") or s.get("store_name") or "", "site": s.get("url") or s.get("domain") or ""}
    except ErroTray:
        _req(loja, "GET", "products", {"limit": 1})          # só confirma o acesso
        return {"nome": "", "site": ""}


def pedidos(loja: dict, desde: dt.date, maximo: int = 3000) -> list[dict]:
    """Pedidos do mais novo para o mais antigo, até passar de `desde`."""
    out, pagina = [], 1
    while len(out) < maximo:
        r = _req(loja, "GET", "orders", {"limit": 50, "page": pagina, "sort": "id_desc"})
        lista = [x.get("Order") or x for x in r.get("Orders") or []]
        if not lista:
            break
        passou = False
        for o in lista:
            data = _data(o.get("date") or o.get("created_at"))
            if data and data < desde.isoformat():
                passou = True
                continue
            status = str(o.get("status") or "").upper()
            cupom = o.get("discount_coupon") or (o.get("DiscountCoupon") or {}).get("code") or ""
            out.append({"id": str(o.get("id")), "numero": str(o.get("id")), "data": data,
                        "total": _num(o.get("total") or o.get("total_amount")), "desconto": _num(o.get("discount")),
                        "cupons": [str(cupom).upper()] if cupom else [], "cancelado": "CANCEL" in status,
                        "itens": [{"produto_id": str(p.get("product_id") or p.get("id") or ""), "nome": p.get("name") or "",
                                   "qtd": int(_num(p.get("quantity"))), "valor": _num(p.get("price")) * _num(p.get("quantity"))}
                                  for p in [(x.get("ProductsSold") or x) for x in (o.get("ProductsSold") or [])]]})
        paging = r.get("paging") or {}
        if passou or pagina * int(paging.get("limit") or 50) >= int(paging.get("total") or 0):
            break
        pagina += 1
    if out and not any(o["itens"] for o in out):
        _completar_itens(loja, out, desde)
    return out


def _completar_itens(loja: dict, ped: list[dict], desde: dt.date) -> None:
    """A listagem de pedidos não traz os itens: busca nos produtos vendidos."""
    por_id = {o["id"]: o for o in ped}
    pagina = 1
    while pagina <= 40:
        try:
            r = _req(loja, "GET", "products_solds", {"limit": 50, "page": pagina, "sort": "id_desc"})
        except ErroTray:
            return
        lista = [x.get("ProductsSold") or x for x in r.get("ProductsSolds") or r.get("ProductsSold") or []]
        if not lista:
            return
        fora = 0
        for p in lista:
            o = por_id.get(str(p.get("order_id")))
            if o is None:
                fora += 1
                continue
            o["itens"].append({"produto_id": str(p.get("product_id") or ""), "nome": p.get("name") or "",
                               "qtd": int(_num(p.get("quantity"))), "valor": _num(p.get("price")) * _num(p.get("quantity"))})
        if fora == len(lista) and pagina > 2:
            return
        pagina += 1


def produtos(loja: dict, maximo: int = 500) -> list[dict]:
    out, pagina = [], 1
    hoje = dt.date.today().isoformat()
    while len(out) < maximo:
        r = _req(loja, "GET", "products", {"limit": 50, "page": pagina})
        lista = [x.get("Product") or x for x in r.get("Products") or []]
        if not lista:
            break
        for p in lista:
            promo = _num(p.get("promotional_price"))
            ini, fim = _data(p.get("start_promotion")), _data(p.get("end_promotion"))
            em_promo = promo > 0 and (not ini or ini <= hoje) and (not fim or fim >= hoje)
            out.append({"id": str(p.get("id")), "nome": p.get("name") or "", "ativo": str(p.get("available")) == "1",
                        "status": "ACTIVE" if str(p.get("available")) == "1" else "INACTIVE",
                        "estoque": int(_num(p.get("stock"))), "criado": _data(p.get("creation_date") or p.get("created")),
                        "preco": promo if em_promo else _num(p.get("price")),
                        "preco_de": _num(p.get("price")) if em_promo else None,
                        "promocao": {"preco": promo, "inicio": ini, "fim": fim} if promo else None,
                        "tipo": str(p.get("category_name") or ""), "link": (p.get("url") or {}).get("https", "")
                        if isinstance(p.get("url"), dict) else str(p.get("url") or ""),
                        "seo_titulo": p.get("metatag_title") or "", "seo_descricao": p.get("metatag_description") or "",
                        "variantes": []})
        paging = r.get("paging") or {}
        if pagina * int(paging.get("limit") or 50) >= int(paging.get("total") or 0):
            break
        pagina += 1
    return out


def cupons(loja: dict) -> list[dict]:
    try:
        r = _req(loja, "GET", "discount_coupons", {"limit": 50, "sort": "id_desc"})
    except ErroTray:
        return []
    hoje = dt.date.today().isoformat()
    out = []
    for c in [x.get("DiscountCoupon") or x for x in r.get("DiscountCoupons") or []]:
        fim = _data(c.get("ends_at"))
        out.append({"id": str(c.get("id")), "codigo": str(c.get("code") or "").upper(),
                    "titulo": c.get("description") or "", "automatico": False,
                    "status": "expired" if fim and fim < hoje else "active",
                    "inicio": _data(c.get("starts_at")), "fim": fim, "usos": c.get("usage_counter")})
    return out


def visitas(loja: dict, dias: int = 30) -> dict:
    return {}                       # a API da Tray não traz visitas nem conversão


# ── escrita ─────────────────────────────────────────────────────────────────
def criar_cupom(loja: dict, det: dict) -> dict:
    hoje = dt.date.today()
    campos = {"code": det["codigo"].upper(), "description": det.get("titulo") or det["codigo"],
              "type": "$" if det.get("tipo") == "valor" else "%", "value": f"{float(det['valor']):.2f}",
              "starts_at": det.get("inicio") or hoje.isoformat(),
              "ends_at": det.get("fim") or (hoje + dt.timedelta(days=30)).isoformat(),
              "local_application": "produtos" if det.get("produtos") else "loja",
              "freight_application": "frete_gratis" if det.get("frete_gratis") else "nao_aplicavel",
              "cumulative_discount": "0"}
    if det.get("minimo"):
        campos["value_start"] = f"{float(det['minimo']):.2f}"
    if det.get("limite_usos"):
        campos["usage_sum_limit"] = str(int(det["limite_usos"]))
    if det.get("uma_vez_por_cliente"):
        campos["usage_counter_limit_customer"] = "1"
    r = _req(loja, "POST", "discount_coupons", form={f"DiscountCoupon[{k}]": v for k, v in campos.items()})
    cid = str(r.get("id") or (r.get("DiscountCoupon") or {}).get("id") or "")
    if not cid:
        raise ErroTray(f"a Tray não criou o cupom: {r.get('message') or r}")
    if det.get("produtos"):
        _req(loja, "POST", f"discount_coupons/create_relationship/{cid}",
             corpo={"DiscountCouponProduct": [{"product_id": str(p)} for p in det["produtos"]]})
    return {"id": cid, "codigo": campos["code"]}


def desativar_cupom(loja: dict, cupom_id: str, automatico: bool = False) -> dict:
    ontem = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    _req(loja, "PUT", f"discount_coupons/{cupom_id}", form={"DiscountCoupon[ends_at]": ontem})
    return {"desativado": cupom_id}


def _put_produto(loja: dict, produto_id: str, campos: dict) -> dict:
    r = _req(loja, "PUT", f"products/{produto_id}", corpo={"Product": campos})
    if str(r.get("code", "200"))[:1] not in ("2", "") and r.get("message"):
        raise ErroTray(str(r.get("message"))[:300])
    return {"produto": produto_id}


def preco_promocional(loja: dict, det: dict) -> dict:
    hoje = dt.date.today()
    _put_produto(loja, det["produto_id"], {
        "promotional_price": f"{float(det['preco_promocional']):.2f}",
        "start_promotion": det.get("inicio") or hoje.isoformat(),
        "end_promotion": det.get("fim") or (hoje + dt.timedelta(days=7)).isoformat()})
    return {"reverter": [], "reverter_em": ""}               # a própria Tray encerra no fim


def preco(loja: dict, det: dict) -> dict:
    return _put_produto(loja, det["produto_id"], {"price": f"{float(det['preco_novo']):.2f}"})


def atualizar_produto(loja: dict, produto_id: str, campos: dict) -> dict:
    mud = {}
    if campos.get("descricao_html"):
        mud["description"] = campos["descricao_html"]
    if campos.get("titulo"):
        mud["name"] = campos["titulo"]
    if campos.get("seo_titulo"):
        mud["metatag_title"] = campos["seo_titulo"]
    if campos.get("seo_descricao"):
        mud["metatag_description"] = campos["seo_descricao"]
    if campos.get("status"):
        mud["available"] = "1" if campos["status"] == "ACTIVE" else "0"
    return _put_produto(loja, produto_id, mud)

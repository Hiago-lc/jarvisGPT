"""Cliente da Google Ads API (REST), sem bibliotecas do Google.

Acesso: OAuth do Google com um cliente "App para computador" de um projeto do
Google Cloud com a Google Ads API ativada (desde setembro de 2026 não existe
mais developer token: o nível de acesso é do projeto; o "Explorer" já permite
contas reais, até 2.880 operações por dia). O refresh token fica criptografado
só neste PC.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from haizen.ecommerce import cofre

# Google Ads + envio de vídeo ao YouTube (anúncio em vídeo só usa vídeo do YouTube).
ESCOPO = "https://www.googleapis.com/auth/adwords https://www.googleapis.com/auth/youtube.upload"
VERSOES = [v for v in (os.environ.get("HAIZEN_GADS_API", ""), "v25", "v24", "v23", "v22") if v]
_CHAVE = "_google_ads"          # no cofre: client_id, client_secret, refresh_token, token, expira, versao
_PENDENTE: dict = {}            # state -> {verifier, redirect, criado}


class ErroGoogleAds(RuntimeError):
    pass


def _http(metodo: str, url: str, dados: bytes | None = None, cab: dict | None = None, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            corpo = json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            corpo = {}
        raise ErroGoogleAds(_mensagem(e.code, corpo)) from None
    except urllib.error.URLError as e:
        raise ErroGoogleAds(f"sem conexão com o Google: {e.reason}") from None


def _mensagem(codigo: int, corpo: dict) -> str:
    if isinstance(corpo, list):
        corpo = corpo[0] if corpo else {}
    err = corpo.get("error") or {}
    if isinstance(err, str):                       # resposta do OAuth
        return {"invalid_grant": "a autorização do Google venceu ou foi revogada: conecte de novo na tela Google Ads",
                "invalid_client": "Client ID ou Client secret errados"}.get(err, f"{err}: {corpo.get('error_description', '')}")
    msg = err.get("message") or f"HTTP {codigo}"
    detalhes = []
    for d in err.get("details") or []:
        for e in d.get("errors") or []:
            codigo_ga = next(iter((e.get("errorCode") or {}).values()), "")
            detalhes.append(f"{codigo_ga}: {e.get('message', '')}".strip(": "))
    texto = "; ".join(detalhes) or msg
    if "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION" in texto or "ACTION_NOT_PERMITTED" in texto:
        texto += (" — o projeto do Google Cloud ainda está em acesso de teste: no Console, abra Google Ads API → "
                  "Visão geral → Upgrade access level → Apply for access (Explorer)")
    if "SERVICE_DISABLED" in texto or "has not been used in project" in texto:
        texto += " — ative a Google Ads API no projeto do Google Cloud"
    if codigo == 401:
        texto = "o Google recusou o acesso: conecte de novo na tela Google Ads. " + texto
    return texto[:700]


# ── OAuth (no navegador deste PC) ───────────────────────────────────────────
def salvar_cliente(client_id: str, client_secret: str) -> None:
    client_id, client_secret = (client_id or "").strip(), (client_secret or "").strip()
    if client_id.startswith("{"):                  # colou o JSON baixado do Cloud
        dados = json.loads(client_id)
        bloco = dados.get("installed") or dados.get("web") or {}
        client_id, client_secret = bloco.get("client_id", ""), bloco.get("client_secret", client_secret)
    if not client_id.endswith(".apps.googleusercontent.com") or len(client_secret) < 10:
        raise ValueError("Client ID (termina em .apps.googleusercontent.com) e Client secret do cliente OAuth "
                         "\"App para computador\"")
    a = cofre.ler(_CHAVE)
    a.update(client_id=client_id, client_secret=client_secret)
    cofre.gravar(_CHAVE, a)


def conectado() -> bool:
    return bool(cofre.ler(_CHAVE).get("refresh_token"))


def tem_cliente() -> bool:
    return bool(cofre.ler(_CHAVE).get("client_id"))


def url_autorizacao(redirect: str, youtube: bool = True) -> str:
    a = cofre.ler(_CHAVE)
    if not a.get("client_id"):
        raise ValueError("primeiro cole o Client ID e o Client secret")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    _PENDENTE.clear()
    _PENDENTE[state] = {"verifier": verifier, "redirect": redirect, "criado": time.time()}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": a["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": ESCOPO if youtube else ESCOPO.split()[0],
        "access_type": "offline", "prompt": "consent", "state": state, "code_challenge": desafio,
        "code_challenge_method": "S256"})


def concluir(state: str, code: str) -> None:
    p = _PENDENTE.pop(state or "", None)
    if not p or time.time() - p["criado"] > 900:
        raise ValueError("a autorização expirou ou não foi pedida por este Jarvis: clique em Conectar de novo")
    a = cofre.ler(_CHAVE)
    r = _http("POST", "https://oauth2.googleapis.com/token", urllib.parse.urlencode({
        "code": code, "client_id": a["client_id"], "client_secret": a["client_secret"], "redirect_uri": p["redirect"],
        "grant_type": "authorization_code", "code_verifier": p["verifier"]}).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"})
    if not r.get("refresh_token"):
        raise ErroGoogleAds("o Google não devolveu o refresh token: remova o acesso do app em myaccount.google.com/"
                            "permissions e conecte de novo")
    a.update(refresh_token=r["refresh_token"], token=r.get("access_token", ""),
             expira=time.time() + int(r.get("expires_in") or 3000), conectado_em=time.time())
    cofre.gravar(_CHAVE, a)


def desconectar() -> None:
    a = cofre.ler(_CHAVE)
    for k in ("refresh_token", "token", "expira"):
        a.pop(k, None)
    cofre.gravar(_CHAVE, a)


def _token() -> str:
    a = cofre.ler(_CHAVE)
    if not a.get("refresh_token"):
        raise ErroGoogleAds("o Google Ads ainda não está conectado (tela Google Ads → Conectar)")
    if a.get("token") and float(a.get("expira", 0)) > time.time() + 120:
        return a["token"]
    r = _http("POST", "https://oauth2.googleapis.com/token", urllib.parse.urlencode({
        "client_id": a["client_id"], "client_secret": a["client_secret"], "refresh_token": a["refresh_token"],
        "grant_type": "refresh_token"}).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
    a.update(token=r["access_token"], expira=time.time() + int(r.get("expires_in") or 3000))
    cofre.gravar(_CHAVE, a)
    return a["token"]


# ── chamadas ────────────────────────────────────────────────────────────────
def _chamar(metodo: str, caminho: str, corpo: dict | None = None, login_id: str = "") -> dict:
    a = cofre.ler(_CHAVE)
    versoes = [a["versao"]] if a.get("versao") else VERSOES
    cab = {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}
    if login_id:
        cab["login-customer-id"] = str(login_id).replace("-", "")
    ultimo = None
    for v in versoes:
        try:
            r = _http(metodo, f"https://googleads.googleapis.com/{v}/{caminho}",
                      json.dumps(corpo).encode() if corpo is not None else None, cab, timeout=120)
            if not a.get("versao"):
                a["versao"] = v
                cofre.gravar(_CHAVE, a)
            return r
        except ErroGoogleAds as e:
            ultimo = e
            if "HTTP 404" in str(e) or "not found" in str(e).lower() and "version" in str(e).lower():
                continue                      # versão da API desligada: tenta a anterior
            raise
    if a.get("versao"):                       # a versão guardada saiu do ar
        a.pop("versao")
        cofre.gravar(_CHAVE, a)
    raise ultimo or ErroGoogleAds("API indisponível")


def gaql(conta: dict, consulta: str) -> list[dict]:
    cid = str(conta["id"]).replace("-", "")
    linhas, pagina = [], None
    while True:
        corpo = {"query": " ".join(consulta.split())}
        if pagina:
            corpo["pageToken"] = pagina
        r = _chamar("POST", f"customers/{cid}/googleAds:search", corpo, conta.get("login_id", ""))
        linhas += r.get("results") or []
        pagina = r.get("nextPageToken")
        if not pagina or len(linhas) >= 5000:
            return linhas


def mutate(conta: dict, recurso: str, operacoes: list[dict]) -> dict:
    cid = str(conta["id"]).replace("-", "")
    return _chamar("POST", f"customers/{cid}/{recurso}:mutate", {"operations": operacoes},
                   conta.get("login_id", ""))


def mutate_tudo(conta: dict, operacoes: list[dict]) -> dict:
    """Várias criações de uma vez, tudo ou nada (ids temporários negativos ligam as peças)."""
    cid = str(conta["id"]).replace("-", "")
    return _chamar("POST", f"customers/{cid}/googleAds:mutate", {"mutateOperations": operacoes},
                   conta.get("login_id", ""))


def sugerir_locais(nomes: list[str]) -> dict[str, dict]:
    """Nome da cidade/estado → geoTargetConstant do Google (Brasil)."""
    if not nomes:
        return {}
    r = _chamar("POST", "geoTargetConstants:suggest", {"locale": "pt-BR", "countryCode": "BR",
                                                      "locationNames": {"names": nomes}})
    achados = {}
    for sug in r.get("geoTargetConstantSuggestions") or []:
        g = sug.get("geoTargetConstant") or {}
        chave = str(sug.get("searchTerm") or g.get("name") or "").lower()
        if chave and chave not in achados and g.get("status", "ENABLED") == "ENABLED":
            achados[chave] = {"recurso": g.get("resourceName"), "nome": g.get("canonicalName") or g.get("name"),
                              "tipo": g.get("targetType")}
    return achados


def contas_acessiveis() -> list[dict]:
    """As contas que o seu login enxerga, abrindo as contas de administrador (MCC)."""
    nomes = (_chamar("GET", "customers:listAccessibleCustomers").get("resourceNames") or [])
    out, vistos = [], set()
    for rn in nomes:
        cid = rn.split("/")[-1]
        try:
            filhos = gaql({"id": cid, "login_id": cid},
                          "SELECT customer_client.id, customer_client.descriptive_name, customer_client.manager, "
                          "customer_client.status, customer_client.currency_code, customer_client.level "
                          "FROM customer_client WHERE customer_client.level <= 1")
        except ErroGoogleAds:
            filhos = []
        for f in filhos:
            c = f.get("customerClient") or {}
            fid = str(c.get("id") or "")
            if not fid or fid in vistos or c.get("manager") or c.get("status") not in (None, "ENABLED"):
                continue
            vistos.add(fid)
            out.append({"id": fid, "nome": c.get("descriptiveName") or fid, "moeda": c.get("currencyCode") or "",
                        "login_id": cid if fid != cid else ""})
    return out


def formatar_id(cid: str) -> str:
    d = str(cid).replace("-", "")
    return f"{d[:3]}-{d[3:6]}-{d[6:]}" if len(d) == 10 else d

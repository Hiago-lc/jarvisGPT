"""Instagram da HAIZEN pela API oficial da Meta (Instagram API com login do Facebook).

Precisa de um token de usuário gerado com o app da Meta da HAIZEN, com as
permissões: instagram_basic, instagram_manage_insights, instagram_content_publish,
pages_show_list, pages_read_engagement, pages_manage_posts e business_management.
O token fica só neste PC (variável HAIZEN_IG_TOKEN ou %LOCALAPPDATA%\\JarvisGPT\\
instagram_token.json), nunca no repositório.

Publicar imagem exige um endereço público da imagem: o arquivo sobe como foto NÃO
publicada da Página do Facebook ligada ao Instagram e o endereço dela é usado no
Instagram. Vídeo (reels) sobe direto do PC (upload resumível).
"""
from __future__ import annotations

import json
import re
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

VERSAO = os.environ.get("HAIZEN_GRAPH_VERSAO", "v25.0")
GRAPH = f"https://graph.facebook.com/{VERSAO}"
RUPLOAD = f"https://rupload.facebook.com/ig-api-upload/{VERSAO}"
PERMISSOES = ("instagram_basic", "instagram_manage_insights", "instagram_content_publish", "pages_show_list",
              "pages_read_engagement", "pages_manage_posts", "business_management")
METRICAS_POST = ("reach", "views", "saved", "shares", "total_interactions", "likes", "comments", "follows",
                 "profile_visits")
METRICAS_REELS = ("reach", "views", "saved", "shares", "total_interactions", "likes", "comments",
                  "ig_reels_avg_watch_time", "reels_skip_rate")


class ErroInstagram(RuntimeError):
    pass


# ── token ───────────────────────────────────────────────────────────────────
def _arq_token() -> Path:
    from core.data_paths import data_dir
    return Path(data_dir()) / "instagram_token.json"


def token() -> str:
    t = os.environ.get("HAIZEN_IG_TOKEN", "").strip()
    if t:
        return t
    try:
        guardado = json.loads(_arq_token().read_text(encoding="utf-8")).get("token", "")
    except (OSError, ValueError):
        return ""
    from haizen import segredo
    try:
        t = segredo.abrir(guardado)
    except OSError:
        return ""
    if t and not segredo.fechado(guardado):
        try:
            salvar_token(t)              # token antigo em texto puro: passa a ficar criptografado
        except (OSError, ValueError):
            pass
    return t


def conferir_formato(t: str) -> str:
    """Barra o que não é token de usuário: o "Token do cliente" (32 letras/números), a
    "Chave secreta do app" e o ID do app costumam ser colados por engano."""
    t = (t or "").strip().strip('"').strip()
    if not t or " " in t:
        raise ValueError("cole só o token, sem espaços")
    if re.fullmatch(r"[0-9a-f]{32}", t):
        raise ValueError("isso é o \"Token do cliente\" ou a \"Chave secreta\" do app, não o token de acesso. Gere o "
                         "token no Explorador da Graph API (botão Generate Access Token): ele começa com EAA e é bem "
                         "mais comprido")
    if t.isdigit() or "|" in t:
        raise ValueError("isso é o ID do app (ou token de app), não o token de acesso do usuário. Gere no Explorador "
                         "da Graph API: ele começa com EAA")
    if not t.startswith("EA") or len(t) < 100:
        raise ValueError("isso não parece um token de acesso da Meta (ele começa com EAA e tem mais de 100 "
                         "caracteres). Copie de novo do Explorador da Graph API ou do Depurador de Token")
    return t


def salvar_token(t: str) -> None:
    t = (t or "").strip()
    if len(t) < 30 or " " in t:
        raise ValueError("isso não parece um token de acesso da Meta")
    from haizen import segredo
    _arq_token().write_text(json.dumps({"token": segredo.fechar(t), "em": time.time()}), encoding="utf-8")


def apagar_token() -> None:
    try:
        _arq_token().unlink()
    except OSError:
        pass


# ── HTTP ────────────────────────────────────────────────────────────────────
def _http(metodo: str, url: str, dados: bytes | None = None, cabecalhos: dict | None = None,
          timeout: int = 60) -> dict:
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cabecalhos or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            erro = json.loads(e.read()).get("error") or {}
        except Exception:  # noqa: BLE001
            erro = {}
        msg = erro.get("error_user_msg") or erro.get("message") or f"HTTP {e.code}"
        if erro.get("code") in (190, 102) or e.code == 401:
            msg = ("o acesso ao Instagram venceu ou o token guardado não vale: clique em \"Trocar token\" na aba Social "
                   f"({msg})")
        raise ErroInstagram(msg) from None
    except urllib.error.URLError as e:
        raise ErroInstagram(f"sem conexão com a Meta: {e.reason}") from None


def _get(caminho: str, tk: str | None = None, **params) -> dict:
    params["access_token"] = tk or token()
    if not params["access_token"]:
        raise ErroInstagram("o Instagram ainda não está conectado (cole o token na aba Social)")
    return _http("GET", f"{GRAPH}/{caminho}?{urllib.parse.urlencode(params)}")


def _post(caminho: str, tk: str | None = None, **params) -> dict:
    params["access_token"] = tk or token()
    if not params["access_token"]:
        raise ErroInstagram("o Instagram ainda não está conectado (cole o token na aba Social)")
    return _http("POST", f"{GRAPH}/{caminho}", urllib.parse.urlencode(params).encode(),
                 {"Content-Type": "application/x-www-form-urlencoded"})


# ── conta ───────────────────────────────────────────────────────────────────
def info_do_token(tk: str | None = None) -> dict:
    """Quando o token vence (0 = não vence) e se ainda vale, pelo depurador da própria Meta."""
    tk = tk or token()
    try:
        d = (_get("debug_token", tk, input_token=tk).get("data") or {})
    except ErroInstagram:
        return {}
    return {"valido": bool(d.get("is_valid")), "vence_em": int(d.get("expires_at") or 0),
            "acesso_vence_em": int(d.get("data_access_expires_at") or 0), "escopos": d.get("scopes") or []}


def contas(tk: str | None = None) -> list[dict]:
    """As contas do Instagram ligadas às Páginas do token: [{ig_id, username, page_id, page_nome}]."""
    r = _get("me/accounts", tk, fields="id,name,access_token,instagram_business_account{id,username,name}", limit=100)
    out = []
    for p in r.get("data") or []:
        ig = p.get("instagram_business_account")
        if ig:
            out.append({"ig_id": ig["id"], "username": ig.get("username", ""), "nome": ig.get("name", ""),
                        "page_id": p["id"], "page_nome": p.get("name", "")})
    return out


def _token_da_pagina(page_id: str) -> str:
    r = _get("me/accounts", fields="id,access_token", limit=100)
    for p in r.get("data") or []:
        if p["id"] == page_id and p.get("access_token"):
            return p["access_token"]
    raise ErroInstagram("não achei a Página do Facebook ligada ao Instagram neste token")


def perfil(ig_id: str) -> dict:
    return _get(ig_id, fields="id,username,name,biography,website,followers_count,follows_count,media_count,"
                               "profile_picture_url")


def _insights(media: dict) -> dict:
    reels = media.get("media_product_type") == "REELS"
    metricas = METRICAS_REELS if reels else METRICAS_POST
    try:
        r = _get(f"{media['id']}/insights", metric=",".join(metricas))
    except ErroInstagram:
        # Uma métrica que não existe para o tipo derruba o pedido todo: tenta o básico.
        try:
            r = _get(f"{media['id']}/insights", metric="reach,saved,shares,total_interactions")
        except ErroInstagram:
            return {}
    out = {}
    for m in r.get("data") or []:
        valores = m.get("values") or [{}]
        out[m["name"]] = (m.get("total_value") or {}).get("value", valores[0].get("value"))
    return out


def posts(ig_id: str, limite: int = 30, com_insights: bool = True) -> list[dict]:
    r = _get(f"{ig_id}/media", limit=min(limite, 50),
             fields="id,caption,media_type,media_product_type,timestamp,like_count,comments_count,permalink,"
                    "thumbnail_url,media_url")
    lista = r.get("data") or []
    if com_insights:
        for m in lista:
            m["insights"] = _insights(m)
    return lista


def insights_da_conta(ig_id: str, dias: int = 28) -> dict:
    """Alcance, visitas ao perfil, seguidores ganhos... o que a Meta liberar (métricas mudam)."""
    agora = int(time.time())
    out = {}
    for metrica in ("reach", "profile_views", "accounts_engaged", "total_interactions", "follows_and_unfollows",
                    "website_clicks", "views"):
        try:
            r = _get(f"{ig_id}/insights", metric=metrica, period="day", metric_type="total_value",
                     since=agora - dias * 86400, until=agora)
        except ErroInstagram:
            continue
        for m in r.get("data") or []:
            out[m["name"]] = (m.get("total_value") or {}).get("value")
    try:
        r = _get(f"{ig_id}/insights", metric="follower_count", period="day", since=agora - dias * 86400, until=agora)
        valores = (r.get("data") or [{}])[0].get("values") or []
        out["seguidores_ganhos_por_dia"] = [v.get("value") for v in valores]
    except ErroInstagram:
        pass
    return out


def outro_perfil(ig_id: str, username: str, limite: int = 25) -> dict:
    """Perfil público de outra conta profissional (concorrente, referência)."""
    u = username.strip().lstrip("@").split("/")[0]
    campos = (f"business_discovery.username({u}){{username,name,biography,followers_count,media_count,"
              f"media.limit({limite}){{id,caption,media_type,media_product_type,timestamp,like_count,"
              f"comments_count,permalink,media_url,thumbnail_url}}}}")
    r = _get(ig_id, fields=campos)
    bd = r.get("business_discovery") or {}
    if not bd:
        raise ErroInstagram(f"não consegui ver @{u}: só dá para analisar contas profissionais (empresa ou criador)")
    bd["posts"] = (bd.pop("media", {}) or {}).get("data") or []
    return bd


# ── publicar ────────────────────────────────────────────────────────────────
def _jpeg(arquivo: Path) -> Path:
    """O Instagram só aceita JPEG por endereço: PNG vira JPEG ao lado (fundo branco)."""
    if arquivo.suffix.lower() in (".jpg", ".jpeg"):
        return arquivo
    from PIL import Image
    destino = arquivo.with_suffix(".instagram.jpg")
    with Image.open(arquivo) as im:
        fundo = Image.new("RGB", im.size, (255, 255, 255))
        fundo.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
        fundo.save(destino, "JPEG", quality=92)
    return destino


def _multipart(campos: dict, arquivo: Path, nome_campo: str = "source") -> tuple[bytes, str]:
    limite = uuid.uuid4().hex
    partes = []
    for k, v in campos.items():
        partes.append(f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    partes.append(f"--{limite}\r\nContent-Disposition: form-data; name=\"{nome_campo}\"; filename=\"{arquivo.name}\"\r\n"
                  f"Content-Type: image/jpeg\r\n\r\n".encode() + arquivo.read_bytes() + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


def endereco_publico(page_id: str, arquivo: Path) -> str:
    """Sobe a imagem como foto NÃO publicada da Página e devolve o endereço dela."""
    tk = _token_da_pagina(page_id)
    corpo, tipo = _multipart({"published": "false", "access_token": tk}, _jpeg(arquivo))
    foto = _http("POST", f"{GRAPH}/{page_id}/photos", corpo, {"Content-Type": tipo}, timeout=180)
    r = _get(foto["id"], tk, fields="images")
    imagens = sorted(r.get("images") or [], key=lambda x: -int(x.get("width") or 0))
    if not imagens:
        raise ErroInstagram("a Meta não devolveu o endereço da imagem enviada")
    return imagens[0]["source"]


def _esperar(container: str, limite: int = 600) -> None:
    fim = time.time() + limite
    while time.time() < fim:
        r = _get(container, fields="status_code,status")
        if r.get("status_code") == "FINISHED":
            return
        if r.get("status_code") in ("ERROR", "EXPIRED"):
            raise ErroInstagram(f"a Meta recusou a mídia: {r.get('status') or r.get('status_code')}")
        time.sleep(5)
    raise ErroInstagram("a Meta demorou demais para processar a mídia")


def _video(ig_id: str, arquivo: Path, legenda: str, reels: bool = True, carrossel: bool = False) -> str:
    params = {"upload_type": "resumable", "media_type": "REELS" if reels and not carrossel else "VIDEO"}
    if carrossel:
        params["is_carousel_item"] = "true"
    elif legenda:
        params["caption"] = legenda
    c = _post(f"{ig_id}/media", **params)
    dados = arquivo.read_bytes()
    _http("POST", f"{RUPLOAD}/{c['id']}", dados,
          {"Authorization": f"OAuth {token()}", "offset": "0", "file_size": str(len(dados))}, timeout=900)
    _esperar(c["id"])
    return c["id"]


def publicar(ig_id: str, page_id: str, arquivos: list[Path], legenda: str) -> dict:
    """Publica agora: 1 imagem, 1 vídeo (reels) ou carrossel (2 a 10). Devolve id e link."""
    arquivos = [Path(a) for a in arquivos]
    if not arquivos:
        raise ErroInstagram("nada para publicar")
    if len(arquivos) > 10:
        raise ErroInstagram("carrossel aceita no máximo 10 itens")
    video = lambda f: f.suffix.lower() in (".mp4", ".mov")  # noqa: E731
    if len(arquivos) == 1:
        f = arquivos[0]
        if video(f):
            cid = _video(ig_id, f, legenda)
        else:
            cid = _post(f"{ig_id}/media", image_url=endereco_publico(page_id, f), caption=legenda)["id"]
            _esperar(cid)
    else:
        filhos = []
        for f in arquivos:
            if video(f):
                filhos.append(_video(ig_id, f, "", carrossel=True))
            else:
                filhos.append(_post(f"{ig_id}/media", image_url=endereco_publico(page_id, f),
                                    is_carousel_item="true")["id"])
        for fid in filhos:
            _esperar(fid)
        cid = _post(f"{ig_id}/media", media_type="CAROUSEL", children=",".join(filhos), caption=legenda)["id"]
        _esperar(cid)
    pub = _post(f"{ig_id}/media_publish", creation_id=cid)
    link = ""
    try:
        link = _get(pub["id"], fields="permalink").get("permalink", "")
    except ErroInstagram:
        pass
    return {"id": pub["id"], "permalink": link}

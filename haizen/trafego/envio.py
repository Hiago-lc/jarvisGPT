"""Envio das peças (imagem e vídeo) para a conta de anúncios do Meta, antes de o
gestor criar os anúncios.

O conector oficial da Meta cria criativo só com image_hash/image_url/video_id de
mídia que já está na conta: ele não envia arquivo do PC. Aqui o próprio Jarvis
envia pela Marketing API (/adimages e /advideos) com um token que tenha
ads_management — de preferência o de um "usuário do sistema" do Gerenciador de
Negócios (não vence). Sem esse token, para imagem, tenta o endereço público por
uma foto não publicada da Página da HAIZEN (o anúncio copia a imagem).
"""
from __future__ import annotations

import base64
import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from haizen.ecommerce import cofre

VERSAO = "v25.0"
GRAPH = f"https://graph.facebook.com/{VERSAO}"
GRAPH_VIDEO = f"https://graph-video.facebook.com/{VERSAO}"
_CHAVE = "_meta_ads"
IMAGENS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
VIDEOS = (".mp4", ".mov", ".m4v")


class ErroEnvio(RuntimeError):
    pass


def _http(metodo: str, url: str, dados: bytes | None = None, cab: dict | None = None, timeout: int = 300) -> dict:
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            erro = (json.loads(e.read() or b"{}").get("error") or {})
        except Exception:  # noqa: BLE001
            erro = {}
        msg = erro.get("error_user_msg") or erro.get("message") or f"HTTP {e.code}"
        if erro.get("code") in (190, 102):
            msg = "o token do Meta Ads venceu ou foi revogado: troque em Tráfego → Configurar"
        elif erro.get("code") in (10, 200, 294) or "permission" in msg.lower():
            msg = ("o token não tem permissão de anúncios (ads_management) nesta conta: gere o token de um usuário do "
                   f"sistema com acesso à conta ({msg})")
        raise ErroEnvio(msg[:400]) from None
    except urllib.error.URLError as e:
        raise ErroEnvio(f"sem conexão com o Meta: {e.reason}") from None


# ── token ───────────────────────────────────────────────────────────────────
def salvar_token(t: str) -> None:
    t = (t or "").strip()
    if not t.startswith("EA") or len(t) < 100:
        raise ValueError("isso não parece um token de acesso da Meta (começa com EAA e é bem comprido)")
    cofre.gravar(_CHAVE, {"token": t, "em": time.time()})


def apagar_token() -> None:
    cofre.apagar(_CHAVE)


def token_proprio() -> str:
    return cofre.ler(_CHAVE).get("token", "")


def token() -> str:
    """O token de anúncios cadastrado; senão o do Instagram da HAIZEN (se tiver ads_management)."""
    if token_proprio():
        return token_proprio()
    try:
        from haizen.social import instagram
        return instagram.token()
    except Exception:  # noqa: BLE001
        return ""


def situacao() -> dict:
    """Se o envio está pronto, para a tela."""
    tk = token()
    if not tk:
        return {"pronto": False, "origem": "", "aviso": "Sem token do Meta Ads: cadastre um em Configurar para o Jarvis "
                                                         "subir imagens e vídeos."}
    try:
        d = _http("GET", f"{GRAPH}/debug_token?" + urllib.parse.urlencode({"input_token": tk, "access_token": tk}),
                  timeout=30).get("data") or {}
    except ErroEnvio as e:
        return {"pronto": False, "origem": "proprio" if token_proprio() else "instagram", "aviso": str(e)}
    escopos = d.get("scopes") or []
    ok = d.get("is_valid") and "ads_management" in escopos
    return {"pronto": bool(ok), "origem": "proprio" if token_proprio() else "instagram",
            "vence_em": int(d.get("expires_at") or 0),
            "aviso": "" if ok else "O token não tem a permissão ads_management: o Jarvis não consegue subir arquivos."}


def _act(conta_id: str) -> str:
    c = str(conta_id).strip()
    return c if c.startswith("act_") else f"act_{c}"


# ── envio ───────────────────────────────────────────────────────────────────
def subir_imagem(conta_id: str, arquivo: Path) -> dict:
    """{hash, url} da imagem na biblioteca da conta de anúncios."""
    tk = token()
    if not tk:
        raise ErroEnvio("sem token do Meta Ads (Tráfego → Configurar)")
    dados = urllib.parse.urlencode({"bytes": base64.b64encode(arquivo.read_bytes()).decode(), "name": arquivo.name,
                                    "access_token": tk}).encode()
    r = _http("POST", f"{GRAPH}/{_act(conta_id)}/adimages", dados, {"Content-Type": "application/x-www-form-urlencoded"})
    imgs = r.get("images") or {}
    info = next(iter(imgs.values()), {}) if isinstance(imgs, dict) else {}
    if not info.get("hash"):
        raise ErroEnvio(f"o Meta não devolveu o hash da imagem: {r}")
    return {"image_hash": info["hash"], "image_url": info.get("url", "")}


def _multipart(campos: dict, arquivo: Path, nome_campo: str = "source") -> tuple[bytes, str]:
    limite = uuid.uuid4().hex
    tipo = mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream"
    partes = [f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode() for k, v in campos.items()]
    partes.append(f"--{limite}\r\nContent-Disposition: form-data; name=\"{nome_campo}\"; filename=\"{arquivo.name}\"\r\n"
                  f"Content-Type: {tipo}\r\n\r\n".encode() + arquivo.read_bytes() + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


def subir_video(conta_id: str, arquivo: Path, titulo: str = "", esperar: int = 900) -> dict:
    """{video_id, thumbnail_url} do vídeo na conta, esperando o Meta processar."""
    tk = token()
    if not tk:
        raise ErroEnvio("sem token do Meta Ads (Tráfego → Configurar)")
    if arquivo.stat().st_size > 1_000_000_000:
        raise ErroEnvio("vídeo acima de 1 GB: suba pelo Gerenciador")
    corpo, tipo = _multipart({"access_token": tk, "name": titulo or arquivo.stem}, arquivo)
    r = _http("POST", f"{GRAPH_VIDEO}/{_act(conta_id)}/advideos", corpo, {"Content-Type": tipo}, timeout=3600)
    vid = str(r.get("id") or "")
    if not vid:
        raise ErroEnvio(f"o Meta não devolveu o id do vídeo: {r}")
    fim = time.time() + esperar
    miniatura = ""
    while time.time() < fim:
        st = _http("GET", f"{GRAPH}/{vid}?" + urllib.parse.urlencode({"fields": "status,picture", "access_token": tk}),
                   timeout=60)
        estado = ((st.get("status") or {}).get("video_status") or "").lower()
        miniatura = st.get("picture") or miniatura
        if estado == "ready":
            break
        if estado == "error":
            raise ErroEnvio("o Meta não conseguiu processar o vídeo")
        time.sleep(10)
    return {"video_id": vid, "thumbnail_url": miniatura}


def endereco_publico(arquivo: Path) -> str:
    """Plano B para imagem sem token de anúncios: foto não publicada na Página da HAIZEN."""
    from haizen import social
    from haizen.social import instagram
    page = social.config().get("page_id") or ""
    if not page:
        raise ErroEnvio("sem token do Meta Ads e sem a Página da HAIZEN conectada na aba Social")
    return instagram.endereco_publico(page, arquivo)


def preparar_pecas(conta_id: str, pecas: list[dict], aviso=None) -> list[dict]:
    """Garante image_hash/video_id em cada peça (envia só o que ainda não foi enviado)."""
    for p in pecas:
        arq = Path(str(p.get("arquivo") or ""))
        if p.get("image_hash") or p.get("video_id") or p.get("image_url"):
            continue
        if not arq.is_file():
            raise ErroEnvio(f"arquivo não encontrado: {arq.name}")
        ext = arq.suffix.lower()
        if aviso:
            aviso(f"Enviando {arq.name} para a conta de anúncios…")
        if ext in IMAGENS:
            try:
                p.update(subir_imagem(conta_id, arq))
            except ErroEnvio as e:
                if token_proprio():
                    raise
                try:
                    p["image_url"] = endereco_publico(arq)
                except Exception:  # noqa: BLE001
                    raise e from None
        elif ext in VIDEOS:
            p.update(subir_video(conta_id, arq, p.get("titulo") or ""))
        else:
            raise ErroEnvio(f"formato não aceito pelo Meta: {arq.name}")
    return pecas

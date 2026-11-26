"""Arquivos para campanhas de imagem e vídeo no Google Ads.

- Acha o arquivo (anexo do chat, pasta de cliente, entrega aprovada) — nada fora disso.
- Corta as imagens nos formatos que o Google pede (1,91:1, 1:1, 4:5) e o logo em 1:1.
- Sobe o vídeo para o YouTube como "não listado" (o Google Ads só usa vídeo do YouTube).
- Lê duração, resolução e tamanho de um vídeo.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from haizen.googleads import api

IMAGENS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
VIDEOS = (".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv")
FORMATOS = {"paisagem": (1200, 628, 600, 314), "quadrada": (1200, 1200, 300, 300), "retrato": (960, 1200, 480, 600)}


def _raizes() -> list[Path]:
    raizes = []
    try:
        from haizen.central import anexos
        raizes.append(anexos.pasta())
    except Exception:  # noqa: BLE001
        pass
    try:
        from haizen.central import claude_cerebro
        if claude_cerebro.raiz_clientes():
            raizes.append(Path(claude_cerebro.raiz_clientes()))
    except Exception:  # noqa: BLE001
        pass
    try:
        from haizen import store
        raizes.append(store.pasta_entregas())
    except Exception:  # noqa: BLE001
        pass
    try:
        from core.data_paths import data_dir
        raizes.append(Path(data_dir()))
    except Exception:  # noqa: BLE001
        pass
    return [r.resolve() for r in raizes if r]


def arquivo(ref: str) -> Path:
    """'anexo:ID', o id de um anexo, ou um caminho dentro das pastas permitidas."""
    ref = str(ref or "").strip().strip('"')
    m = re.fullmatch(r"(?:\[?anexo:)?([A-Za-z0-9_.-]+?)\]?", ref)
    if m and "/" not in ref and "\\" not in ref:
        try:
            from haizen.central import anexos
            p = anexos.caminho(m.group(1))
            if p.is_file():
                return p
        except Exception:  # noqa: BLE001
            pass
    p = Path(ref).expanduser()
    if p.is_file():
        p = p.resolve()
        if any(r == p or r in p.parents for r in _raizes()):
            return p
        raise ValueError(f"o arquivo precisa estar nos anexos, nas pastas dos clientes ou nas entregas: {ref}")
    raise ValueError(f"arquivo não encontrado: {ref}")


def conferir_imagem(ref: str) -> dict:
    from PIL import Image
    p = arquivo(ref)
    if p.suffix.lower() not in IMAGENS:
        raise ValueError(f"não é imagem: {p.name}")
    with Image.open(p) as im:
        return {"arquivo": str(p), "nome": p.name, "largura": im.width, "altura": im.height}


def _cortar(im, w: int, h: int):
    from PIL import Image
    alvo = w / h
    atual = im.width / im.height
    if atual > alvo:                                  # sobra largura
        nova = int(im.height * alvo)
        x = (im.width - nova) // 2
        im = im.crop((x, 0, x + nova, im.height))
    else:
        nova = int(im.width / alvo)
        y = (im.height - nova) // 2
        im = im.crop((0, y, im.width, y + nova))
    return im.resize((w, h), Image.LANCZOS) if im.width >= w else im


def cortes(ref: str) -> dict[str, bytes]:
    """{formato: JPEG} nos tamanhos do Google, a partir de uma imagem (corte central)."""
    from PIL import Image
    with Image.open(arquivo(ref)) as im:
        im = im.convert("RGB")
        out = {}
        for nome, (w, h, wmin, hmin) in FORMATOS.items():
            c = _cortar(im, w, h)
            if c.width < wmin or c.height < hmin:
                continue
            b = io.BytesIO()
            c.save(b, "JPEG", quality=88, optimize=True)
            out[nome] = b.getvalue()
        return out


def selecionar_cortes(refs: list[str], formatos: tuple[str, ...], maximo: int,
                      obrigatorios: tuple[str, ...] = ()) -> dict[str, list[bytes]]:
    """Imagens prontas para o Google sem passar do limite do anúncio.

    Uma peça que já está num formato do Google (ex.: 1200x628) entra só nesse formato, sem ser
    recortada nos outros; uma peça em outra proporção vira todos os cortes possíveis. Repetidas
    saem, e o total fica em `maximo`, alternando os formatos para não sobrar só um tipo."""
    from PIL import Image
    por_formato: dict[str, list[bytes]] = {f: [] for f in formatos}
    vistos: set[bytes] = set()
    reserva: dict[str, bytes] = {}
    for ref in refs:
        with Image.open(arquivo(ref)) as im:
            proporcao = im.width / im.height
        cs = {f: b for f, b in cortes(ref).items() if f in formatos}
        for f, b in cs.items():
            reserva.setdefault(f, b)
        casa_todos = [f for f in FORMATOS if abs(proporcao - FORMATOS[f][0] / FORMATOS[f][1]) <= 0.06 * FORMATOS[f][0] / FORMATOS[f][1]]
        casa = [f for f in casa_todos if f in formatos]
        if casa_todos and not casa:
            continue                 # peça feita para outro formato (ex.: retrato no Display): não recorta
        escolhidos = {f: cs[f] for f in casa if f in cs} or cs
        for f, b in escolhidos.items():
            if b not in vistos:
                vistos.add(b)
                por_formato[f].append(b)
    for f in obrigatorios:                      # formato exigido que nenhuma peça tinha: corta da primeira
        if not por_formato.get(f) and f in reserva:
            por_formato[f].append(reserva[f])
    final: dict[str, list[bytes]] = {f: [] for f in formatos}
    total, i = 0, 0
    while total < maximo and any(len(por_formato[f]) > i for f in formatos):
        for f in formatos:
            if total < maximo and len(por_formato[f]) > i:
                final[f].append(por_formato[f][i])
                total += 1
        i += 1
    return final


def logo_quadrado(ref: str) -> bytes:
    """Logo em 1:1 sem cortar: centraliza num quadrado com fundo branco (mín. 128 px)."""
    from PIL import Image
    with Image.open(arquivo(ref)) as im:
        im = im.convert("RGBA")
        lado = max(im.width, im.height, 512)
        fundo = Image.new("RGBA", (lado, lado), (255, 255, 255, 255))
        escala = (lado * 0.86) / max(im.width, im.height)
        im = im.resize((max(1, int(im.width * escala)), max(1, int(im.height * escala))), Image.LANCZOS)
        fundo.alpha_composite(im, ((lado - im.width) // 2, (lado - im.height) // 2))
        if lado > 1200:
            fundo = fundo.resize((1200, 1200), Image.LANCZOS)
        b = io.BytesIO()
        fundo.convert("RGB").save(b, "PNG", optimize=True)
        return b.getvalue()


def id_youtube(ref: str) -> str:
    ref = str(ref or "").strip()
    m = re.search(r"(?:youtu\.be/|v=|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})", ref)
    if m:
        return m.group(1)
    return ref if re.fullmatch(r"[A-Za-z0-9_-]{11}", ref) else ""


def info_video(ref: str) -> dict:
    """Duração, resolução, proporção, tamanho e o que o Google Ads aceita."""
    from haizen.producao.ferramentas import ffmpeg
    p = arquivo(ref)
    r = subprocess.run([ffmpeg(), "-nostdin", "-i", str(p)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", stdin=subprocess.DEVNULL, timeout=60)
    txt = r.stderr or ""
    dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    res = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", txt)
    fps = re.search(r"(\d+(?:\.\d+)?) fps", txt)
    codec = re.search(r"Video:\s*(\w+)", txt)
    segundos = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3)) if dur else None
    w, h = (int(res.group(1)), int(res.group(2))) if res else (None, None)
    rot = re.search(r"rotate\s*:\s*(-?\d+)", txt) or re.search(r"rotation of (-?\d+)", txt)
    if rot and abs(int(float(rot.group(1)))) in (90, 270) and w:
        w, h = h, w
    prop = None
    if w and h:
        for nome, val in (("16:9 (horizontal)", 16 / 9), ("9:16 (vertical, Shorts)", 9 / 16), ("1:1 (quadrado)", 1),
                          ("4:5 (vertical)", 0.8)):
            if abs(w / h - val) < 0.03:
                prop = nome
        prop = prop or f"{w}:{h}"
    avisos = []
    if segundos is not None and segundos < 10:
        avisos.append("tem menos de 10 s: o Google recomenda pelo menos 10 s para anúncio em vídeo")
    if segundos is not None and segundos > 180:
        avisos.append("passa de 3 min: para anúncio, o ideal é 15 a 60 s")
    if w and min(w, h) < 720:
        avisos.append("resolução abaixo de 720p: pode ficar com aparência ruim")
    return {"arquivo": p.name, "segundos": round(segundos, 1) if segundos is not None else None,
            "largura": w, "altura": h, "proporcao": prop, "fps": float(fps.group(1)) if fps else None,
            "codec": codec.group(1) if codec else None, "tamanho_mb": round(p.stat().st_size / 1_048_576, 1),
            "aceito_pelo_youtube": p.suffix.lower() in VIDEOS, "avisos": avisos}


def subir_youtube(ref: str, titulo: str, descricao: str = "") -> str:
    """Envia o vídeo ao YouTube como não listado e devolve o id (11 letras)."""
    p = arquivo(ref)
    if p.suffix.lower() not in VIDEOS:
        raise ValueError(f"não é vídeo: {p.name}")
    tamanho = p.stat().st_size
    meta = {"snippet": {"title": titulo[:95], "description": descricao[:4500], "categoryId": "22"},
            "status": {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False}}
    tipo = {".mov": "video/quicktime", ".mp4": "video/mp4", ".webm": "video/webm"}.get(p.suffix.lower(), "video/*")
    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=json.dumps(meta).encode(), method="POST",
        headers={"Authorization": f"Bearer {api._token()}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": tipo, "X-Upload-Content-Length": str(tamanho)})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            destino = r.headers.get("Location")
    except urllib.error.HTTPError as e:
        raise api.ErroGoogleAds(_erro_youtube(e)) from None
    if not destino:
        raise api.ErroGoogleAds("o YouTube não abriu o envio")
    with open(p, "rb") as f:
        put = urllib.request.Request(destino, data=f.read(), method="PUT",
                                     headers={"Content-Type": tipo, "Content-Length": str(tamanho)})
    try:
        with urllib.request.urlopen(put, timeout=3600) as r:
            vid = json.loads(r.read() or b"{}").get("id", "")
    except urllib.error.HTTPError as e:
        raise api.ErroGoogleAds(_erro_youtube(e)) from None
    if not vid:
        raise api.ErroGoogleAds("o YouTube não devolveu o id do vídeo")
    return vid


def _erro_youtube(e) -> str:
    try:
        corpo = json.loads(e.read() or b"{}")
    except Exception:  # noqa: BLE001
        corpo = {}
    msg = ((corpo.get("error") or {}).get("message") or f"HTTP {e.code}")
    motivo = json.dumps(corpo)
    if "insufficient" in motivo.lower() or "scope" in motivo.lower():
        return ("falta a permissão de enviar ao YouTube: na tela Google Ads, Configurar → Desconectar e conecte de novo "
                "(o Google vai pedir a permissão do YouTube)")
    if "has not been used" in motivo or "disabled" in motivo.lower():
        return "ative a YouTube Data API v3 no mesmo projeto do Google Cloud"
    if "youtubeSignupRequired" in motivo or "channel" in msg.lower():
        return "a conta Google conectada não tem canal no YouTube: crie um canal (pode ser o da agência) e tente de novo"
    if "quota" in motivo.lower():
        return "a cota diária de envios ao YouTube acabou (cerca de 6 vídeos por dia): tente amanhã ou envie pelo YouTube"
    return f"o YouTube recusou o envio: {msg}"

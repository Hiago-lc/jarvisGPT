"""Arquivos que você envia ao Jarvis e aos projetos (fotos, vídeos, PDFs, logos).

Cada envio fica em %LOCALAPPDATA%\\JarvisGPT\\jarvis-claude\\anexos com um id
(o nome salvo). O Claude abre de lá; ao abrir um projeto, os arquivos são
copiados para a pasta do projeto, em "00 - Material enviado".
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

LIMITE = 300_000_000            # 300 MB por arquivo (vídeos curtos de celular)
TIPOS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
         ".webp": "image/webp", ".heic": "image/heic", ".svg": "image/svg+xml", ".pdf": "application/pdf",
         ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mp3": "audio/mpeg",
         ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".wav": "audio/wav", ".txt": "text/plain; charset=utf-8"}
IMAGENS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def pasta() -> Path:
    from core.data_paths import data_dir
    p = Path(data_dir()) / "jarvis-claude" / "anexos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _nome_seguro(nome: str) -> str:
    nome = Path(str(nome or "").replace("\\", "/")).name
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", nome)
    nome = " ".join(nome.split()).strip(" .")
    return nome[-120:] or "arquivo"


def salvar(nome: str, dados: bytes) -> dict:
    if not dados:
        raise ValueError("arquivo vazio")
    if len(dados) > LIMITE:
        raise ValueError("arquivo grande demais (máximo 300 MB)")
    original = _nome_seguro(nome)
    aid = f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}-{original}"
    (pasta() / aid).write_bytes(dados)
    return descrever(aid)


def caminho(aid: str) -> Path:
    """O arquivo de um id (ou de um caminho dentro da pasta de anexos). Nada fora dela."""
    raiz = pasta().resolve()
    bruto = str(aid or "").strip()
    p = Path(bruto) if Path(bruto).is_absolute() else raiz / _nome_seguro(bruto)
    p = p.resolve()
    if p.parent != raiz or not p.is_file():
        raise KeyError(f"anexo não encontrado: {Path(bruto).name}")
    return p


def nome_original(aid: str) -> str:
    m = re.match(r"\d{8}-\d{6}-\d{3}-(.*)", Path(aid).name)
    return m.group(1) if m else Path(aid).name


def descrever(aid: str) -> dict:
    p = caminho(aid)
    return {"id": p.name, "nome": nome_original(p.name), "tamanho": p.stat().st_size,
            "imagem": p.suffix.lower() in IMAGENS, "caminho": str(p)}


def varios(ids) -> list[dict]:
    out = []
    for aid in ids or []:
        d = descrever(str(aid))
        if d["id"] not in {x["id"] for x in out}:
            out.append(d)
    return out[:20]


def tipo(p: Path) -> str:
    return TIPOS.get(p.suffix.lower(), "application/octet-stream")


def copiar_para(ids, destino: Path) -> list[Path]:
    """Copia os anexos para `destino` com o nome original (sem sobrescrever)."""
    destino.mkdir(parents=True, exist_ok=True)
    feitos = []
    for d in varios(ids):
        alvo = destino / d["nome"]
        if alvo.is_file() and alvo.stat().st_size == d["tamanho"]:
            continue                                     # já copiado antes
        n = 2
        while alvo.exists():
            alvo = destino / f"{Path(d['nome']).stem} ({n}){Path(d['nome']).suffix}"
            n += 1
        shutil.copy2(d["caminho"], alvo)
        feitos.append(alvo)
    return feitos


def texto_para_o_claude(lista: list[dict]) -> str:
    linhas = [f"- {d['nome']}: {d['caminho']}" for d in lista]
    return ("\n\n[Arquivos que o usuário enviou junto com esta mensagem. Abra com a ferramenta Read "
            "(imagens e PDFs você vê). Para usar num projeto, passe estes caminhos em `anexos` "
            "do projeto_criar ou do trabalho_refazer.]\n" + "\n".join(linhas))

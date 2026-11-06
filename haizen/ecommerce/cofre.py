"""Os acessos de cada loja (tokens, chaves), criptografados pela conta do Windows.

Ficam só neste PC, fora do banco e fora do backup. Nunca vão para agentes,
listagens ou para o Claude.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from haizen import segredo

_TRAVA = threading.Lock()


def _arq() -> Path:
    from core.data_paths import data_dir
    return Path(data_dir()) / "ecommerce_acessos.json"


def _tudo() -> dict:
    try:
        return json.loads(_arq().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ler(loja_id: str) -> dict:
    guardado = _tudo().get(str(loja_id))
    if not guardado:
        return {}
    try:
        return json.loads(segredo.abrir(guardado))
    except (OSError, ValueError):
        return {}


def gravar(loja_id: str, acessos: dict) -> None:
    with _TRAVA:
        t = _tudo()
        t[str(loja_id)] = segredo.fechar(json.dumps(acessos))
        _arq().parent.mkdir(parents=True, exist_ok=True)
        _arq().write_text(json.dumps(t, indent=1), encoding="utf-8")


def apagar(loja_id: str) -> None:
    with _TRAVA:
        t = _tudo()
        t.pop(str(loja_id), None)
        _arq().write_text(json.dumps(t, indent=1), encoding="utf-8")

"""Guarda segredos (tokens) criptografados.

No Windows, pela conta do Windows (DPAPI): só o seu usuário, neste PC, consegue abrir; copiado
para outro lugar o arquivo não serve para nada. No servidor (Linux), com uma chave guardada num
arquivo que só o serviço do Jarvis lê (HAIZEN_CHAVE_ARQUIVO, padrão /etc/jarvis/chave). Sem
nenhum dos dois (testes), o texto passa sem mudança, marcado como tal.
"""
from __future__ import annotations

import base64
import ctypes
import os
from pathlib import Path

_PREFIXO = "dpapi:"
_CHAVE = "fernet:"
_PURO = "plain:"


def _dpapi(dados: bytes, proteger: bool) -> bytes:
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(dados, len(dados))
    entrada = BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    saida = BLOB()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if proteger else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(entrada), None, None, None, None, 0x01, ctypes.byref(saida))   # UI_FORBIDDEN
    if not ok:
        raise OSError("o Windows não conseguiu abrir o segredo (outro usuário ou outro PC?)")
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        kernel32.LocalFree(saida.pbData)


def _arquivo_chave() -> Path | None:
    p = os.environ.get("HAIZEN_CHAVE_ARQUIVO") or ("/etc/jarvis/chave" if os.name != "nt" else "")
    return Path(p) if p and Path(p).is_file() else None


def _fernet():
    from cryptography.fernet import Fernet
    arq = _arquivo_chave()
    if arq is None:
        raise OSError("sem a chave do servidor (HAIZEN_CHAVE_ARQUIVO)")
    return Fernet(arq.read_bytes().strip())


def fechar(texto: str) -> str:
    if os.name == "nt":
        return _PREFIXO + base64.b64encode(_dpapi(texto.encode("utf-8"), True)).decode("ascii")
    if _arquivo_chave() is not None:
        return _CHAVE + _fernet().encrypt(texto.encode("utf-8")).decode("ascii")
    return _PURO + texto


def abrir(guardado: str) -> str:
    guardado = guardado or ""
    if guardado.startswith(_PREFIXO):
        return _dpapi(base64.b64decode(guardado[len(_PREFIXO):]), False).decode("utf-8")
    if guardado.startswith(_CHAVE):
        return _fernet().decrypt(guardado[len(_CHAVE):].encode("ascii")).decode("utf-8")
    if guardado.startswith(_PURO):
        return guardado[len(_PURO):]
    return guardado                     # formato antigo (texto puro): ainda abre, e é regravado fechado


def fechado(guardado: str) -> bool:
    g = guardado or ""
    if g.startswith((_PREFIXO, _CHAVE)):
        return True
    return os.name != "nt" and _arquivo_chave() is None and g.startswith(_PURO)

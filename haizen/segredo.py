"""Guarda segredos (tokens) criptografados pela conta do Windows (DPAPI).

Só o seu usuário, neste PC, consegue abrir: se o arquivo for copiado para outro
lugar (backup, pendrive, nuvem) ele não serve para nada. Fora do Windows (testes)
o texto passa sem mudança, marcado como tal.
"""
from __future__ import annotations

import base64
import ctypes
import os

_PREFIXO = "dpapi:"
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


def fechar(texto: str) -> str:
    if os.name == "nt":
        return _PREFIXO + base64.b64encode(_dpapi(texto.encode("utf-8"), True)).decode("ascii")
    return _PURO + texto


def abrir(guardado: str) -> str:
    guardado = guardado or ""
    if guardado.startswith(_PREFIXO):
        return _dpapi(base64.b64decode(guardado[len(_PREFIXO):]), False).decode("utf-8")
    if guardado.startswith(_PURO):
        return guardado[len(_PURO):]
    return guardado                     # formato antigo (texto puro): ainda abre, e é regravado fechado


def fechado(guardado: str) -> bool:
    return (guardado or "").startswith(_PREFIXO) or (os.name != "nt" and (guardado or "").startswith(_PURO))

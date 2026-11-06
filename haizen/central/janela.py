"""Ponte entre a interface da central e a janela nativa do Jarvis.

Quando a central roda dentro do Jarvis (start_local.py), a interface não tem
um assistente próprio: a tela "Jarvis" mostra e comanda o Jarvis da janela,
que é quem ouve, fala e controla o PC. A janela se registra aqui ao abrir; sem
ela (central aberta sozinha, pelo jarvis_web.py), as rotas /api/janela somem e
a interface usa o assistente da web, como antes.

A ponte só repassa: quem decide o que fazer com uma mensagem é o mesmo cérebro
da voz, e os ajustes abrem os painéis nativos da janela.
"""
from __future__ import annotations

import threading

_ponte = None
_lock = threading.Lock()

# Painéis nativos que a interface pode abrir.
AJUSTES = ("audio", "memoria", "plugins", "plugins_ajustes", "motor", "personalizar",
           "remoto", "classico")


def registrar(ponte) -> None:
    global _ponte
    with _lock:
        _ponte = ponte


def ponte():
    return _ponte


def ativa() -> bool:
    return _ponte is not None

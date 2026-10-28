"""Processa a fila de trabalhos em segundo plano, um por vez.

Um por vez de propósito: o modelo local ocupa a placa de vídeo inteira, e o
Claude Code consome o limite da assinatura. Dois ao mesmo tempo só fariam os
dois andarem mais devagar.
"""
from __future__ import annotations

import contextlib
import sys
import threading
from typing import Callable, Optional

from . import executor, store

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_avisar: Callable[[str], None] = lambda msg: None

# Ligado pelo servidor MCP, cuja saída padrão é o canal com o Claude.
SAIDA_PARA_STDERR = False


def _rodar() -> None:
    global _thread
    try:
        while True:
            t = store.pegar_proximo()
            if t is None:
                # Última olhada com a trava: um trabalho criado agora mesmo ou
                # é pego aqui, ou encontra _thread vazio e inicia outro worker.
                with _lock:
                    t = store.pegar_proximo()
                    if t is None:
                        _thread = None
                        return
            try:
                desvio = (contextlib.redirect_stdout(sys.stderr) if SAIDA_PARA_STDERR
                          else contextlib.nullcontext())
                with desvio:
                    arq = executor.executar(t)
                if t.get("projeto_id"):
                    from . import servicos
                    servicos.apos_entrega(t)
                    feito = store.trabalho(t["id"]) or {}
                    if feito.get("status") == "aguardando_aprovacao":
                        _avisar(f"Etapa \"{t.get('titulo') or t['agente']}\" do projeto {t['projeto_id']} pronta para sua aprovação.")
                else:
                    _avisar(f"Trabalho {t['id']} ({t['agente']}) pronto para aprovação: {arq.name}")
            except Exception as e:
                store.atualizar(t["id"], status="erro", erro=f"{type(e).__name__}: {e}"[:500])
                _avisar(f"Trabalho {t['id']} ({t['agente']}) falhou: {e}")
    except Exception:
        with _lock:
            _thread = None
        raise


def iniciar(avisar: Callable[[str], None] | None = None) -> bool:
    """Garante que há alguém processando a fila. Devolve True se começou agora."""
    global _thread, _avisar
    if avisar:
        _avisar = avisar
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        _thread = threading.Thread(target=_rodar, name="haizen-worker", daemon=True)
        _thread.start()
        return True


def ocupado() -> bool:
    return _thread is not None and _thread.is_alive()

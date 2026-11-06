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


def _notificar(titulo: str, texto: str, tipo: str, t: dict) -> None:
    try:
        from . import notificar
        notificar.avisar(titulo, texto, tipo, f"#/agentes/{t['id']}")
    except Exception as e:  # noqa: BLE001 - o aviso nunca trava a fila
        print(f"[HAIZEN] aviso não saiu: {e}", file=sys.stderr)


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
                if arq is None:                   # o agente parou para perguntar
                    _avisar(f"{t.get('titulo') or t['agente']} tem uma pergunta para você.")
                    _notificar("Um agente tem uma pergunta", f"{t.get('titulo') or t['agente']}: "
                               f"{(store.trabalho(t['id']) or {}).get('pergunta', '')[:160]}", "pergunta", t)
                    continue
                if t.get("projeto_id"):
                    from . import servicos
                    servicos.apos_entrega(t)
                    feito = store.trabalho(t["id"]) or {}
                    if feito.get("status") == "aguardando_aprovacao":
                        _avisar(f"Etapa \"{t.get('titulo') or t['agente']}\" do projeto {t['projeto_id']} pronta para sua aprovação.")
                        _notificar("Pronto para aprovar", t.get("titulo") or t["agente"], "aprovacao", t)
                else:
                    _avisar(f"Trabalho {t['id']} ({t['agente']}) pronto para aprovação: {arq.name}")
                    _notificar("Pronto para aprovar", t.get("titulo") or t["agente"], "aprovacao", t)
            except Exception as e:
                from . import uso
                if uso.e_limite(str(e)):
                    # Limite do Claude: os próximos falhariam igual. Para a fila e
                    # volta sozinho quando o limite liberar.
                    quando = uso.volta_em(str(e))
                    store.atualizar(t["id"], status="erro",
                                    erro=f"{LIMITE_MARCA} volta sozinho às {_hora(quando)}. ({e})"[:500])
                    _avisar(f"O Claude chegou ao limite. A fila volta sozinha às {_hora(quando)}.")
                    agendar_retomada(quando)
                    with _lock:
                        _thread = None
                    return
                store.atualizar(t["id"], status="erro", erro=f"{type(e).__name__}: {e}"[:500])
                _avisar(f"Trabalho {t['id']} ({t['agente']}) falhou: {e}")
                _notificar("Um trabalho travou", f"{t.get('titulo') or t['agente']}: {e}"[:200], "erro", t)
    except Exception:
        with _lock:
            _thread = None
        raise


LIMITE_MARCA = "Limite do Claude:"
_retomada: dict = {"timer": None, "em": 0.0}


def _hora(ts: float) -> str:
    import time as _t
    return _t.strftime("%H:%M", _t.localtime(ts))


def retomar_apos_limite() -> int:
    """Os trabalhos parados pelo limite voltam para a fila e ela anda de novo."""
    from . import servicos
    n = 0
    for t in store.listar_trabalhos("erro", 200):
        if str(t.get("erro") or "").startswith(LIMITE_MARCA):
            with contextlib.suppress(Exception):
                servicos.tentar_de_novo(t["id"])
                n += 1
    _retomada.update(timer=None, em=0.0)
    if n or store.listar_trabalhos("na_fila", 1):
        iniciar()
    return n


def agendar_retomada(quando: float) -> None:
    import time as _t
    if _retomada["timer"] is not None:
        _retomada["timer"].cancel()
    tm = threading.Timer(max(1.0, quando - _t.time()), retomar_apos_limite)
    tm.daemon = True
    tm.start()
    _retomada.update(timer=tm, em=quando)


def pausado_ate() -> float:
    import time as _t
    return _retomada["em"] if _retomada["em"] > _t.time() else 0.0


def iniciar(avisar: Callable[[str], None] | None = None) -> bool:
    """Garante que há alguém processando a fila. Devolve True se começou agora."""
    global _thread, _avisar
    if avisar:
        _avisar = avisar
    if pausado_ate():                     # limite do Claude: a retomada agendada liga a fila
        return False
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        _thread = threading.Thread(target=_rodar, name="haizen-worker", daemon=True)
        _thread.start()
        return True


def ocupado() -> bool:
    return _thread is not None and _thread.is_alive()

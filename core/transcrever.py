"""Transcrição de arquivos de áudio (mensagens de voz do WhatsApp) com o Whisper local.

Reaproveita o modelo que a voz do Jarvis já carregou; se ele não estiver
carregado (central aberta sem a janela), carrega um igual, uma vez só.
Nada sai do computador.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

_lock = threading.Lock()
_proprio = None


def _modelo():
    global _proprio
    try:
        from providers import stt_whisper
        voz = stt_whisper.ATUAL
    except Exception:  # noqa: BLE001
        voz = None
    if voz is not None and getattr(voz, "_model", None) is not None:
        return voz._model
    with _lock:
        if _proprio is None:
            from faster_whisper import WhisperModel
            nome = (os.environ.get("JARVIS_WHISPER_AUDIOS") or (voz.model_name if voz else "") or "base").strip()
            threads = max(1, min(8, (os.cpu_count() or 4) // 2))
            _proprio = WhisperModel(nome, device="cpu", compute_type="int8", cpu_threads=threads)
        return _proprio


def transcrever(dados: bytes, sufixo: str = ".ogg") -> str:
    """O texto falado no áudio (vazio se não houver fala)."""
    if not dados:
        return ""
    try:
        modelo = _modelo()
    except ImportError:
        raise RuntimeError("o reconhecimento de voz (faster-whisper) não está instalado") from None
    fd, caminho = tempfile.mkstemp(suffix=sufixo)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dados)
        with _lock:
            segmentos, _ = modelo.transcribe(caminho, language="pt", beam_size=1, vad_filter=True,
                                             condition_on_previous_text=False)
            texto = " ".join(s.text.strip() for s in segmentos).strip()
    finally:
        try:
            os.unlink(caminho)
        except OSError:
            pass
    try:
        from providers.stt_whisper import sem_alucinacao
        return sem_alucinacao(texto)
    except Exception:  # noqa: BLE001
        return texto


# ── memória das transcrições (por id da mensagem) ───────────────────────────
def _arquivo() -> Path:
    from core.data_paths import data_dir
    return data_dir() / "whatsapp_transcricoes.json"


def guardadas() -> dict:
    try:
        return json.loads(_arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar(msg_id: str, texto: str) -> None:
    with _lock:
        todas = guardadas()
        todas[msg_id] = texto
        if len(todas) > 2000:                       # guarda só as mais recentes
            todas = dict(list(todas.items())[-1500:])
        tmp = _arquivo().with_suffix(".tmp")
        tmp.write_text(json.dumps(todas, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _arquivo())


def transcrever_mensagem(contato: str, msg_id: str) -> str:
    """Baixa a mensagem de voz pelo WhatsApp Web e transcreve (uma vez só)."""
    feita = guardadas().get(msg_id)
    if feita is not None:
        return feita
    from core import whatsapp_web
    ok, code, r = whatsapp_web.run_op({"op": "audio", "recipient": contato, "id": msg_id}, timeout=75)
    if not ok:
        raise ValueError(r)
    texto = transcrever(r["audio"], ".ogg") or "(áudio sem fala reconhecível)"
    guardar(msg_id, texto)
    return texto


def com_transcricoes(msgs: list[dict]) -> list[dict]:
    """As mensagens com o texto das vozes já transcritas."""
    feitas = guardadas()
    out = []
    for m in msgs:
        if m.get("tipo") == "audio" and m.get("id") in feitas:
            m = {**m, "transcricao": feitas[m["id"]], "texto": f"[áudio] {feitas[m['id']]}"}
        out.append(m)
    return out

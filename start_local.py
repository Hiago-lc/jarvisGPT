"""Inicia o JARVIS sem API de créditos.

Dois perfis:

  local    (padrão) Tudo no seu computador: Whisper ouve, Ollama pensa, Piper
           fala. Nenhum dado sai da máquina, nenhum custo por uso. A qualidade
           depende do hardware.

  hibrido  O raciocínio e a transcrição vão para o plano GRATUITO do Groq
           (sem cartão, com limite diário de pedidos); a voz continua local.
           Bem mais inteligente e rápido em hardware modesto. A chave fica só
           na variável GROQ_API_KEY, nunca no disco.

Em nenhum dos dois o Gemini é chamado, mesmo que uma chave antiga continue
salva nas configurações.

Uso:
    python start_local.py                    # perfil local
    python start_local.py --perfil hibrido   # Groq gratuito + voz local
    python start_local.py --verificar        # só confere a instalação

Variáveis opcionais:
    JARVIS_LOCAL_MODEL   modelo do Ollama (padrão: qwen3:4b-instruct-2507-q4_K_M)
    JARVIS_GROQ_MODEL    modelo do Groq   (padrão: openai/gpt-oss-120b)
    JARVIS_PIPER_VOICE   voz Piper        (padrão: pt_BR-faber-medium)
    JARVIS_WHISPER_MODEL modelo Whisper   (padrão: small)
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import sys
from importlib.util import find_spec

OLLAMA_URL = "http://127.0.0.1:11434"
GROQ_URL = "https://api.groq.com/openai/v1"

# Escolhido para uma GPU de 4 GB (ex.: RX 580) com 16 GB de RAM: cabe inteiro
# na placa via Vulkan, chama ferramentas de forma confiável e é a variante
# "instruct", que responde direto em vez de gastar segundos "pensando" antes
# da primeira palavra.
DEFAULT_LOCAL_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_VOICE = "pt_BR-faber-medium"
DEFAULT_WHISPER = "small"

# Um modelo de 4B se perde com dezenas de ferramentas no prompt, e o contexto
# de uma GPU de 4 GB é curto. Menos ferramentas e um histórico menor cabem com
# folga; o painel permite mudar depois.
LOCAL_TOOL_BUDGET = {"max_tools": "10", "max_tool_chars": "8000",
                     "history_chars": "8000"}

# O Ollama abre modelos com 4096 tokens de contexto por padrão, e só as
# instruções e ferramentas do Jarvis passam de 7 mil. A API compatível com a
# OpenAI não aceita mudar isso por pedido, então criamos um modelo derivado com
# o contexto já gravado nele. 12 mil tokens = instruções + ferramentas +
# histórico + resposta, e ainda cabe quase todo numa placa de 4 GB.
DEFAULT_CONTEXT = 12288
DERIVED_PREFIX = "jarvis-"

PERFIS = ("local", "hibrido")


# ─────────────────────────────────────────────────────────────────────────────
#  Verificação
# ─────────────────────────────────────────────────────────────────────────────
def _ollama_models(base: str = OLLAMA_URL) -> list[str] | None:
    """Modelos instalados no Ollama, ou None se ele não estiver rodando."""
    try:
        import httpx
        r = httpx.get(base + "/api/tags", timeout=3.0)
        r.raise_for_status()
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return None


def verificar(perfil: str, modelo: str) -> list[str]:
    """Lista de problemas, em português, com o comando que resolve cada um.
    Lista vazia = pronto para iniciar."""
    problemas: list[str] = []

    if perfil == "local":
        modelos = _ollama_models()
        if modelos is None:
            problemas.append(
                "O Ollama não está respondendo em 127.0.0.1:11434. Instale em "
                "https://ollama.com e deixe-o aberto.")
        elif modelo not in modelos:
            instalados = ", ".join(modelos) or "nenhum"
            problemas.append(
                f"O modelo '{modelo}' não está no Ollama (instalados: {instalados}). "
                f"Rode: ollama pull {modelo}")
        if find_spec("faster_whisper") is None:
            problemas.append(
                "Falta o reconhecimento de voz local. Rode: "
                "python -m pip install faster-whisper")
    else:
        if not os.environ.get("GROQ_API_KEY", "").strip():
            problemas.append(
                "Defina GROQ_API_KEY no ambiente (chave gratuita em "
                "https://console.groq.com/keys).")

    if find_spec("piper") is None:
        problemas.append(
            "Falta a voz neural local (Piper); a voz do Windows será usada no "
            "lugar. Para a voz pt-BR: python -m pip install piper-tts")
    return problemas


def nome_derivado(base: str, contexto: int) -> str:
    """'qwen3:4b-instruct-2507-q4_K_M' -> 'jarvis-qwen3-4b-instruct-2507-q4_k_m-12k'."""
    limpo = "".join(c if c.isalnum() or c in "-_." else "-" for c in base.lower())
    return f"{DERIVED_PREFIX}{limpo}-{contexto // 1024}k"


def preparar_ollama(base: str, contexto: int = DEFAULT_CONTEXT,
                    url: str = OLLAMA_URL) -> str:
    """Garante um modelo com contexto suficiente e devolve o nome a usar.

    Cria (uma vez) um derivado de `base` com `num_ctx = contexto`. Se o Ollama
    for antigo demais para isso, avisa e devolve o próprio `base`, para que o
    Jarvis ainda inicie e o aviso diga como resolver.
    """
    if base.startswith(DERIVED_PREFIX):
        return base
    nome = nome_derivado(base, contexto)
    if nome in (_ollama_models(url) or []) or f"{nome}:latest" in (_ollama_models(url) or []):
        return nome
    try:
        import httpx
        r = httpx.post(url + "/api/create", timeout=120.0, json={
            "model": nome, "from": base,
            "parameters": {"num_ctx": int(contexto)}, "stream": False})
        r.raise_for_status()
        print(f"  • Criado '{nome}' ({contexto} tokens de contexto) a partir de '{base}'.")
        return nome
    except Exception as e:
        print(f"  • Não consegui criar o modelo com contexto maior ({type(e).__name__}). "
              "Atualize o Ollama ou rode: setx OLLAMA_CONTEXT_LENGTH 12288 "
              "e reinicie o Ollama.")
        return base


# ─────────────────────────────────────────────────────────────────────────────
#  Configuração
# ─────────────────────────────────────────────────────────────────────────────
def _env(name: str, default: str) -> str:
    """A variable that is set but empty counts as unset."""
    return os.environ.get(name, "").strip() or default


def modelo_padrao(perfil: str) -> str:
    if perfil == "local":
        return _env("JARVIS_LOCAL_MODEL", DEFAULT_LOCAL_MODEL)
    return _env("JARVIS_GROQ_MODEL", DEFAULT_GROQ_MODEL)


def _os_name() -> str:
    return {"Windows": "windows", "Darwin": "mac"}.get(platform.system(), "linux")


def montar_config(data: dict, perfil: str, modelo: str) -> dict:
    """Uma cópia de `data` com o motor local configurado. Nada é apagado: as
    outras configurações e provedores salvos continuam como estavam."""
    if perfil not in PERFIS:
        raise ValueError(f"perfil desconhecido: {perfil}")
    data = copy.deepcopy(data)
    providers = data.setdefault("providers", {})
    tts = "piper" if find_spec("piper") is not None else "system_tts"
    providers.update(mode="pipeline", sidecar="openai_compat", sidecar_first=True)
    providers["pipeline"] = {"stt": "whisper", "llm": "openai_compat", "tts": tts}
    creds = providers.setdefault("creds", {})

    llm = creds.setdefault("openai_compat", {})
    if perfil == "local":
        llm.update(base_url=OLLAMA_URL + "/v1", model=modelo, api_key="",
                   vision=False, **LOCAL_TOOL_BUDGET)
    else:
        llm.update(base_url=GROQ_URL, model=modelo, vision=False,
                   max_tools="0", max_tool_chars="0")
        llm.pop("api_key", None)          # a chave só existe em memória
        llm.pop("history_chars", None)    # o Groq tem contexto de sobra

    stt = creds.setdefault("whisper", {})
    if perfil == "local":
        stt.update(backend="local", base_url="", api_key="", device="cpu",
                   model=_env("JARVIS_WHISPER_MODEL", DEFAULT_WHISPER),
                   language="pt")
    else:
        stt.update(backend="api", base_url=GROQ_URL,
                   model="whisper-large-v3-turbo", language="pt")
        stt.pop("api_key", None)

    creds.setdefault("piper", {}).update(
        voice=_env("JARVIS_PIPER_VOICE", DEFAULT_VOICE),
        follow_language="0")
    creds.setdefault("system_tts", {})
    data.setdefault("os_system", _os_name())
    return data


def configure(perfil: str = "local", modelo: str = "") -> None:
    from memory import config_manager as cm

    modelo = modelo or modelo_padrao(perfil)
    chave = os.environ.get("GROQ_API_KEY", "").strip()
    if perfil == "hibrido" and not chave:
        raise SystemExit("Defina GROQ_API_KEY no ambiente antes de usar o perfil hibrido.")

    data = montar_config(cm.load_api_keys(), perfil, modelo)
    cm.ensure_config_dir()
    cm.CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Nenhuma chamada ao Gemini, nem como reserva.
    os.environ["JARVIS_NO_GEMINI"] = "1"

    if chave:
        original = cm.load_api_keys

        def runtime_config():
            current = original()
            block = current.setdefault("providers", {}).setdefault("creds", {})
            for pid in ("openai_compat", "whisper"):
                block.setdefault(pid, {})["api_key"] = chave
            return current

        cm.load_api_keys = runtime_config


def _args(argv=None):
    p = argparse.ArgumentParser(description="Inicia o JARVIS sem API de créditos.")
    p.add_argument("--perfil", choices=PERFIS, default="local")
    p.add_argument("--modelo", default="", help="sobrescreve o modelo do perfil")
    p.add_argument("--verificar", action="store_true",
                   help="só confere a instalação e sai")
    return p.parse_args(argv)


if __name__ == "__main__":
    a = _args()
    modelo = a.modelo or modelo_padrao(a.perfil)
    problemas = verificar(a.perfil, modelo)
    for p in problemas:
        print("  •", p)
    if a.verificar:
        print("Tudo pronto." if not problemas else "Resolva os itens acima.")
        sys.exit(0 if not problemas else 1)
    bloqueantes = [p for p in problemas if "Piper" not in p]
    if bloqueantes:
        sys.exit("Não foi possível iniciar. Resolva os itens acima.")
    if a.perfil == "local":
        contexto = int(_env("JARVIS_CONTEXT", str(DEFAULT_CONTEXT)))
        modelo = preparar_ollama(modelo, contexto)
    configure(a.perfil, modelo)
    from main import main
    main()

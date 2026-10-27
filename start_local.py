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
from pathlib import Path
import copy
import json
import os
import platform
import sys
import time
from importlib.util import find_spec

OLLAMA_URL = "http://127.0.0.1:11434"
GROQ_URL = "https://api.groq.com/openai/v1"
# A API do Gemini também fala o protocolo da OpenAI. No plano gratuito
# (projeto sem cobrança ativada) não há crédito: só um limite de pedidos.
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

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

# Quanto esperar pela primeira palavra do modelo local, em segundos. O padrão
# do provedor (60 s) é pouco para uma placa modesta: antes de responder, o
# modelo lê ~7 mil tokens de instruções, e na primeira vez ainda carrega o
# modelo na memória. Nas vezes seguintes o Ollama reaproveita essa leitura.
LOCAL_TIMEOUT = "180"

# O Ollama abre modelos com 4096 tokens de contexto por padrão, e só as
# instruções e ferramentas do Jarvis passam de 7 mil. A API compatível com a
# OpenAI não aceita mudar isso por pedido, então criamos um modelo derivado com
# o contexto já gravado nele. 12 mil tokens = instruções + ferramentas +
# histórico + resposta, e ainda cabe quase todo numa placa de 4 GB.
DEFAULT_CONTEXT = 12288
DERIVED_PREFIX = "jarvis-"

PERFIS = ("local", "hibrido", "gemini")
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"


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


def verificar_aguardando(perfil: str, modelo: str, segundos: float = 0,
                         passo: float = 5) -> list[str]:
    """Como verificar(), mas espera o Ollama subir (logo depois de ligar o PC
    ele ainda não está pronto)."""
    limite = time.monotonic() + segundos
    while True:
        problemas = verificar(perfil, modelo)
        if not any("Ollama" in p for p in problemas) or time.monotonic() >= limite:
            return problemas
        time.sleep(passo)


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
    elif perfil == "gemini":
        if not chave_gemini():
            problemas.append(
                "Falta a chave do Gemini. Crie uma gratuita em "
                "https://aistudio.google.com/apikey e salve com: setx GEMINI_API_KEY \"sua-chave\"")
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
    if perfil == "gemini":
        return _env("JARVIS_GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    return _env("JARVIS_GROQ_MODEL", DEFAULT_GROQ_MODEL)


def chave_gemini() -> str:
    """GEMINI_API_KEY do ambiente, ou a chave já salva pela tela inicial do Jarvis."""
    chave = os.environ.get("GEMINI_API_KEY", "").strip()
    if chave:
        return chave
    try:
        from memory import config_manager as cm
        return str(cm.load_api_keys().get("gemini_api_key") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


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
                   vision=False, timeout=_env("JARVIS_TIMEOUT", LOCAL_TIMEOUT),
                   **LOCAL_TOOL_BUDGET)
    else:
        llm.update(base_url=GROQ_URL if perfil == "hibrido" else GEMINI_URL,
                   model=modelo, vision=False, max_tools="0", max_tool_chars="0")
        llm.pop("api_key", None)          # a chave só existe em memória
        llm.pop("history_chars", None)    # na nuvem há contexto de sobra
        llm.pop("timeout", None)          # e a resposta vem em segundos

    stt = creds.setdefault("whisper", {})
    if perfil in ("local", "gemini"):
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
    chave, destinos = "", ()
    if perfil == "hibrido":
        chave, destinos = os.environ.get("GROQ_API_KEY", "").strip(), ("openai_compat", "whisper")
        if not chave:
            raise SystemExit("Defina GROQ_API_KEY no ambiente antes de usar o perfil hibrido.")
    elif perfil == "gemini":
        chave, destinos = chave_gemini(), ("openai_compat",)
        if not chave:
            raise SystemExit("Falta a chave do Gemini (GEMINI_API_KEY ou a salva no Jarvis).")

    data = montar_config(cm.load_api_keys(), perfil, modelo)
    cm.ensure_config_dir()
    # Gravação atômica: outro processo lendo ao mesmo tempo nunca vê o arquivo
    # pela metade. Foi isso que, com a web e a janela subindo juntas, fez a
    # janela achar a configuração vazia e cair no Gemini Live.
    from core.atomic_storage import write_json
    write_json(cm.CONFIG_FILE, data)

    # Nenhuma chamada ao Gemini, nem como reserva.
    os.environ["JARVIS_NO_GEMINI"] = "1"
    os.environ["JARVIS_PROVIDER_MODE"] = "pipeline"

    original = cm.load_api_keys
    vocabulario = vocabulario_whisper()

    def runtime_config():
        current = original()
        block = current.setdefault("providers", {})
        block["mode"] = "pipeline"           # mesmo se o arquivo for lido vazio
        creds = block.setdefault("creds", {})
        for pid in destinos:
            creds.setdefault(pid, {})["api_key"] = chave
        if vocabulario:
            creds.setdefault("whisper", {})["initial_prompt"] = vocabulario
        return current

    cm.load_api_keys = runtime_config


# Grafias que o Whisper pequeno erra no dia a dia. Os nomes dos clientes da
# central entram na hora (só em memória, nunca no arquivo de configuração).
VOCABULARIO = ("Jarvis, HAIZEN, WhatsApp, WhatsApp Business, Google Agenda, Google Chrome, "
               "Spotify, YouTube, Instagram, Canva, Photoshop, Illustrator, Premiere, "
               "Visual Studio Code, Explorador de Arquivos, Downloads, Documentos, "
               "receita, despesa, faturamento, tarefa, proposta, e-commerce, tráfego pago")


def vocabulario_whisper(limite: int = 60) -> str:
    nomes = []
    try:
        from haizen import store
        nomes = [c["nome"] for c in store.listar_clientes() if c.get("status", "Ativo") == "Ativo"][:limite]
    except Exception:  # noqa: BLE001 - sem central, só o vocabulário fixo
        pass
    return VOCABULARIO + (". Clientes: " + ", ".join(nomes) if nomes else "") + "."


# ── iniciar com o Windows (só a janela) ─────────────────────────────────────
NOME_ATALHO = "Jarvis HAIZEN.cmd"


def _pasta_inicializar() -> Path:
    return (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu"
            / "Programs" / "Startup")


def iniciar_com_windows(perfil: str, ligar: bool) -> str:
    if sys.platform != "win32":
        return "Início automático só está pronto para o Windows."
    atalho = _pasta_inicializar() / NOME_ATALHO
    if not ligar:
        atalho.unlink(missing_ok=True)
        return "O Jarvis não inicia mais sozinho com o Windows."
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.is_file() else Path(sys.executable)
    raiz = Path(__file__).resolve().parent
    atalho.write_text("\r\n".join([
        "@echo off", f'cd /d "{raiz}"',
        f'start "" "{exe}" "{raiz / "start_local.py"}" --perfil {perfil} --aguardar', ""]),
        encoding="utf-8")
    return ("Pronto: ao ligar o PC, abre o Jarvis (a janela com voz), com a central da HAIZEN "
            f"dentro dele. ({atalho})")


def aquecer_modelo(modelo: str, url: str = OLLAMA_URL) -> None:
    """Carrega o modelo na placa de vídeo em segundo plano, logo ao abrir.

    Sem isso, o primeiro "oi" pagava a carga do modelo (dezenas de segundos
    numa placa modesta) e parecia que o Jarvis não respondia. Um pedido vazio
    ao Ollama só carrega o modelo, e keep_alive=-1 o mantém carregado.
    """
    import threading
    import urllib.request

    def _carregar():
        corpo = json.dumps({"model": modelo, "prompt": "", "keep_alive": -1}).encode()
        req = urllib.request.Request(f"{url}/api/generate", data=corpo,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                r.read()
            print(f"[Ollama] {modelo} carregado e pronto.")
        except Exception as e:  # noqa: BLE001 - só adianta o trabalho; sem ele, carrega na 1ª fala
            print(f"[Ollama] não consegui pré-carregar {modelo}: {e}")

    threading.Thread(target=_carregar, daemon=True, name="aquecer-modelo").start()


def ligar_central() -> None:
    """A central (painel, financeiro, celular) roda dentro da janela, sem
    outro processo. Se outra cópia já ocupa a porta, usa aquela."""
    try:
        from haizen.central import servidor
        url = servidor.iniciar(abrir_navegador=False)
        print(f"[HAIZEN] Central em {url}")
    except Exception as e:  # noqa: BLE001 - sem central, o Jarvis funciona igual
        print(f"[HAIZEN] Central não iniciou: {e}")


def _args(argv=None):
    p = argparse.ArgumentParser(description="Inicia o JARVIS sem API de créditos.")
    p.add_argument("--perfil", choices=PERFIS, default="local")
    p.add_argument("--modelo", default="", help="sobrescreve o modelo do perfil")
    p.add_argument("--verificar", action="store_true",
                   help="só confere a instalação e sai")
    p.add_argument("--aguardar", action="store_true",
                   help="espera o Ollama subir (usado ao iniciar com o Windows)")
    p.add_argument("--iniciar-com-windows", action="store_true",
                   help="abre esta janela sozinha quando o PC liga")
    p.add_argument("--nao-iniciar-com-windows", action="store_true")
    p.add_argument("--sem-central", action="store_true",
                   help="não abre a central da HAIZEN junto")
    return p.parse_args(argv)


if __name__ == "__main__":
    if sys.stdout is None or sys.stderr is None:   # pythonw: sem janela de console
        _log = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "JarvisGPT" / "jarvis_janela.log"
        _log.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(_log, "a", encoding="utf-8", buffering=1)
    a = _args()
    if a.iniciar_com_windows or a.nao_iniciar_com_windows:
        print(iniciar_com_windows(a.perfil, a.iniciar_com_windows))
        sys.exit(0)
    modelo = a.modelo or modelo_padrao(a.perfil)
    problemas = verificar_aguardando(a.perfil, modelo, 180 if a.aguardar else 0)
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
    if a.perfil == "local":
        aquecer_modelo(modelo)
    if not a.sem_central:
        ligar_central()
    from main import main
    main()

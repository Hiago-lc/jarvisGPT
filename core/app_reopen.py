"""Registered application activation, without taskbar vision or a shell."""
import time


def reopen_registered(spoken, cancelled=lambda: False):
    # These are OS protocol registrations, not guessed shell commands.
    protocols = {'spotify': 'spotify:'}
    protocol = protocols.get(spoken.strip().casefold())
    if protocol is None or cancelled():
        return False
    try:
        import os
        import winreg
        from core.window_restore import foreground_matches
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, protocol[:-1]) as key:
            winreg.QueryValueEx(key, 'URL Protocol')
        if cancelled():
            return False
        os.startfile(protocol)
        deadline = time.monotonic() + 4
        while not cancelled() and time.monotonic() < deadline:
            if foreground_matches(spoken):
                return True
            time.sleep(.1)
    except (OSError, ImportError):
        pass
    return False


# ── Apps da Microsoft Store (WhatsApp, WhatsApp Business, Spotify da loja) ──
# Esses apps não têm executável no PATH, e quando estão na bandeja do sistema
# não há janela para trazer à frente. O próprio Windows sabe abri-los pelo
# AppID do menu Iniciar (Get-StartApps): "shell:AppsFolder\<AppID>" abre o app
# ou, se já estiver rodando, mostra a janela dele. Sem visão, sem clicar.
_START_APPS: tuple[float, list[dict]] | None = None


def _normalizar(texto):
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def start_apps():
    """[{'Name': ..., 'AppID': ...}] do menu Iniciar, guardado por 10 minutos."""
    global _START_APPS
    import json
    import subprocess
    if _START_APPS and time.monotonic() - _START_APPS[0] < 600:
        return _START_APPS[1]
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        dados = json.loads(r.stdout or "[]")
        apps = [dados] if isinstance(dados, dict) else list(dados or [])
    except Exception:
        apps = []
    _START_APPS = (time.monotonic(), apps)
    return apps


def escolher_start_app(spoken, apps):
    """O app do menu Iniciar que o usuário quis dizer, ou None se ambíguo."""
    alvo = _normalizar(spoken)
    if not alvo:
        return None
    nomes = [(a, _normalizar(a.get("Name", ""))) for a in apps if a.get("AppID")]
    exatos = [a for a, n in nomes if n == alvo]
    if exatos:
        return exatos[0]
    # "whatsapp" deve achar "WhatsApp", não "WhatsApp Business"; por isso o
    # nome mais curto que contém o pedido, e só se o pedido for uma palavra inteira.
    contem = [(a, n) for a, n in nomes if f" {alvo} " in f" {n} "]
    if not contem:
        return None
    return min(contem, key=lambda x: len(x[1]))[0]


def open_start_app(spoken, cancelled=lambda: False, esperar=6.0):
    """Abre (ou traz à frente) um app pelo menu Iniciar. True se a janela apareceu."""
    import subprocess
    app = escolher_start_app(spoken, start_apps())
    if app is None or cancelled():
        return False
    try:
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + app["AppID"]],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        return False
    from core.window_restore import foreground_matches
    nome = app.get("Name") or spoken
    limite = time.monotonic() + esperar
    while not cancelled() and time.monotonic() < limite:
        if foreground_matches(nome) or foreground_matches(spoken):
            return True
        time.sleep(0.15)
    return False

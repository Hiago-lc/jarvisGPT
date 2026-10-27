"""Jarvis web: o assistente e a central da HAIZEN no navegador, no PC e no celular.

Roda em segundo plano, sem a janela antiga (que fica opcional, em start_local.py).
O cérebro continua neste PC: modelo, voz, agentes, arquivos e controle do PC.

    py jarvis_web.py                       # modelo local, abre o navegador
    py jarvis_web.py --perfil hibrido      # Groq gratuito + voz local
    py jarvis_web.py --tailscale           # libera o acesso pelo celular (Tailscale)
    py jarvis_web.py --iniciar-com-windows # inicia sozinho quando você liga o PC
    py jarvis_web.py --nao-iniciar-com-windows

Pelo celular: instale o Tailscale no PC e no celular, entre com a mesma conta,
rode uma vez com --tailscale e abra o endereço https://....ts.net que aparecer.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import start_local  # noqa: E402

# Iniciado sem console (pythonw, início automático), o print não iria para
# lugar nenhum. Vai para um arquivo que dá para abrir se algo falhar.
if sys.stdout is None or sys.stderr is None:
    _log = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "JarvisGPT" / "jarvis_web.log"
    _log.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(_log, "a", encoding="utf-8", buffering=1)

PORTA = int(os.environ.get("HAIZEN_CENTRAL_PORTA", "8765"))
NOME_ATALHO = "Jarvis HAIZEN.cmd"


# ── Tailscale ───────────────────────────────────────────────────────────────
def _tailscale() -> str | None:
    achado = shutil.which("tailscale")
    if achado:
        return achado
    padrao = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
    return str(padrao) if padrao.is_file() else None


def endereco_tailscale(exe: str) -> str | None:
    try:
        r = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=10)
        nome = (json.loads(r.stdout or "{}").get("Self") or {}).get("DNSName", "").rstrip(".")
        return f"https://{nome}" if nome else None
    except Exception:  # noqa: BLE001
        return None


def ligar_tailscale() -> str:
    exe = _tailscale()
    if not exe:
        return ("Tailscale não encontrado. Instale em https://tailscale.com/download "
                "(no PC e no celular, mesma conta) e rode de novo com --tailscale.")
    # Publica a central SÓ dentro da sua rede Tailscale (serve, não funnel):
    # ninguém fora dos seus aparelhos consegue abrir.
    #
    # Na primeira vez o Tailscale imprime um link para ativar o "Serve" e
    # ESPERA você ativar. Por isso a saída vai direto para a tela (não é
    # capturada) e há tempo de sobra para abrir o link e clicar.
    print("Ligando o acesso pelo celular no Tailscale...")
    print("Se aparecer um link abaixo, abra no navegador, ative e volte aqui.")
    try:
        r = subprocess.run([exe, "serve", "--bg", str(PORTA)], timeout=300)
    except subprocess.TimeoutExpired:
        return ("O Tailscale não terminou em 5 minutos. Ative o Serve pelo link que ele "
                "mostrou e rode de novo com --tailscale.")
    if r.returncode != 0:
        return "O Tailscale recusou (veja a mensagem acima). O Jarvis continua funcionando no PC."
    url = endereco_tailscale(exe)
    return (f"Pelo celular (com o Tailscale ligado): {url}" if url
            else "Tailscale ligado. Veja o endereço .ts.net no app do Tailscale.")


# ── iniciar com o Windows ───────────────────────────────────────────────────
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
    atalho.write_text(
        "@echo off\r\n"
        f'cd /d "{RAIZ}"\r\n'
        f'start "" "{exe}" "{RAIZ / "jarvis_web.py"}" --perfil {perfil} --sem-navegador\r\n',
        encoding="utf-8")
    return f"Pronto: o Jarvis vai iniciar sozinho quando você ligar o PC ({atalho})."


# ── principal ───────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jarvis web: assistente e central da HAIZEN.")
    ap.add_argument("--perfil", choices=start_local.PERFIS, default="local")
    ap.add_argument("--modelo", default="")
    ap.add_argument("--sem-navegador", action="store_true")
    ap.add_argument("--tailscale", action="store_true", help="liberar o acesso pelo celular")
    ap.add_argument("--iniciar-com-windows", action="store_true")
    ap.add_argument("--nao-iniciar-com-windows", action="store_true")
    a = ap.parse_args(argv)

    if a.iniciar_com_windows or a.nao_iniciar_com_windows:
        print(iniciar_com_windows(a.perfil, a.iniciar_com_windows))
        return 0

    modelo = a.modelo or start_local.modelo_padrao(a.perfil)
    problemas = [p for p in start_local.verificar(a.perfil, modelo) if "Piper" not in p]
    for p in problemas:
        print("  •", p)
    if problemas:
        print("Resolva os itens acima e rode de novo.")
        return 1
    if a.perfil == "local":
        modelo = start_local.preparar_ollama(
            modelo, int(start_local._env("JARVIS_CONTEXT", str(start_local.DEFAULT_CONTEXT))))
    start_local.configure(a.perfil, modelo)

    from haizen import worker
    from haizen.central import cerebro, servidor
    from haizen import store

    cerebro.ligar_confirmacoes()
    url = servidor.iniciar(abrir_navegador=False)
    print(f"Jarvis web em {url}")
    if a.tailscale:
        print(ligar_tailscale())
    else:
        exe = _tailscale()
        remoto = exe and endereco_tailscale(exe)
        if remoto:
            print(f"Se já liberou o celular antes: {remoto}")

    # Trabalhos dos agentes que ficaram pela metade voltam a andar.
    if store.recuperar_interrompidos() or store.listar_trabalhos("na_fila", 1):
        worker.iniciar(lambda m: print(f"[HAIZEN] {m}"))

    print("Carregando o ouvido e a voz (só na primeira vez demora)...")
    threading.Thread(target=cerebro.aquecer, daemon=True, name="aquecer").start()
    if not a.sem_navegador:
        import webbrowser
        webbrowser.open(url + "#/jarvis")
    print("Pronto. Ctrl+C para fechar.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        servidor.parar()
    return 0


if __name__ == "__main__":
    sys.exit(main())

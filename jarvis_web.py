"""Jarvis web: o assistente e a central da HAIZEN no navegador, no PC e no celular.

Roda em segundo plano, sem a janela antiga (que fica opcional, em start_local.py).
Quem responde e age é o Claude (Claude Code com a sua assinatura), usando as
ferramentas do Jarvis: financeiro, agenda, WhatsApp, agentes e o PC. Sem o
Claude Code (ou com JARVIS_CEREBRO=local), volta o modelo local.

    py jarvis_web.py --abrir               # só abre a janela (se já estiver rodando)

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


def iniciar_com_windows(perfil: str, ligar: bool, com_janela: bool = False) -> str:
    if sys.platform != "win32":
        return "Início automático só está pronto para o Windows."
    atalho = _pasta_inicializar() / NOME_ATALHO
    if not ligar:
        atalho.unlink(missing_ok=True)
        return "O Jarvis não inicia mais sozinho com o Windows."
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.is_file() else Path(sys.executable)
    linhas = ["@echo off", f'cd /d "{RAIZ}"',
              f'start "" "{exe}" "{RAIZ / "jarvis_web.py"}" --perfil {perfil} --sem-navegador']
    if com_janela:
        # A janela de voz sobe um pouco depois, para não disputar o Ollama.
        linhas += ["timeout /t 20 /nobreak >nul",
                   f'start "" "{exe}" "{RAIZ / "start_local.py"}" --perfil {perfil} --aguardar']
    atalho.write_text("\r\n".join(linhas) + "\r\n", encoding="utf-8")
    extra = " A janela de voz abre junto." if com_janela else ""
    return f"Pronto: o Jarvis vai iniciar sozinho quando você ligar o PC.{extra} ({atalho})"


# ── a janela ────────────────────────────────────────────────────────────────
def _navegador_app() -> str | None:
    """Edge ou Chrome, para abrir a central como um aplicativo (sem abas e barra)."""
    if sys.platform != "win32":
        return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("microsoft-edge")
    pastas = [os.environ.get(k, "") for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
        for base in pastas:
            if base and (Path(base) / rel).is_file():
                return str(Path(base) / rel)
    return shutil.which("msedge") or shutil.which("chrome")


def abrir_janela(url: str) -> None:
    """A central numa janela própria, com o microfone liberado (127.0.0.1 é local)."""
    exe = _navegador_app()
    if exe:
        try:
            perfil = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "JarvisGPT" / "janela-web"
            subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={perfil}", "--window-size=1280,860",
                              "--no-first-run", "--no-default-browser-check"])
            return
        except OSError:
            pass
    import webbrowser
    webbrowser.open(url)


def _ja_aberto() -> bool:
    import urllib.request
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORTA}/api/sistema/versao", headers={"X-Central": "1"})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _claude_cerebro() -> bool:
    try:
        from haizen.central import claude_cerebro
        return claude_cerebro.ativo()
    except Exception as e:  # noqa: BLE001
        print(f"Claude Code indisponível ({e}); uso o modelo local.")
        return False


# ── principal ───────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jarvis web: assistente e central da HAIZEN.")
    ap.add_argument("--perfil", choices=start_local.PERFIS, default="local")
    ap.add_argument("--modelo", default="")
    ap.add_argument("--sem-navegador", action="store_true")
    ap.add_argument("--abrir", action="store_true", help="só abrir a janela do Jarvis já rodando")
    ap.add_argument("--tailscale", action="store_true", help="liberar o acesso pelo celular")
    ap.add_argument("--iniciar-com-windows", action="store_true")
    ap.add_argument("--nao-iniciar-com-windows", action="store_true")
    ap.add_argument("--com-janela", action="store_true",
                    help="com --iniciar-com-windows: abre também a janela de voz")
    a = ap.parse_args(argv)
    try:
        # O atalho da área de trabalho (Jarvis.vbs) abre com este mesmo Python.
        _pyw = Path(sys.executable).with_name("pythonw.exe")
        (RAIZ / "config" / "python_local.txt").write_text(
            str(_pyw if _pyw.is_file() else Path(sys.executable)), encoding="utf-8")
    except OSError:
        pass

    if a.iniciar_com_windows or a.nao_iniciar_com_windows:
        print(iniciar_com_windows(a.perfil, a.iniciar_com_windows, a.com_janela))
        return 0

    url_jarvis = f"http://127.0.0.1:{PORTA}/#/jarvis"
    if a.abrir and _ja_aberto():
        abrir_janela(url_jarvis)
        print("O Jarvis já está rodando; abri a janela.")
        return 0

    modelo = a.modelo or start_local.modelo_padrao(a.perfil)
    claude = _claude_cerebro()
    # Com o Claude no comando, o modelo local é só reserva: sem Ollama, segue.
    espera = 0 if claude else (180 if a.sem_navegador else 0)
    problemas = [p for p in start_local.verificar_aguardando(a.perfil, modelo, espera)
                 if "Piper" not in p]
    for p in problemas:
        print("  •", p)
    if problemas and not claude:
        print("Resolva os itens acima e rode de novo.")
        return 1
    if claude:
        print("Cérebro: Claude (Claude Code da sua assinatura).")
    if a.perfil == "local" and not problemas and not claude:
        modelo = start_local.preparar_ollama(
            modelo, int(start_local._env("JARVIS_CONTEXT", str(start_local.DEFAULT_CONTEXT))))
        start_local.liberar_outros(modelo)
    start_local.configure(a.perfil, modelo)

    from haizen import worker
    from haizen.central import cerebro, servidor
    from haizen import store

    cerebro.ligar_confirmacoes()
    servidor.COMANDO_REINICIO = [sys.executable, str(RAIZ / "jarvis_web.py"),
                                 *[x for x in (argv if argv is not None else sys.argv[1:])
                                   if x != "--tailscale"],
                                 *([] if a.sem_navegador else ["--sem-navegador"])]
    try:
        url = servidor.iniciar(abrir_navegador=False, assumir=True)
    except RuntimeError as e:
        print(e)
        return 1
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
        abrir_janela(url.rstrip("/") + "/#/jarvis")
    print("Pronto. Ctrl+C para fechar.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        servidor.parar()
    return 0


if __name__ == "__main__":
    sys.exit(main())

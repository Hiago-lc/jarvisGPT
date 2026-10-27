"""Registra o servidor MCP da HAIZEN no app do Claude (e, opcionalmente, no
Claude Code).

    py -m haizen.instalar_mcp                 # app do Claude
    py -m haizen.instalar_mcp --claude-code   # também no Claude Code

Faz uma cópia de segurança da configuração antes de alterar e preserva os
outros servidores que já estiverem lá. Depois, feche o app do Claude por
completo (bandeja do Windows) e abra de novo.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from importlib.util import find_spec
from pathlib import Path

NOME = "haizen"
SERVIDOR = Path(__file__).resolve().parent / "mcp_server.py"


def pastas_config() -> list[Path]:
    """Onde o app do Claude guarda a configuração neste sistema."""
    if sys.platform == "win32":
        achadas = []
        appdata = os.environ.get("APPDATA")
        if appdata:
            achadas.append(Path(appdata) / "Claude")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            # Instalação pela Microsoft Store guarda em outro lugar.
            achadas += sorted(Path(local, "Packages").glob("*Claude*/LocalCache/Roaming/Claude"))
        existentes = [p for p in achadas if p.is_dir()]
        return existentes or achadas[:1]
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support" / "Claude"]
    return [Path.home() / ".config" / "Claude"]


def entrada() -> dict:
    return {"command": sys.executable, "args": [str(SERVIDOR)]}


def registrar(pasta: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / "claude_desktop_config.json"
    dados = {}
    if arq.exists():
        texto = arq.read_text(encoding="utf-8").strip()
        dados = json.loads(texto) if texto else {}
        shutil.copy2(arq, arq.with_name(f"claude_desktop_config.backup-{int(time.time())}.json"))
    dados.setdefault("mcpServers", {})[NOME] = entrada()
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, arq)
    return arq


def registrar_claude_code() -> str:
    exe = shutil.which("claude")
    if not exe:
        return "Claude Code não encontrado; pulei esta parte."
    subprocess.run([exe, "mcp", "remove", "--scope", "user", NOME],
                   capture_output=True, text=True)
    r = subprocess.run([exe, "mcp", "add", "--scope", "user", NOME, "--",
                        sys.executable, str(SERVIDOR)], capture_output=True, text=True)
    return ("Registrado no Claude Code." if r.returncode == 0
            else f"Claude Code recusou: {(r.stderr or r.stdout).strip()[:300]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--claude-code", action="store_true",
                    help="registrar também no Claude Code")
    a = ap.parse_args(argv)
    if find_spec("mcp") is None:
        print("Falta o pacote do MCP. Rode: py -m pip install mcp")
        return 1
    for pasta in pastas_config():
        print(f"Registrado em {registrar(pasta)}")
    if a.claude_code:
        print(registrar_claude_code())
    print("Feche o app do Claude pela bandeja do Windows e abra de novo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

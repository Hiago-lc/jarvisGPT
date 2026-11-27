"""Atualizar o Jarvis pelo GitHub, voltar à versão anterior e gerar o pacote de diagnóstico.

Funciona onde o Jarvis foi instalado com git (servidor e notebook). Antes de atualizar faz o
backup do banco e espera os agentes terminarem; depois reinicia sozinho.
"""
from __future__ import annotations

import io
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
_TRAVA = threading.Lock()
ESTADO: dict = {"rodando": False, "etapa": "", "erro": ""}
# Nunca entram no diagnóstico: tokens, chaves, sessões, conversas inteiras.
_FORA_DIAGNOSTICO = ("acessos", "token", "sessoes", "chave", "api_keys", "cofre", "credential", ".db")


def _git(*args: str, timeout: int = 120) -> str:
    r = subprocess.run(["git", "-C", str(RAIZ), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "git falhou").strip()[-400:])
    return r.stdout.strip()


def disponivel() -> bool:
    return (RAIZ / ".git").exists() and shutil.which("git") is not None


def _arq_anterior() -> Path:
    from core.data_paths import data_dir
    return Path(data_dir()) / "versao_anterior.txt"


def info(buscar: bool = True) -> dict:
    if not disponivel():
        return {"disponivel": False, "motivo": "este Jarvis não foi instalado pelo GitHub (sem .git)"}
    if buscar:
        try:
            _git("fetch", "--quiet", timeout=60)
        except Exception as e:  # noqa: BLE001
            return {"disponivel": True, "erro": f"não consegui falar com o GitHub: {e}", **ESTADO}
    atual = _git("rev-parse", "--short", "HEAD")
    try:
        novos = _git("log", "--format=%h%x09%s%x09%cI", "HEAD..@{u}", "-n", "40")
    except RuntimeError:
        novos = ""
    commits = [dict(zip(("id", "titulo", "quando"), l.split("\t", 2))) for l in novos.splitlines() if l.strip()]
    anterior = _arq_anterior().read_text().strip() if _arq_anterior().is_file() else ""
    return {"disponivel": True, "atual": atual, "data": _git("log", "-1", "--format=%cI"),
            "novidades": commits, "anterior": anterior[:7], **ESTADO}


def _reiniciar() -> None:
    from haizen.central import acesso, servidor
    time.sleep(1.5)
    if acesso.ativo() or os.environ.get("INVOCATION_ID"):
        os._exit(0)                       # systemd sobe de novo (Restart=always)
    servidor.reiniciar()


def _esperar_agentes(limite: int = 3600) -> None:
    from haizen import worker
    fim = time.time() + limite
    while worker.ocupado() and time.time() < fim:
        ESTADO["etapa"] = "esperando os agentes terminarem o que estão fazendo"
        time.sleep(15)


def _instalar_dependencias(antes: str) -> None:
    mudou = _git("diff", "--name-only", antes, "HEAD")
    req = RAIZ / ("servidor/requirements-servidor.txt" if os.name != "nt" else "requirements.txt")
    if req.as_posix().split(f"{RAIZ.as_posix()}/")[-1] not in mudou or not req.is_file():
        return
    ESTADO["etapa"] = "instalando bibliotecas novas"
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)], timeout=1800, check=False)


def _rodar(acao: str) -> None:
    try:
        _esperar_agentes()
        ESTADO["etapa"] = "fazendo backup do banco"
        try:
            from haizen import rotina
            rotina.fazer_backup()
        except Exception as e:  # noqa: BLE001
            print(f"[Atualizar] backup não rodou: {e}")
        antes = _git("rev-parse", "HEAD")
        if acao == "atualizar":
            ESTADO["etapa"] = "baixando a versão nova"
            _git("pull", "--ff-only", timeout=300)
            _arq_anterior().write_text(antes)
        else:
            alvo = _arq_anterior().read_text().strip()
            ESTADO["etapa"] = "voltando à versão anterior"
            _git("reset", "--hard", alvo)
            _arq_anterior().write_text(antes)
        _instalar_dependencias(antes)
        ESTADO["etapa"] = "reiniciando"
        _reiniciar()
    except Exception as e:  # noqa: BLE001
        ESTADO.update(rodando=False, erro=str(e), etapa="")


def iniciar(acao: str = "atualizar") -> dict:
    if not disponivel():
        raise ValueError("este Jarvis não foi instalado pelo GitHub")
    if acao == "voltar" and not _arq_anterior().is_file():
        raise ValueError("não há versão anterior guardada")
    with _TRAVA:
        if ESTADO["rodando"]:
            return dict(ESTADO)
        ESTADO.update(rodando=True, erro="", etapa="começando")
    threading.Thread(target=_rodar, args=(acao,), name="atualizar-jarvis", daemon=True).start()
    return dict(ESTADO)


# ── diagnóstico ─────────────────────────────────────────────────────────────
def _logs() -> str:
    from core.data_paths import data_dir
    textos = []
    for nome in ("jarvis_web.log", "jarvis_janela.log"):
        p = Path(data_dir()) / nome
        if p.is_file():
            linhas = p.read_text(encoding="utf-8", errors="replace").splitlines()[-1500:]
            textos.append(f"===== {nome} =====\n" + "\n".join(linhas))
    if shutil.which("journalctl"):
        r = subprocess.run(["journalctl", "-u", "jarvis.service", "-n", "1500", "--no-pager"], capture_output=True,
                           text=True, errors="replace", timeout=30)
        if r.stdout.strip():
            textos.append("===== journalctl jarvis.service =====\n" + r.stdout)
    return "\n\n".join(textos) or "(sem registros)"


def diagnostico() -> bytes:
    from core.data_paths import data_dir
    from haizen import store, worker
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("registro.txt", _logs())
        try:
            versao = info(buscar=False)
        except Exception as e:  # noqa: BLE001
            versao = {"erro": str(e)}
        z.writestr("sistema.json", json.dumps({
            "gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"), "plataforma": platform.platform(),
            "python": sys.version, "versao": versao, "agentes_ocupados": worker.ocupado(),
            "servidor": bool(os.environ.get("HAIZEN_URL_PUBLICA"))}, ensure_ascii=False, indent=1, default=str))
        with store.conexao() as con:
            erros = [dict(r) for r in con.execute(
                "SELECT id, agente, status, titulo, erro, observacao, criado_em, atualizado_em FROM trabalhos "
                "WHERE status IN ('erro', 'executando', 'na_fila') ORDER BY atualizado_em DESC LIMIT 40")]
        z.writestr("trabalhos_com_problema.json", json.dumps(erros, ensure_ascii=False, indent=1, default=str))
        for p in Path(data_dir()).glob("*.json"):
            if not any(x in p.name.lower() for x in _FORA_DIAGNOSTICO):
                z.writestr(f"config/{p.name}", p.read_text(encoding="utf-8", errors="replace"))
    return buf.getvalue()

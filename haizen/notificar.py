"""Avisos para você: na central, no Windows (notificação com som) e no navegador.

Quando um agente termina e espera aprovação, faz uma pergunta, trava, ou o
gestor de tráfego tem otimizações, sai um aviso. A central mostra na tela e o
Windows toca o som e mostra a notificação, mesmo com a janela fechada.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

from haizen import store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notificacoes (
    id INTEGER PRIMARY KEY,
    criado_em REAL NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'info',     -- aprovacao | pergunta | erro | trafego | info
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL DEFAULT '',
    lida INTEGER NOT NULL DEFAULT 0
);
"""


def _garantir(con) -> None:
    con.executescript(_SCHEMA)


def avisar(titulo: str, texto: str = "", tipo: str = "info", link: str = "") -> dict:
    with store.conexao() as con:
        _garantir(con)
        cur = con.execute("INSERT INTO notificacoes(criado_em, tipo, titulo, texto, link) VALUES(?,?,?,?,?)",
                          (time.time(), tipo[:20], titulo[:120], texto[:400], link[:200]))
        nid = cur.lastrowid
    if sys.platform == "win32" and os.environ.get("HAIZEN_NOTIFICAR_WINDOWS", "1") != "0":
        threading.Thread(target=_windows, args=(titulo, texto), daemon=True, name="aviso-windows").start()
    return {"id": nid, "titulo": titulo, "texto": texto, "tipo": tipo, "link": link}


def listar(desde: int = 0, limite: int = 30) -> list[dict]:
    with store.conexao() as con:
        _garantir(con)
        rows = con.execute("SELECT * FROM notificacoes WHERE id > ? ORDER BY id DESC LIMIT ?",
                           (int(desde), int(limite))).fetchall()
    return [dict(r) for r in rows]


def ultimo_id() -> int:
    with store.conexao() as con:
        _garantir(con)
        r = con.execute("SELECT MAX(id) AS m FROM notificacoes").fetchone()
    return int(r["m"] or 0)


def marcar_lidas() -> None:
    with store.conexao() as con:
        _garantir(con)
        con.execute("UPDATE notificacoes SET lida=1 WHERE lida=0")


# Notificação do Windows pelo PowerShell (sem instalar nada). O título e o
# texto vão por variáveis de ambiente, nunca montados dentro do comando.
_PS = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $x.GetElementsByTagName('text')
$t.Item(0).AppendChild($x.CreateTextNode($env:HAIZEN_AVISO_TITULO)) > $null
$t.Item(1).AppendChild($x.CreateTextNode($env:HAIZEN_AVISO_TEXTO)) > $null
$n = [Windows.UI.Notifications.ToastNotification]::new($x)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show($n)
"""


def _windows(titulo: str, texto: str) -> None:
    from haizen import uso
    cfg = uso.config()["notificacoes"]
    if cfg.get("som"):
        try:
            import winsound
            winsound.PlaySound("SystemNotification", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except Exception:  # noqa: BLE001
            pass
    if not cfg.get("windows"):
        return
    try:
        env = {**os.environ, "HAIZEN_AVISO_TITULO": f"Jarvis: {titulo}"[:120], "HAIZEN_AVISO_TEXTO": texto[:250]}
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _PS],
                       env=env, capture_output=True, timeout=20,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:  # noqa: BLE001
        print(f"[Avisos] notificação do Windows: {e}")

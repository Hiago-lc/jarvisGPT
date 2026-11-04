"""Quanto cada parte do sistema gasta do Claude, e qual modelo cada uma usa.

Toda chamada ao Claude Code (Jarvis na conversa, agentes, gestor de tráfego)
é anotada com os tokens, o tempo e o custo equivalente em API que o próprio
Claude Code informa. A assinatura não cobra esse valor: ele serve como medida
do peso de cada chamada no limite de uso.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path

from haizen import store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS claude_uso (
    id INTEGER PRIMARY KEY,
    criado_em REAL NOT NULL,
    origem TEXT NOT NULL,              -- jarvis | agente | trafego
    referencia TEXT NOT NULL DEFAULT '',
    modelo TEXT NOT NULL DEFAULT '',
    entrada INTEGER NOT NULL DEFAULT 0,
    saida INTEGER NOT NULL DEFAULT 0,
    cache_leitura INTEGER NOT NULL DEFAULT 0,
    cache_escrita INTEGER NOT NULL DEFAULT 0,
    custo_usd REAL NOT NULL DEFAULT 0,
    duracao_ms INTEGER NOT NULL DEFAULT 0,
    turnos INTEGER NOT NULL DEFAULT 0,
    erro TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS claude_uso_data ON claude_uso(criado_em);
"""

# Modelos que a pessoa escolhe por área. "" = o padrão do Claude Code.
AREAS = {"jarvis": "Jarvis (conversa)", "agentes": "Agentes (produção)", "gerente": "Gerente (planos)",
         "trafego": "Gestor de tráfego"}
PADRAO_MODELOS = {"jarvis": "sonnet", "agentes": "", "gerente": "sonnet", "trafego": "sonnet"}
MODELOS = ("", "sonnet", "opus", "haiku")
_LIMITE = re.compile(r"usage limit|limit reached|rate limit|limite de uso|resets? (?:at|in)|5-hour limit|weekly limit",
                     re.I)


def _con():
    con = store.conexao()
    return con


def _garantir(con) -> None:
    con.executescript(_SCHEMA)


def _arq_config() -> Path:
    from core.data_paths import data_dir
    return Path(data_dir()) / "uso.json"


def config() -> dict:
    try:
        c = json.loads(_arq_config().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        c = {}
    return {"modelos": {**PADRAO_MODELOS, **(c.get("modelos") or {})}, "limite": c.get("limite") or {},
            "notificacoes": {"som": True, "windows": True, **(c.get("notificacoes") or {})}}


def salvar_config(mud: dict) -> dict:
    c = config()
    for area, m in (mud.get("modelos") or {}).items():
        if area in AREAS and m in MODELOS:
            c["modelos"][area] = m
    for k in ("som", "windows"):
        if k in (mud.get("notificacoes") or {}):
            c["notificacoes"][k] = bool(mud["notificacoes"][k])
    _arq_config().write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return c


def modelo(area: str, agente_modelo: str = "") -> str:
    """O modelo de uma área. Nos agentes, o do arquivo do agente vale quando a
    área está no padrão ("")."""
    escolhido = config()["modelos"].get(area, "")
    if area == "agentes" and not escolhido:
        return agente_modelo or ""
    return escolhido


def registrar(dados: dict, origem: str, referencia: str = "", erro: str = "") -> None:
    """`dados` é o resultado do Claude Code (JSON final ou o evento result)."""
    try:
        u = dados.get("usage") or {}
        modelos = list((dados.get("modelUsage") or {}).keys())
        texto_erro = erro or (str(dados.get("result") or "")[:300] if dados.get("is_error") else "")
        with store.conexao() as con:
            _garantir(con)
            con.execute(
                "INSERT INTO claude_uso(criado_em, origem, referencia, modelo, entrada, saida, cache_leitura,"
                " cache_escrita, custo_usd, duracao_ms, turnos, erro) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (time.time(), origem, str(referencia)[:120], ",".join(m.replace("claude-", "") for m in modelos)[:80],
                 int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0),
                 int(u.get("cache_read_input_tokens") or 0), int(u.get("cache_creation_input_tokens") or 0),
                 float(dados.get("total_cost_usd") or 0), int(dados.get("duration_ms") or 0),
                 int(dados.get("num_turns") or 0), texto_erro))
        if texto_erro and _LIMITE.search(texto_erro):
            marcar_limite(texto_erro)
    except Exception as e:  # noqa: BLE001 - medir nunca derruba o trabalho
        print(f"[Uso do Claude] não anotei: {e}")


def marcar_limite(texto: str) -> None:
    c = config()
    c["limite"] = {"em": time.time(), "mensagem": str(texto)[:300]}
    _arq_config().write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        from haizen import notificar
        notificar.avisar("Limite do Claude", "O Claude chegou ao limite de uso. Os agentes voltam quando ele liberar.",
                         "erro", "#/uso")
    except Exception:  # noqa: BLE001
        pass


def resumo(dias: int = 7) -> dict:
    agora = time.time()
    inicio_hoje = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
    desde = inicio_hoje - (max(1, int(dias)) - 1) * 86400
    with store.conexao() as con:
        _garantir(con)
        linhas = [dict(r) for r in con.execute(
            "SELECT * FROM claude_uso WHERE criado_em >= ? ORDER BY id DESC", (desde,)).fetchall()]

    def soma(rs):
        return {"chamadas": len(rs), "custo_usd": round(sum(r["custo_usd"] for r in rs), 4),
                "tokens": sum(r["entrada"] + r["saida"] + r["cache_escrita"] for r in rs),
                "saida": sum(r["saida"] for r in rs), "minutos": round(sum(r["duracao_ms"] for r in rs) / 60000, 1)}
    hoje = [r for r in linhas if r["criado_em"] >= inicio_hoje]
    ultimas5h = [r for r in linhas if r["criado_em"] >= agora - 5 * 3600]
    por_origem = {}
    for r in linhas:
        por_origem.setdefault(r["origem"], []).append(r)
    por_dia = {}
    for r in linhas:
        por_dia.setdefault(dt.date.fromtimestamp(r["criado_em"]).isoformat(), []).append(r)
    por_ref = {}
    for r in linhas:
        if r["referencia"]:
            por_ref.setdefault((r["origem"], r["referencia"]), []).append(r)
    maiores = sorted(({"origem": o, "referencia": ref, **soma(rs)} for (o, ref), rs in por_ref.items()),
                     key=lambda x: -x["custo_usd"])[:10]
    c = config()
    limite = c["limite"] if c["limite"] and agora - c["limite"].get("em", 0) < 6 * 3600 else None
    return {"hoje": soma(hoje), "ultimas_5h": soma(ultimas5h), "periodo": soma(linhas), "dias": dias,
            "por_origem": {o: soma(rs) for o, rs in por_origem.items()},
            "por_dia": [{"dia": d, **soma(rs)} for d, rs in sorted(por_dia.items())],
            "maiores": maiores, "recentes": linhas[:25], "limite": limite,
            "modelos": c["modelos"], "areas": AREAS, "notificacoes": c["notificacoes"]}

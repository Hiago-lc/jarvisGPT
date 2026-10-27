"""Cadastro, edição e indicadores da central, sobre o mesmo banco da HAIZEN.

Valores trafegam em reais (float) na API e ficam em centavos no banco.
Os acessos (logins e senhas) de uma tarefa nunca saem nas listagens: só por
`acessos_da_tarefa`, chamado quando você clica para ver.
"""
from __future__ import annotations

import datetime as dt
import json
import time

from haizen import store

STATUS_TAREFA = ("A Fazer", "Em Andamento", "Em Revisão", "Concluída")
PRIORIDADES = ("Baixa", "Média", "Alta", "Urgente")
ETAPAS = ("Lead", "Contato", "Proposta", "Negociação", "Ganho", "Perdido")
STATUS_CLIENTE = ("Ativo", "Pausado", "Ex-Cliente")
CATEGORIAS = ("Assinaturas", "Impostos", "Marketing", "Equipamentos", "Freelancers",
              "Outros")


def hoje() -> str:
    return dt.date.today().isoformat()


def centavos(valor) -> int:
    if valor in (None, ""):
        return 0
    if isinstance(valor, str):
        v = valor.strip().replace("R$", "").replace(" ", "")
        if "," in v:                      # 1.234,56 → 1234.56
            v = v.replace(".", "").replace(",", ".")
        valor = v
    return int(round(float(valor) * 100))


def reais(c) -> float:
    return round((c or 0) / 100, 2)


def _data(v) -> str:
    v = (v or "").strip()[:10]
    if not v:
        return ""
    dt.date.fromisoformat(v)              # valida; levanta ValueError se inválida
    return v


def _bool(v) -> int:
    if isinstance(v, str):
        return int(v.strip().lower() in ("1", "true", "sim", "yes", "on"))
    return int(bool(v))


def _opcao(v, opcoes, padrao):
    v = (v or "").strip()
    if not v:
        return padrao
    if v not in opcoes:
        raise ValueError(f"valor inválido '{v}'; use um destes: {', '.join(opcoes)}")
    return v


def _cliente_id(v):
    if v in (None, "", 0, "0"):
        return None
    return int(v)


# ── normalização por entidade ───────────────────────────────────────────────
def _norm_receita(d: dict, atual: dict | None = None) -> dict:
    out = {}
    if "cliente_id" in d: out["cliente_id"] = _cliente_id(d["cliente_id"])
    if "descricao" in d: out["descricao"] = (d["descricao"] or "").strip()
    if "valor" in d: out["valor_centavos"] = centavos(d["valor"])
    if "vencimento" in d: out["vencimento"] = _data(d["vencimento"])
    if "recebido" in d: out["recebido"] = _bool(d["recebido"])
    if "data_recebimento" in d: out["data_recebimento"] = _data(d["data_recebimento"])
    if "mes_referencia" in d: out["mes_referencia"] = (d["mes_referencia"] or "")[:7]
    final = {**(atual or {}), **out}
    if final.get("recebido") and not final.get("data_recebimento"):
        out["data_recebimento"] = hoje()
    if "recebido" in out and not out["recebido"]:
        out["data_recebimento"] = ""
    if not final.get("mes_referencia") and final.get("vencimento"):
        out["mes_referencia"] = final["vencimento"][:7]
    return out


def _norm_despesa(d: dict, atual: dict | None = None) -> dict:
    out = {}
    if "descricao" in d: out["descricao"] = (d["descricao"] or "").strip()
    if "categoria" in d: out["categoria"] = (d["categoria"] or "Outros").strip() or "Outros"
    if "valor" in d: out["valor_centavos"] = centavos(d["valor"])
    if "vencimento" in d: out["vencimento"] = _data(d["vencimento"])
    if "pago" in d: out["pago"] = _bool(d["pago"])
    if "data_pagamento" in d: out["data_pagamento"] = _data(d["data_pagamento"])
    if "mes_referencia" in d: out["mes_referencia"] = (d["mes_referencia"] or "")[:7]
    final = {**(atual or {}), **out}
    if final.get("pago") and not final.get("data_pagamento"):
        out["data_pagamento"] = hoje()
    if "pago" in out and not out["pago"]:
        out["data_pagamento"] = ""
    if not final.get("mes_referencia") and final.get("vencimento"):
        out["mes_referencia"] = final["vencimento"][:7]
    return out


def _norm_tarefa(d: dict, atual: dict | None = None) -> dict:
    out = {}
    for k in ("titulo", "descricao", "acessos"):
        if k in d: out[k] = (d[k] or "").strip()
    if "cliente_id" in d: out["cliente_id"] = _cliente_id(d["cliente_id"])
    if "status" in d: out["status"] = _opcao(d["status"], STATUS_TAREFA, "A Fazer")
    if "prioridade" in d: out["prioridade"] = _opcao(d["prioridade"], PRIORIDADES, "Média")
    if "data_entrega" in d: out["data_entrega"] = _data(d["data_entrega"])
    if "horas_estimadas" in d: out["horas_estimadas"] = float(d["horas_estimadas"] or 0)
    if "comentarios" in d:
        c = d["comentarios"]
        out["comentarios"] = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
    if "status" in out:
        antes = (atual or {}).get("status")
        if out["status"] == "Concluída" and antes != "Concluída":
            out["concluida_em"] = hoje()
        elif out["status"] != "Concluída":
            out["concluida_em"] = ""
    return out


def _norm_oportunidade(d: dict, atual: dict | None = None) -> dict:
    out = {}
    for k in ("titulo", "contato", "servico", "notas"):
        if k in d: out[k] = (d[k] or "").strip()
    if "cliente_id" in d: out["cliente_id"] = _cliente_id(d["cliente_id"])
    if "valor" in d: out["valor_centavos"] = centavos(d["valor"])
    if "etapa" in d: out["etapa"] = _opcao(d["etapa"], ETAPAS, "Lead")
    if "previsao" in d: out["previsao"] = _data(d["previsao"])
    return out


def _norm_cliente(d: dict, atual: dict | None = None) -> dict:
    out = {}
    if "nome" in d:
        out["nome"] = (d["nome"] or "").strip()
        if not out["nome"]:
            raise ValueError("o cliente precisa de um nome")
        out["chave"] = store.chave(out["nome"])
    for k in ("contato", "email", "endereco", "notas"):
        if k in d: out[k] = (d[k] or "").strip()
    if "status" in d: out["status"] = _opcao(d["status"], STATUS_CLIENTE, "Ativo")
    return out


def _norm_marca(d: dict, atual: dict | None = None) -> dict:
    out = {}
    if "nome" in d:
        out["nome"] = (d["nome"] or "").strip()
        out["chave"] = store.chave(out["nome"])
    for k in ("pasta", "notas"):
        if k in d: out[k] = (d[k] or "").strip()
    if "cliente_id" in d: out["cliente_id"] = _cliente_id(d["cliente_id"])
    return out


def _norm_subtarefa(d: dict, atual: dict | None = None) -> dict:
    out = {}
    if "tarefa_id" in d: out["tarefa_id"] = int(d["tarefa_id"])
    if "titulo" in d: out["titulo"] = (d["titulo"] or "").strip()
    if "concluida" in d: out["concluida"] = _bool(d["concluida"])
    if "ordem" in d: out["ordem"] = int(d["ordem"] or 0)
    return out


ENTIDADES = {
    "receitas": (_norm_receita, ("valor",), True, False),
    "despesas": (_norm_despesa, ("descricao", "valor"), True, False),
    "tarefas": (_norm_tarefa, ("titulo",), True, True),
    "oportunidades": (_norm_oportunidade, ("titulo",), True, True),
    "clientes": (_norm_cliente, ("nome",), True, True),
    "marcas": (_norm_marca, ("nome",), False, False),
    "subtarefas": (_norm_subtarefa, ("tarefa_id", "titulo"), False, False),
}
# (normalizador, campos obrigatórios na criação, tem criado_em, tem atualizado_em)


def _publico(entidade: str, row) -> dict:
    d = dict(row)
    if "valor_centavos" in d:
        d["valor"] = reais(d.pop("valor_centavos"))
    if entidade == "tarefas":
        d["tem_acessos"] = bool(d.pop("acessos", ""))
        try:
            d["comentarios"] = json.loads(d.get("comentarios") or "[]")
        except ValueError:
            d["comentarios"] = []
    if entidade == "clientes":
        d.pop("chave", None)
        try:
            d["dados"] = json.loads(d.get("dados") or "{}")
        except ValueError:
            d["dados"] = {}
    for k in ("recebido", "pago", "concluida"):
        if k in d:
            d[k] = bool(d[k])
    return d


def obter(entidade: str, rid: int) -> dict | None:
    ENTIDADES[entidade]                    # valida o nome da tabela
    with store.conexao() as con:
        row = con.execute(f"SELECT * FROM {entidade} WHERE id=?", (int(rid),)).fetchone()
        return _publico(entidade, row) if row else None


def criar(entidade: str, d: dict) -> dict:
    norm, obrig, tem_criado, tem_atual = ENTIDADES[entidade]
    falta = [c for c in obrig if d.get(c) in (None, "")]
    if falta:
        raise ValueError(f"faltam campos: {', '.join(falta)}")
    campos = norm(d)
    agora = time.time()
    if tem_criado: campos["criado_em"] = agora
    if tem_atual: campos["atualizado_em"] = agora
    if entidade == "clientes":
        campos.setdefault("dados", "{}")
    cols = ", ".join(campos)
    with store.conexao() as con:
        cur = con.execute(f"INSERT INTO {entidade}({cols}) VALUES({', '.join('?' * len(campos))})",
                          tuple(campos.values()))
        rid = cur.lastrowid
    return obter(entidade, rid)


def atualizar(entidade: str, rid: int, d: dict) -> dict:
    norm, _, _, tem_atual = ENTIDADES[entidade]
    with store.conexao() as con:
        row = con.execute(f"SELECT * FROM {entidade} WHERE id=?", (int(rid),)).fetchone()
    if row is None:
        raise KeyError(f"não encontrado: {entidade} {rid}")
    campos = norm(d, dict(row))
    if tem_atual: campos["atualizado_em"] = time.time()
    if campos:
        with store.conexao() as con:
            con.execute(f"UPDATE {entidade} SET {', '.join(f'{k}=?' for k in campos)} WHERE id=?",
                        (*campos.values(), int(rid)))
    return obter(entidade, rid)


def apagar(entidade: str, rid: int) -> None:
    ENTIDADES[entidade]
    with store.conexao() as con:
        if entidade == "clientes":
            for t in ("receitas", "tarefas", "oportunidades", "marcas", "trabalhos"):
                con.execute(f"UPDATE {t} SET cliente_id=NULL WHERE cliente_id=?", (int(rid),))
        con.execute(f"DELETE FROM {entidade} WHERE id=?", (int(rid),))


def listar(entidade: str, **filtros) -> list[dict]:
    ENTIDADES[entidade]
    onde, args = [], []
    for k, v in filtros.items():
        if v in (None, ""):
            continue
        if k == "de":
            col = {"receitas": "COALESCE(NULLIF(e.data_recebimento,''), e.vencimento)",
                   "despesas": "COALESCE(NULLIF(e.data_pagamento,''), e.vencimento)"}.get(entidade)
            if col: onde.append(f"{col} >= ?"); args.append(v)
        elif k == "ate":
            col = {"receitas": "COALESCE(NULLIF(e.data_recebimento,''), e.vencimento)",
                   "despesas": "COALESCE(NULLIF(e.data_pagamento,''), e.vencimento)"}.get(entidade)
            if col: onde.append(f"{col} <= ?"); args.append(v)
        elif k in ("cliente_id", "status", "etapa", "tarefa_id", "categoria"):
            onde.append(f"e.{k} = ?"); args.append(v)
    junta = ""
    extra = ""
    if entidade in ("receitas", "tarefas", "oportunidades", "marcas"):
        junta = " LEFT JOIN clientes c ON c.id = e.cliente_id"
        extra = ", c.nome AS cliente_nome"
    ordem = {
        "receitas": "COALESCE(NULLIF(e.data_recebimento,''), e.vencimento) DESC, e.id DESC",
        "despesas": "COALESCE(NULLIF(e.data_pagamento,''), e.vencimento) DESC, e.id DESC",
        "tarefas": "CASE e.status WHEN 'Concluída' THEN 1 ELSE 0 END, "
                   "CASE WHEN e.data_entrega='' THEN '9999' ELSE e.data_entrega END, e.id DESC",
        "oportunidades": "e.atualizado_em DESC",
        "clientes": "CASE e.status WHEN 'Ativo' THEN 0 ELSE 1 END, e.nome COLLATE NOCASE",
        "marcas": "e.nome COLLATE NOCASE",
        "subtarefas": "e.ordem, e.id",
    }[entidade]
    sql = (f"SELECT e.*{extra} FROM {entidade} e{junta}"
           + (f" WHERE {' AND '.join(onde)}" if onde else "") + f" ORDER BY {ordem}")
    with store.conexao() as con:
        return [_publico(entidade, r) for r in con.execute(sql, args)]


def acessos_da_tarefa(rid: int) -> str:
    with store.conexao() as con:
        row = con.execute("SELECT acessos FROM tarefas WHERE id=?", (int(rid),)).fetchone()
    if row is None:
        raise KeyError(f"não encontrado: tarefa {rid}")
    return row["acessos"]


# ── visão de um cliente ─────────────────────────────────────────────────────
def ficha_cliente(cid: int) -> dict:
    c = obter("clientes", cid)
    if c is None:
        raise KeyError(f"não encontrado: cliente {cid}")
    receitas = listar("receitas", cliente_id=cid)
    with store.conexao() as con:
        trabalhos = [dict(r) for r in con.execute(
            "SELECT id, agente, status, arquivo, criado_em FROM trabalhos "
            "WHERE cliente_id=? ORDER BY id DESC LIMIT 20", (cid,))]
    return {
        "cliente": c,
        "receitas": receitas,
        "tarefas": listar("tarefas", cliente_id=cid),
        "oportunidades": listar("oportunidades", cliente_id=cid),
        "marcas": listar("marcas", cliente_id=cid),
        "trabalhos": trabalhos,
        "total_recebido": round(sum(r["valor"] for r in receitas if r["recebido"]), 2),
        "em_aberto": round(sum(r["valor"] for r in receitas if not r["recebido"]), 2),
    }


# ── painel ──────────────────────────────────────────────────────────────────
def _meses(fim: str, n: int) -> list[str]:
    a, m = int(fim[:4]), int(fim[5:7])
    out = []
    for _ in range(n):
        out.append(f"{a:04d}-{m:02d}")
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    return out[::-1]


def painel(de: str, ate: str) -> dict:
    de, ate = _data(de), _data(ate)
    if de > ate:
        de, ate = ate, de
    hj = hoje()
    with store.conexao() as con:
        q = lambda sql, *a: con.execute(sql, a).fetchone()[0] or 0  # noqa: E731
        receita = q("SELECT SUM(valor_centavos) FROM receitas WHERE recebido=1 "
                    "AND data_recebimento BETWEEN ? AND ?", de, ate)
        custos = q("SELECT SUM(valor_centavos) FROM despesas WHERE pago=1 "
                   "AND data_pagamento BETWEEN ? AND ?", de, ate)
        vencido = q("SELECT SUM(valor_centavos) FROM receitas WHERE recebido=0 "
                    "AND vencimento<>'' AND vencimento < ?", hj)
        a_receber = q("SELECT SUM(valor_centavos) FROM receitas WHERE recebido=0")
        a_pagar = q("SELECT SUM(valor_centavos) FROM despesas WHERE pago=0")
        devido_periodo = q("SELECT SUM(valor_centavos) FROM receitas "
                           "WHERE vencimento BETWEEN ? AND ?", de, ate)
        vencido_periodo = q("SELECT SUM(valor_centavos) FROM receitas WHERE recebido=0 "
                            "AND vencimento BETWEEN ? AND ? AND vencimento < ?", de, ate, hj)
        concluidas = q("SELECT COUNT(*) FROM tarefas WHERE status='Concluída' "
                       "AND concluida_em BETWEEN ? AND ?", de, ate)
        atrasadas = q("SELECT COUNT(*) FROM tarefas WHERE status<>'Concluída' "
                      "AND data_entrega<>'' AND data_entrega < ?", hj)
        abertas = q("SELECT COUNT(*) FROM tarefas WHERE status<>'Concluída'")

        fim_mes = ate
        meses = _meses(fim_mes, 12)
        serie = {m: {"mes": m, "receita": 0, "custos": 0} for m in meses}
        for r in con.execute("SELECT substr(data_recebimento,1,7) m, SUM(valor_centavos) v "
                             "FROM receitas WHERE recebido=1 GROUP BY m"):
            if r["m"] in serie: serie[r["m"]]["receita"] = r["v"]
        for r in con.execute("SELECT substr(data_pagamento,1,7) m, SUM(valor_centavos) v "
                             "FROM despesas WHERE pago=1 GROUP BY m"):
            if r["m"] in serie: serie[r["m"]]["custos"] = r["v"]

        categorias = [{"categoria": r["categoria"], "valor": reais(r["v"])} for r in con.execute(
            "SELECT categoria, SUM(valor_centavos) v FROM despesas WHERE pago=1 "
            "AND data_pagamento BETWEEN ? AND ? GROUP BY categoria ORDER BY v DESC", (de, ate))]

        top = [{"cliente_id": r["cliente_id"], "cliente": r["nome"] or "Sem cliente",
                "valor": reais(r["v"])} for r in con.execute(
            "SELECT r.cliente_id, c.nome, SUM(r.valor_centavos) v FROM receitas r "
            "LEFT JOIN clientes c ON c.id=r.cliente_id WHERE r.recebido=1 "
            "AND r.data_recebimento BETWEEN ? AND ? GROUP BY r.cliente_id ORDER BY v DESC LIMIT 8",
            (de, ate))]

        pipeline = {e: {"etapa": e, "quantidade": 0, "valor": 0.0} for e in ETAPAS}
        for r in con.execute("SELECT etapa, COUNT(*) n, SUM(valor_centavos) v "
                             "FROM oportunidades GROUP BY etapa"):
            if r["etapa"] in pipeline:
                pipeline[r["etapa"]].update(quantidade=r["n"], valor=reais(r["v"]))

        proximas = [dict(r) for r in con.execute(
            "SELECT t.id, t.titulo, t.data_entrega, t.status, t.prioridade, c.nome cliente_nome "
            "FROM tarefas t LEFT JOIN clientes c ON c.id=t.cliente_id "
            "WHERE t.status<>'Concluída' ORDER BY CASE WHEN t.data_entrega='' THEN '9999' "
            "ELSE t.data_entrega END LIMIT 6")]
        aguardando = q("SELECT COUNT(*) FROM trabalhos WHERE status='aguardando_aprovacao'")

    return {
        "periodo": {"de": de, "ate": ate},
        "receita": reais(receita),
        "custos": reais(custos),
        "lucro": reais(receita - custos),
        "margem": round((receita - custos) / receita * 100, 1) if receita else 0.0,
        "inadimplencia": round(vencido_periodo / devido_periodo * 100, 1) if devido_periodo else 0.0,
        "vencido": reais(vencido),
        "a_receber": reais(a_receber),
        "a_pagar": reais(a_pagar),
        "tarefas_concluidas": concluidas,
        "tarefas_atrasadas": atrasadas,
        "tarefas_abertas": abertas,
        "serie": [{"mes": s["mes"], "receita": reais(s["receita"]),
                   "custos": reais(s["custos"])} for s in serie.values()],
        "categorias": categorias,
        "top_clientes": top,
        "pipeline": list(pipeline.values()),
        "proximas_tarefas": proximas,
        "entregas_aguardando": aguardando,
    }


def opcoes() -> dict:
    with store.conexao() as con:
        cats = [r[0] for r in con.execute("SELECT DISTINCT categoria FROM despesas")]
    return {
        "status_tarefa": STATUS_TAREFA, "prioridades": PRIORIDADES, "etapas": ETAPAS,
        "status_cliente": STATUS_CLIENTE,
        "categorias": sorted(set(CATEGORIAS) | set(cats)),
        "clientes": [{"id": c["id"], "nome": c["nome"], "status": c["status"]}
                     for c in listar("clientes")],
    }

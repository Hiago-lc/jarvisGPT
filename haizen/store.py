"""Fichas de clientes e trabalhos, em SQLite.

O banco fica na pasta de dados do Jarvis (fora do repositório; no Windows,
%LOCALAPPDATA%\\JarvisGPT\\haizen.db). As entregas vão para uma pasta que você
abre no Explorer: Documentos\\HAIZEN\\entregas.

O Jarvis e o servidor MCP do Claude abrem o mesmo banco em processos
diferentes; o modo WAL e o tempo de espera cuidam disso.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path

STATUS = ("na_fila", "executando", "aguardando_aprovacao",
          "aprovado", "rejeitado", "erro")


def _dados_dir() -> Path:
    try:
        from core.data_paths import data_dir
        return data_dir()
    except Exception:
        p = Path.home() / ".jarvisgpt"
        p.mkdir(parents=True, exist_ok=True)
        return p


def caminho_banco() -> Path:
    override = os.environ.get("HAIZEN_DB", "").strip()
    return Path(override) if override else _dados_dir() / "haizen.db"


def pasta_entregas() -> Path:
    override = os.environ.get("HAIZEN_ENTREGAS_DIR", "").strip()
    p = Path(override) if override else Path.home() / "Documents" / "HAIZEN" / "entregas"
    p.mkdir(parents=True, exist_ok=True)
    return p


_SCHEMA = """
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    chave TEXT NOT NULL UNIQUE,
    dados TEXT NOT NULL DEFAULT '{}',
    notas TEXT NOT NULL DEFAULT '',
    criado_em REAL NOT NULL,
    atualizado_em REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS trabalhos (
    id INTEGER PRIMARY KEY,
    agente TEXT NOT NULL,
    cliente_id INTEGER REFERENCES clientes(id),
    pedido TEXT NOT NULL,
    executor TEXT NOT NULL,
    status TEXT NOT NULL,
    arquivo TEXT NOT NULL DEFAULT '',
    erro TEXT NOT NULL DEFAULT '',
    observacao TEXT NOT NULL DEFAULT '',
    criado_em REAL NOT NULL,
    atualizado_em REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS trabalhos_status ON trabalhos(status);

-- ── Central (faturamento, tarefas, pipeline) ───────────────────────────────
-- Valores em centavos (inteiro): soma de dinheiro em ponto flutuante erra.
-- Datas em texto ISO (AAAA-MM-DD). base44_id permite reimportar sem duplicar.
CREATE TABLE IF NOT EXISTS marcas (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    chave TEXT NOT NULL UNIQUE,
    pasta TEXT NOT NULL DEFAULT '',
    cliente_id INTEGER REFERENCES clientes(id),
    notas TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS receitas (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER REFERENCES clientes(id),
    descricao TEXT NOT NULL DEFAULT '',
    valor_centavos INTEGER NOT NULL,
    vencimento TEXT NOT NULL DEFAULT '',
    recebido INTEGER NOT NULL DEFAULT 0,
    data_recebimento TEXT NOT NULL DEFAULT '',
    mes_referencia TEXT NOT NULL DEFAULT '',
    base44_id TEXT UNIQUE,
    criado_em REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS despesas (
    id INTEGER PRIMARY KEY,
    descricao TEXT NOT NULL,
    categoria TEXT NOT NULL DEFAULT 'Outros',
    valor_centavos INTEGER NOT NULL,
    vencimento TEXT NOT NULL DEFAULT '',
    pago INTEGER NOT NULL DEFAULT 0,
    data_pagamento TEXT NOT NULL DEFAULT '',
    mes_referencia TEXT NOT NULL DEFAULT '',
    base44_id TEXT UNIQUE,
    criado_em REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tarefas (
    id INTEGER PRIMARY KEY,
    titulo TEXT NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    acessos TEXT NOT NULL DEFAULT '',
    cliente_id INTEGER REFERENCES clientes(id),
    status TEXT NOT NULL DEFAULT 'A Fazer',
    prioridade TEXT NOT NULL DEFAULT 'Média',
    data_entrega TEXT NOT NULL DEFAULT '',
    horas_estimadas REAL NOT NULL DEFAULT 0,
    comentarios TEXT NOT NULL DEFAULT '[]',
    concluida_em TEXT NOT NULL DEFAULT '',
    base44_id TEXT UNIQUE,
    criado_em REAL NOT NULL,
    atualizado_em REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS subtarefas (
    id INTEGER PRIMARY KEY,
    tarefa_id INTEGER NOT NULL REFERENCES tarefas(id) ON DELETE CASCADE,
    titulo TEXT NOT NULL,
    concluida INTEGER NOT NULL DEFAULT 0,
    ordem INTEGER NOT NULL DEFAULT 0,
    base44_id TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS oportunidades (
    id INTEGER PRIMARY KEY,
    titulo TEXT NOT NULL,
    cliente_id INTEGER REFERENCES clientes(id),
    contato TEXT NOT NULL DEFAULT '',
    servico TEXT NOT NULL DEFAULT '',
    valor_centavos INTEGER NOT NULL DEFAULT 0,
    etapa TEXT NOT NULL DEFAULT 'Lead',
    notas TEXT NOT NULL DEFAULT '',
    previsao TEXT NOT NULL DEFAULT '',
    base44_id TEXT UNIQUE,
    criado_em REAL NOT NULL,
    atualizado_em REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS receitas_receb ON receitas(data_recebimento);
CREATE INDEX IF NOT EXISTS despesas_pag ON despesas(data_pagamento);
CREATE INDEX IF NOT EXISTS tarefas_status ON tarefas(status);
"""

# Colunas acrescentadas a tabelas que já existiam em bancos de versões
# anteriores. CREATE TABLE IF NOT EXISTS não altera uma tabela existente.
_COLUNAS_NOVAS = {
    "clientes": {
        "status": "TEXT NOT NULL DEFAULT 'Ativo'",
        "contato": "TEXT NOT NULL DEFAULT ''",
        "email": "TEXT NOT NULL DEFAULT ''",
        "endereco": "TEXT NOT NULL DEFAULT ''",
        "base44_id": "TEXT",
    },
}


def _migrar(con) -> None:
    for tabela, colunas in _COLUNAS_NOVAS.items():
        existentes = {r[1] for r in con.execute(f"PRAGMA table_info({tabela})")}
        for nome, tipo in colunas.items():
            if nome not in existentes:
                con.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS clientes_base44 "
                "ON clientes(base44_id) WHERE base44_id IS NOT NULL")


@contextmanager
def conexao():
    db = caminho_banco()
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript(_SCHEMA)
        _migrar(con)
        yield con
        con.commit()
    finally:
        con.close()


def chave(nome: str) -> str:
    """'Padaria São João ' -> 'padaria sao joao'. Busca sem acento e sem caixa."""
    n = unicodedata.normalize("NFKD", nome or "")
    n = "".join(c for c in n if not unicodedata.combining(c))
    return " ".join(n.lower().split())


# ── clientes ────────────────────────────────────────────────────────────────
def _cliente(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["dados"] = json.loads(d.get("dados") or "{}")
    return d


def salvar_cliente(nome: str, dados: dict | None = None, notas: str = "") -> dict:
    """Cria a ficha ou atualiza a existente (os campos de `dados` são somados
    aos que já existem; `notas` novas são acrescentadas, não substituídas)."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("o cliente precisa de um nome")
    agora = time.time()
    with conexao() as con:
        atual = con.execute("SELECT * FROM clientes WHERE chave=?", (chave(nome),)).fetchone()
        if atual is None:
            con.execute(
                "INSERT INTO clientes(nome, chave, dados, notas, criado_em, atualizado_em)"
                " VALUES(?,?,?,?,?,?)",
                (nome, chave(nome), json.dumps(dados or {}, ensure_ascii=False),
                 (notas or "").strip(), agora, agora))
        else:
            merged = json.loads(atual["dados"] or "{}")
            merged.update(dados or {})
            todas = "\n".join(x for x in (atual["notas"], (notas or "").strip()) if x)
            con.execute("UPDATE clientes SET dados=?, notas=?, atualizado_em=? WHERE id=?",
                        (json.dumps(merged, ensure_ascii=False), todas, agora, atual["id"]))
        return _cliente(con.execute("SELECT * FROM clientes WHERE chave=?",
                                    (chave(nome),)).fetchone())


def buscar_cliente(nome: str) -> dict | None:
    """Pelo nome exato (sem acento/caixa) ou, se só um bater, por parte dele."""
    k = chave(nome)
    if not k:
        return None
    with conexao() as con:
        row = con.execute("SELECT * FROM clientes WHERE chave=?", (k,)).fetchone()
        if row is not None:
            return _cliente(row)
        rows = con.execute("SELECT * FROM clientes WHERE chave LIKE ?", (f"%{k}%",)).fetchall()
        return _cliente(rows[0]) if len(rows) == 1 else None


def listar_clientes() -> list[dict]:
    with conexao() as con:
        return [_cliente(r) for r in con.execute("SELECT * FROM clientes ORDER BY nome")]


def cliente_por_id(cid) -> dict | None:
    if cid is None:
        return None
    with conexao() as con:
        return _cliente(con.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone())


# ── trabalhos ───────────────────────────────────────────────────────────────
def criar_trabalho(agente: str, pedido: str, executor: str,
                   cliente_id: int | None = None) -> dict:
    if not (pedido or "").strip():
        raise ValueError("o trabalho precisa de um pedido")
    agora = time.time()
    with conexao() as con:
        cur = con.execute(
            "INSERT INTO trabalhos(agente, cliente_id, pedido, executor, status,"
            " criado_em, atualizado_em) VALUES(?,?,?,?,?,?,?)",
            (agente, cliente_id, pedido.strip(), executor, "na_fila", agora, agora))
        return dict(con.execute("SELECT * FROM trabalhos WHERE id=?", (cur.lastrowid,)).fetchone())


def trabalho(tid: int) -> dict | None:
    with conexao() as con:
        row = con.execute("SELECT * FROM trabalhos WHERE id=?", (int(tid),)).fetchone()
        return dict(row) if row else None


def listar_trabalhos(status: str | None = None, limite: int = 20) -> list[dict]:
    with conexao() as con:
        if status:
            rows = con.execute("SELECT * FROM trabalhos WHERE status=? ORDER BY id DESC LIMIT ?",
                               (status, limite))
        else:
            rows = con.execute("SELECT * FROM trabalhos ORDER BY id DESC LIMIT ?", (limite,))
        return [dict(r) for r in rows]


def atualizar(tid: int, **campos) -> dict:
    if "status" in campos and campos["status"] not in STATUS:
        raise ValueError(f"status inválido: {campos['status']}")
    permitidos = {"status", "arquivo", "erro", "observacao", "executor"}
    sets = {k: v for k, v in campos.items() if k in permitidos}
    sets["atualizado_em"] = time.time()
    with conexao() as con:
        con.execute(f"UPDATE trabalhos SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                    (*sets.values(), int(tid)))
    t = trabalho(tid)
    if t is None:
        raise KeyError(f"não existe o trabalho {tid}")
    return t


def pegar_proximo() -> dict | None:
    """Marca o trabalho mais antigo da fila como 'executando' e o devolve.
    A troca de status é atômica, então dois processos nunca pegam o mesmo."""
    with conexao() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM trabalhos WHERE status='na_fila' "
                          "ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return None
        con.execute("UPDATE trabalhos SET status='executando', atualizado_em=? WHERE id=?",
                    (time.time(), row["id"]))
        d = dict(row)
        d["status"] = "executando"
        return d


def recuperar_interrompidos() -> int:
    """Trabalhos que ficaram 'executando' quando o Jarvis fechou voltam à fila."""
    with conexao() as con:
        cur = con.execute("UPDATE trabalhos SET status='na_fila', atualizado_em=? "
                          "WHERE status='executando'", (time.time(),))
        return cur.rowcount


def gravar_entrega(tid: int, conteudo: str) -> Path:
    t = trabalho(tid)
    if t is None:
        raise KeyError(f"não existe o trabalho {tid}")
    cliente = cliente_por_id(t["cliente_id"])
    sufixo = chave(cliente["nome"]).replace(" ", "-") if cliente else "sem-cliente"
    arq = pasta_entregas() / f"{tid:04d}-{t['agente']}-{sufixo}.md"
    arq.write_text(conteudo.strip() + "\n", encoding="utf-8")
    atualizar(tid, status="aguardando_aprovacao", arquivo=str(arq), erro="")
    return arq

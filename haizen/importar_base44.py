"""Importa os CSVs exportados do Base44 e as pastas de clientes do Drive.

    py -m haizen.importar_base44 PASTA_DOS_CSVS [--drive "G:\\Meu Drive\\CLIENTES"]
                                 [--apagar-csv]

Pode rodar de novo quantas vezes quiser: cada registro do Base44 é reconhecido
pelo id dele e atualizado, nunca duplicado.

Logins e senhas que estavam no texto das tarefas (e nos comentários) são
tirados de lá e guardados no campo protegido "acessos" da tarefa, que a
central só mostra quando você clica e que nunca vai para os agentes de IA.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from haizen import store
from haizen.central import dados

AVISO_ACESSOS = "[Acessos guardados no campo protegido da tarefa]"

# ── separar acessos ─────────────────────────────────────────────────────────
_PALAVRAS = re.compile(
    r"\b(senha|password|passwd|login|usu[aá]rio|user(name)?|cpanel|wp-admin|"
    r"hostgator|hostinger|hostinguer|wordpress|ftp|smtp)\b", re.I)
_ESPECIAIS = set("!@#$%^&*()_+=[]{}|~;")


def _parece_senha(linha: str) -> bool:
    t = linha.strip()
    if " " in t or len(t) < 8 or "://" in t or t.lower().startswith("www."):
        return False
    return (any(c.isdigit() for c in t) and any(c.isalpha() for c in t)
            and any(c in _ESPECIAIS for c in t))


def separar_acessos(texto: str) -> tuple[str, str]:
    """(texto sem acessos, acessos). Trabalha por blocos separados por linha em
    branco: um bloco com palavra de acesso ou com algo que parece senha vai
    inteiro para os acessos, porque usuário e senha costumam vir juntos."""
    if not (texto or "").strip():
        return "", ""
    blocos = re.split(r"\n\s*\n", texto.replace("\r\n", "\n"))
    limpos, acessos = [], []
    for b in blocos:
        linhas = [l for l in b.split("\n") if l.strip()]
        if any(_PALAVRAS.search(l) for l in linhas) or any(_parece_senha(l) for l in linhas):
            acessos.append(b.strip())
        else:
            limpos.append(b.strip())
    limpo = "\n\n".join(x for x in limpos if x)
    if acessos:
        limpo = (limpo + "\n\n" + AVISO_ACESSOS).strip()
    return limpo, "\n\n".join(acessos)


# ── leitura ─────────────────────────────────────────────────────────────────
def _ler(pasta: Path, nome: str) -> list[dict]:
    arqs = sorted(pasta.glob(f"*{nome}_export*.csv"))
    if not arqs:
        return []
    with open(arqs[-1], encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("is_sample", "false") != "true"]


def _nome(v: str) -> str:
    """O Base44 prefixa com ' nomes que começam com + (proteção contra fórmula)."""
    return (v or "").strip().lstrip("'").strip()


def _epoch(v: str) -> float:
    try:
        return dt.datetime.fromisoformat((v or "")[:19]).timestamp()
    except ValueError:
        return time.time()


def _upsert(con, tabela: str, base44_id: str, campos: dict) -> tuple[int, bool]:
    row = con.execute(f"SELECT id FROM {tabela} WHERE base44_id=?", (base44_id,)).fetchone()
    if row:
        con.execute(f"UPDATE {tabela} SET {', '.join(f'{k}=?' for k in campos)} WHERE id=?",
                    (*campos.values(), row["id"]))
        return row["id"], False
    campos = {**campos, "base44_id": base44_id}
    cur = con.execute(f"INSERT INTO {tabela}({', '.join(campos)}) "
                      f"VALUES({', '.join('?' * len(campos))})", tuple(campos.values()))
    return cur.lastrowid, True


# ── importação ──────────────────────────────────────────────────────────────
def importar(pasta: Path) -> dict:
    rel = Counter()
    clientes_csv = _ler(pasta, "Cliente")
    mapa: dict[str, int] = {}
    with store.conexao() as con:
        for r in clientes_csv:
            nome = _nome(r["nome_empresa"])
            if not nome:
                continue
            notas = (r.get("observacoes") or "").strip()
            docs = json.loads(r.get("documentos_urls") or "[]")
            if docs:
                notas = (notas + "\nDocumentos: " + " ".join(docs)).strip()
            status = r.get("status") or "Ativo"
            if status not in dados.STATUS_CLIENTE:
                status = "Ativo"
            campos = {"nome": nome, "chave": store.chave(nome), "contato": r.get("contato", ""),
                      "email": r.get("email", ""), "endereco": r.get("endereco", ""),
                      "status": status, "notas": notas, "atualizado_em": time.time()}
            # Um cliente com o mesmo nome criado antes pela voz/Claude é o mesmo cliente.
            existente = con.execute("SELECT id FROM clientes WHERE base44_id=? OR "
                                    "(base44_id IS NULL AND chave=?)",
                                    (r["id"], campos["chave"])).fetchone()
            if existente:
                con.execute(f"UPDATE clientes SET {', '.join(f'{k}=?' for k in campos)}, "
                            "base44_id=? WHERE id=?", (*campos.values(), r["id"], existente["id"]))
                mapa[r["id"]] = existente["id"]
                rel["clientes_atualizados"] += 1
            else:
                cur = con.execute(
                    "INSERT INTO clientes(nome, chave, contato, email, endereco, status, notas,"
                    " atualizado_em, base44_id, dados, criado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (*campos.values(), r["id"], "{}", _epoch(r.get("created_date"))))
                mapa[r["id"]] = cur.lastrowid
                rel["clientes_novos"] += 1

        def cliente(cid: str, nome: str):
            if cid in mapa:
                return mapa[cid]
            if _nome(nome):
                row = con.execute("SELECT id FROM clientes WHERE chave=?",
                                  (store.chave(_nome(nome)),)).fetchone()
                return row["id"] if row else None
            return None

        for r in _ler(pasta, "Receita"):
            recebido = r.get("recebido") == "true"
            _, novo = _upsert(con, "receitas", r["id"], {
                "cliente_id": cliente(r.get("cliente_id"), r.get("cliente_nome")),
                "descricao": (r.get("descricao_servico") or "").strip(),
                "valor_centavos": dados.centavos(r.get("valor") or 0),
                "vencimento": (r.get("data_vencimento") or "")[:10],
                "recebido": int(recebido),
                "data_recebimento": (r.get("data_recebimento") or "")[:10] if recebido else "",
                "mes_referencia": (r.get("mes_referencia") or r.get("data_vencimento") or "")[:7],
                "criado_em": _epoch(r.get("created_date"))})
            rel["receitas_novas" if novo else "receitas_atualizadas"] += 1

        for r in _ler(pasta, "Despesa"):
            pago = r.get("pago") == "true"
            _, novo = _upsert(con, "despesas", r["id"], {
                "descricao": (r.get("custo") or "").strip() or "Despesa",
                "categoria": (r.get("categoria") or "Outros").strip() or "Outros",
                "valor_centavos": dados.centavos(r.get("valor") or 0),
                "vencimento": (r.get("data_vencimento") or "")[:10],
                "pago": int(pago),
                "data_pagamento": (r.get("data_pagamento") or "")[:10] if pago else "",
                "mes_referencia": (r.get("mes_referencia") or r.get("data_vencimento") or "")[:7],
                "criado_em": _epoch(r.get("created_date"))})
            rel["despesas_novas" if novo else "despesas_atualizadas"] += 1

        tarefas_mapa: dict[str, int] = {}
        for r in _ler(pasta, "Tarefa"):
            descricao, acessos = separar_acessos(r.get("descricao") or "")
            comentarios = []
            for c in json.loads(r.get("comentarios") or "[]"):
                texto, ac = separar_acessos(c.get("texto") or "")
                if ac:
                    acessos = (acessos + f"\n\n(comentário de {c.get('data', '')[:10]})\n{ac}").strip()
                comentarios.append({"autor": c.get("autor_nome", ""), "texto": texto,
                                    "data": c.get("data", "")})
            arquivos = json.loads(r.get("arquivos_urls") or "[]")
            if arquivos:
                descricao = (descricao + "\n\nArquivos: " + " ".join(arquivos)).strip()
            status = r.get("status") or "A Fazer"
            if status not in dados.STATUS_TAREFA:
                status = "A Fazer"
            prioridade = r.get("prioridade") or "Média"
            if prioridade not in dados.PRIORIDADES:
                prioridade = "Média"
            try:
                horas = float(r.get("horas_estimadas") or 0)
            except ValueError:
                horas = 0.0
            tid, novo = _upsert(con, "tarefas", r["id"], {
                "titulo": (r.get("titulo") or "").strip() or "Sem título",
                "descricao": descricao, "acessos": acessos,
                "cliente_id": cliente(r.get("cliente_id"), r.get("cliente_nome")),
                "status": status, "prioridade": prioridade,
                "data_entrega": (r.get("data_entrega") or "")[:10],
                "horas_estimadas": horas,
                "comentarios": json.dumps(comentarios, ensure_ascii=False),
                "concluida_em": (r.get("updated_date") or "")[:10] if status == "Concluída" else "",
                "criado_em": _epoch(r.get("created_date")),
                "atualizado_em": _epoch(r.get("updated_date"))})
            tarefas_mapa[r["id"]] = tid
            rel["tarefas_novas" if novo else "tarefas_atualizadas"] += 1
            if acessos:
                rel["tarefas_com_acessos_protegidos"] += 1

        for r in _ler(pasta, "Subtarefa"):
            tid = tarefas_mapa.get(r.get("tarefa_id")) or (con.execute(
                "SELECT id FROM tarefas WHERE base44_id=?", (r.get("tarefa_id"),)).fetchone() or [None])[0]
            if not tid:
                continue
            try:
                ordem = int(float(r.get("ordem") or 0))
            except ValueError:
                ordem = 0
            _upsert(con, "subtarefas", r["id"], {
                "tarefa_id": tid, "titulo": (r.get("titulo") or "").strip(),
                "concluida": int(r.get("concluida") == "true"), "ordem": ordem})
            rel["subtarefas"] += 1

        for r in _ler(pasta, "Oportunidade"):
            etapa = r.get("etapa") or r.get("status") or "Lead"
            if etapa not in dados.ETAPAS:
                etapa = "Lead"
            _, novo = _upsert(con, "oportunidades", r["id"], {
                "titulo": (r.get("titulo") or r.get("nome") or "Oportunidade").strip(),
                "cliente_id": cliente(r.get("cliente_id"), r.get("cliente_nome")),
                "contato": r.get("contato", ""), "servico": r.get("servico", ""),
                "valor_centavos": dados.centavos(r.get("valor") or 0), "etapa": etapa,
                "notas": r.get("observacoes") or r.get("descricao") or "",
                "previsao": (r.get("data_previsao") or "")[:10],
                "criado_em": _epoch(r.get("created_date")),
                "atualizado_em": _epoch(r.get("updated_date"))})
            rel["oportunidades"] += 1
    return dict(rel)


# ── pastas do Drive → marcas ────────────────────────────────────────────────
_PREFIXO = re.compile(r"^\s*\d+\s*-\s*")


def _dono_por_nome(chave_marca: str, clientes: list[tuple[int, str]]) -> int | None:
    for cid, ch in clientes:
        if ch == chave_marca:
            return cid
    for cid, ch in clientes:
        menor, maior = sorted((ch, chave_marca), key=len)
        # Palavra inteira: "v4" casa com "v4 company", mas "ana" não casa com "banana".
        if len(menor) >= 2 and re.search(rf"\b{re.escape(menor)}\b", maior):
            return cid
    return None


def _dono_pelas_tarefas(con, chave_marca: str) -> int | None:
    """Quem pagou pelos trabalhos dessa marca: o cliente mais frequente nas
    tarefas e receitas que citam o nome dela (ex.: 'Vídeo - Padaria Sol' → Agência Norte)."""
    if len(chave_marca) < 4:
        return None
    # O nome inteiro primeiro; depois a primeira palavra, se for longa e não
    # genérica ("Congresso X & Y" → tarefas "Congresso 2026", "Banners - Congresso").
    tentativas = [chave_marca]
    primeira = chave_marca.split()[0]
    if primeira != chave_marca and len(primeira) >= 4 and primeira not in _GENERICAS:
        tentativas.append(primeira)
    for termo in tentativas:
        votos = Counter()
        padrao = re.compile(rf"\b{re.escape(termo)}\b")
        for tabela, col in (("tarefas", "titulo"), ("receitas", "descricao")):
            for r in con.execute(f"SELECT cliente_id, {col} t FROM {tabela} "
                                 "WHERE cliente_id IS NOT NULL"):
                if padrao.search(store.chave(r["t"])):
                    votos[r["cliente_id"]] += 1
        if votos:
            return votos.most_common(1)[0][0]
    return None


_GENERICAS = {"casa", "dra.", "academia", "instituto", "igreja", "comunidade",
              "distribuidora", "farmacia", "clinica", "studio", "grupo", "loja"}


def importar_drive(raiz: Path) -> dict:
    rel = Counter()
    pastas = sorted(p for p in raiz.iterdir() if p.is_dir())
    with store.conexao() as con:
        clientes = [(r["id"], r["chave"]) for r in con.execute("SELECT id, chave FROM clientes")]
        for p in pastas:
            nome = _PREFIXO.sub("", p.name).strip() or p.name
            ch = store.chave(nome)
            dono = _dono_por_nome(ch, clientes) or _dono_pelas_tarefas(con, ch)
            atual = con.execute("SELECT id, cliente_id FROM marcas WHERE chave=?", (ch,)).fetchone()
            if atual:
                # Não desfaz uma ligação que você corrigiu na central.
                con.execute("UPDATE marcas SET pasta=?, cliente_id=COALESCE(cliente_id, ?) "
                            "WHERE id=?", (str(p), dono, atual["id"]))
                rel["marcas_atualizadas"] += 1
            else:
                con.execute("INSERT INTO marcas(nome, chave, pasta, cliente_id) VALUES(?,?,?,?)",
                            (nome, ch, str(p), dono))
                rel["marcas_novas"] += 1
            rel["ligadas_a_cliente" if dono else "sem_cliente"] += 1
    return dict(rel)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Importa o Base44 e as pastas do Drive para a central.")
    ap.add_argument("pasta", nargs="?", help="pasta com os CSVs exportados do Base44")
    ap.add_argument("--drive", help="pasta de clientes no Drive (uma subpasta por marca)")
    ap.add_argument("--apagar-csv", action="store_true",
                    help="apaga os CSVs depois de importar (eles têm senhas em texto puro)")
    a = ap.parse_args(argv)
    if not a.pasta and not a.drive:
        ap.error("informe a pasta dos CSVs e/ou --drive")
    if a.pasta:
        pasta = Path(a.pasta)
        if not any(pasta.glob("*_export*.csv")):
            print(f"Nenhum CSV do Base44 em {pasta}")
            return 1
        print("Base44:", json.dumps(importar(pasta), ensure_ascii=False))
        if a.apagar_csv:
            for arq in pasta.glob("*_export*.csv"):
                arq.unlink()
            print("CSVs apagados.")
    if a.drive:
        print("Drive:", json.dumps(importar_drive(Path(a.drive)), ensure_ascii=False))
    print(f"Banco: {store.caminho_banco()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

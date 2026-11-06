"""Rotina diária da HAIZEN: resumo da manhã, backup do banco, cobranças e o
relatório mensal de tráfego de cada cliente.

Nada aqui gasta o Claude, menos o relatório mensal (uma leitura do Meta Ads por
cliente, uma vez por mês). Nenhuma mensagem sai para um cliente sem o seu OK
na tela: o resumo vai só para o seu próprio WhatsApp.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from haizen import store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cobrancas (
    id INTEGER PRIMARY KEY,
    receita_id INTEGER NOT NULL,
    etapa TEXT NOT NULL,                     -- antes | dia | atraso
    cliente_id INTEGER,
    contato TEXT NOT NULL DEFAULT '',
    texto TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposta', -- proposta | enviada | descartada | falhou
    erro TEXT NOT NULL DEFAULT '',
    criado_em REAL NOT NULL,
    atualizado_em REAL NOT NULL,
    UNIQUE(receita_id, etapa)
);
CREATE TABLE IF NOT EXISTS relatorios_mensais (
    id INTEGER PRIMARY KEY,
    conta_id TEXT NOT NULL,
    cliente_id INTEGER,
    mes TEXT NOT NULL,                       -- AAAA-MM (o mês relatado)
    status TEXT NOT NULL DEFAULT 'gerando',  -- gerando | pronto | aprovado | enviado | erro
    dados TEXT NOT NULL DEFAULT '{}',
    arquivo TEXT NOT NULL DEFAULT '',
    mensagem TEXT NOT NULL DEFAULT '',
    erro TEXT NOT NULL DEFAULT '',
    criado_em REAL NOT NULL,
    atualizado_em REAL NOT NULL,
    UNIQUE(conta_id, mes)
);
"""


def _con():
    con = store.conexao()
    return con


def _garantir(con) -> None:
    con.executescript(_SCHEMA)


# ── configuração ────────────────────────────────────────────────────────────
def _arq_config() -> Path:
    from core.data_paths import data_dir
    return Path(data_dir()) / "rotina.json"


PADRAO = {
    "resumo_ativo": True, "resumo_horario": "08:00", "resumo_whatsapp": True, "whatsapp_contato": "",
    "backup_ativo": True, "backup_pasta": "", "backup_dias": 14,
    "cobranca_ativa": True, "cobranca_dias_antes": 2, "cobranca_dias_atraso": 3,
    "cobranca_pagamento": "", "cobranca_assinatura": "Equipe HAIZEN",
    "relatorio_ativo": True,
    "ultimo_resumo": "", "ultimo_backup": "", "ultima_cobranca": "", "ultimo_relatorio": "",
}


def config() -> dict:
    try:
        return {**PADRAO, **json.loads(_arq_config().read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(PADRAO)


def _gravar(c: dict) -> dict:
    _arq_config().parent.mkdir(parents=True, exist_ok=True)
    _arq_config().write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return c


def salvar_config(mud: dict) -> dict:
    c = config()
    for k, v in (mud or {}).items():
        if k not in PADRAO or k.startswith("ultim"):
            continue
        padrao = PADRAO[k]
        if isinstance(padrao, bool):
            v = bool(v)
        elif isinstance(padrao, int):
            v = max(0, min(90, int(v or 0)))
        else:
            v = str(v or "").strip()[:400]
        c[k] = v
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", c["resumo_horario"]):
        raise ValueError("horário no formato HH:MM, ex.: 08:00")
    return _gravar(c)


def _marcar(chave: str, valor: str) -> None:
    c = config()
    c[chave] = valor
    _gravar(c)


def contato_do_dono() -> str:
    """O seu WhatsApp: o da rotina ou, se vazio, o que você pôs na tela Tráfego."""
    c = config()
    if c["whatsapp_contato"]:
        return c["whatsapp_contato"]
    try:
        from haizen import trafego
        return trafego.config().get("whatsapp_contato") or ""
    except Exception:  # noqa: BLE001
        return ""


def _brl(centavos: int | float) -> str:
    v = f"{(centavos or 0) / 100:,.2f}"
    return "R$ " + v.replace(",", "X").replace(".", ",").replace("X", ".")


def _data_br(iso: str) -> str:
    try:
        return dt.date.fromisoformat(iso).strftime("%d/%m")
    except (ValueError, TypeError):
        return iso or ""


# ── resumo da manhã ─────────────────────────────────────────────────────────
def resumo(hoje: dt.date | None = None) -> dict:
    """Tudo o que importa hoje, em blocos (para a tela) e em texto (WhatsApp)."""
    hoje = hoje or dt.date.today()
    h = hoje.isoformat()
    blocos: dict[str, list[str] | str] = {}
    with store.conexao() as con:
        _garantir(con)
        atrasadas = con.execute(
            "SELECT t.titulo, t.data_entrega, c.nome cliente FROM tarefas t LEFT JOIN clientes c ON c.id=t.cliente_id "
            "WHERE t.status<>'Concluída' AND t.data_entrega<>'' AND t.data_entrega < ? ORDER BY t.data_entrega",
            (h,)).fetchall()
        de_hoje = con.execute(
            "SELECT t.titulo, c.nome cliente FROM tarefas t LEFT JOIN clientes c ON c.id=t.cliente_id "
            "WHERE t.status<>'Concluída' AND t.data_entrega=?", (h,)).fetchall()
        aprovar = con.execute("SELECT id, agente, titulo FROM trabalhos WHERE status='aguardando_aprovacao' "
                              "ORDER BY id").fetchall()
        perguntas = con.execute("SELECT id, agente, titulo FROM trabalhos WHERE status='aguardando_resposta'").fetchall()
        erros = con.execute("SELECT id, agente, titulo FROM trabalhos WHERE status='erro' AND atualizado_em > ?",
                            (time.time() - 3 * 86400,)).fetchall()
        receber_hoje = con.execute(
            "SELECT r.descricao, r.valor_centavos, c.nome cliente FROM receitas r LEFT JOIN clientes c ON c.id=r.cliente_id "
            "WHERE r.recebido=0 AND r.vencimento=?", (h,)).fetchall()
        vencidas = con.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(valor_centavos),0) v FROM receitas WHERE recebido=0 AND vencimento<>'' "
            "AND vencimento < ?", (h,)).fetchone()
        pagar_hoje = con.execute("SELECT descricao, valor_centavos FROM despesas WHERE pago=0 AND vencimento=?",
                                 (h,)).fetchall()
        cobr = con.execute("SELECT COUNT(*) FROM cobrancas WHERE status='proposta'").fetchone()[0]
        rel = con.execute("SELECT COUNT(*) FROM relatorios_mensais WHERE status='pronto'").fetchone()[0]

    agenda = []
    try:
        from haizen.central import agenda_web
        evs = agenda_web.listar(h, (hoje + dt.timedelta(days=1)).isoformat()).get("eventos") or []
        for e in evs:
            ini = str(e.get("inicio") or e.get("start") or "")
            hora = ini[11:16] if len(ini) > 15 else "dia todo"
            agenda.append(f"{hora} {e.get('titulo') or e.get('summary') or 'evento'}")
    except Exception:  # noqa: BLE001 - sem Google Agenda conectado: segue sem
        pass
    if agenda:
        blocos["Agenda"] = agenda
    tarefas = [f"⚠️ {r['titulo']}{' (' + r['cliente'] + ')' if r['cliente'] else ''} — venceu {_data_br(r['data_entrega'])}"
               for r in atrasadas[:6]]
    tarefas += [f"• {r['titulo']}{' (' + r['cliente'] + ')' if r['cliente'] else ''} — entrega hoje" for r in de_hoje[:6]]
    if len(atrasadas) > 6:
        tarefas.append(f"+{len(atrasadas) - 6} atrasadas")
    if tarefas:
        blocos["Tarefas"] = tarefas
    esc = []
    if aprovar:
        esc.append(f"{len(aprovar)} entrega(s) esperando sua aprovação: "
                   + ", ".join((r["titulo"] or r["agente"]) for r in aprovar[:4]))
    if perguntas:
        esc.append(f"{len(perguntas)} agente(s) com pergunta para você")
    if erros:
        esc.append(f"{len(erros)} trabalho(s) com erro nos últimos dias")
    if esc:
        blocos["Escritório"] = esc
    fin = [f"Receber hoje: {r['cliente'] or r['descricao']} {_brl(r['valor_centavos'])}" for r in receber_hoje]
    if vencidas["n"]:
        fin.append(f"Em atraso: {vencidas['n']} cobrança(s), {_brl(vencidas['v'])}")
    fin += [f"Pagar hoje: {r['descricao']} {_brl(r['valor_centavos'])}" for r in pagar_hoje]
    if cobr:
        fin.append(f"{cobr} lembrete(s) de cobrança prontos para você aprovar")
    if fin:
        blocos["Financeiro"] = fin
    traf = []
    try:
        from haizen import trafego
        texto = trafego.resumo_texto()
        if texto and not texto.startswith("Nenhuma"):
            traf = texto.splitlines()[1:]
            traf = [x for x in traf if x.strip()]
    except Exception:  # noqa: BLE001
        pass
    if rel:
        traf.append(f"{rel} relatório(s) mensal(is) prontos para aprovar")
    if traf:
        blocos["Tráfego"] = traf
    try:
        from haizen import ecommerce
        lojas_txt = ecommerce.resumo_linhas()
        if lojas_txt:
            blocos["Lojas"] = lojas_txt
    except Exception:  # noqa: BLE001
        pass
    soc = []
    try:
        from haizen import social
        for it in social.itens():
            quando = dt.datetime.fromtimestamp(it["publicar_em"]) if it.get("publicar_em") else None
            if it.get("status") == "agendado" and quando and quando.date() == hoje:
                soc.append(f"Publica hoje {quando.strftime('%H:%M')}: {it['tema']}")
            elif it.get("status") == "pronto":
                soc.append(f"Pronto para publicar: {it['tema']}")
            elif it.get("data") == h and it.get("status") == "ideia":
                soc.append(f"No calendário de hoje (ainda ideia): {it['tema']}")
    except Exception:  # noqa: BLE001
        pass
    if soc:
        blocos["Instagram"] = soc[:6]

    dias = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
    titulo = f"Bom dia! Resumo de {dias[hoje.weekday()]}, {hoje.strftime('%d/%m')}"
    linhas = [f"*{titulo}*"]
    for nome, itens in blocos.items():
        linhas += ["", f"*{nome}*", *itens]
    if not blocos:
        linhas += ["", "Nada pendente hoje. Dia livre para produzir."]
    return {"titulo": titulo, "blocos": blocos, "texto": "\n".join(linhas), "dia": h}


def enviar_resumo() -> dict:
    r = resumo()
    c = config()
    enviado = False
    contato = contato_do_dono()
    if c["resumo_whatsapp"] and contato:
        try:
            from core import whatsapp_web
            ok, _code, res = whatsapp_web.run_op({"op": "send", "recipient": contato, "text": r["texto"][:3900]},
                                                 timeout=60)
            enviado = bool(ok)
            if not ok:
                print(f"[Rotina] resumo no WhatsApp não foi: {res}")
        except Exception as e:  # noqa: BLE001
            print(f"[Rotina] resumo no WhatsApp: {e}")
    try:
        from haizen import notificar
        partes = [f"{k}: {len(v)}" for k, v in r["blocos"].items()]
        notificar.avisar("Resumo da manhã", ", ".join(partes) or "Nada pendente hoje.", "info", "#/painel")
    except Exception:  # noqa: BLE001
        pass
    return {**r, "whatsapp": enviado}


# ── backup ──────────────────────────────────────────────────────────────────
def pasta_backup() -> Path:
    c = config()
    if c["backup_pasta"]:
        return Path(c["backup_pasta"])
    try:
        from haizen.central import claude_cerebro
        raiz = claude_cerebro.raiz_clientes()
        if raiz and Path(raiz).parent.is_dir():
            return Path(raiz).parent / "JARVIS - backups"
    except Exception:  # noqa: BLE001
        pass
    from core.data_paths import data_dir
    return Path(data_dir()) / "backups"


# Configurações que valem guardar. Tokens e chaves NÃO entram no backup.
_CONFIGS = ("trafego.json", "social.json", "uso.json", "rotina.json")


def fazer_backup(hoje: dt.date | None = None) -> Path:
    """Cópia consistente do banco (mesmo com o Jarvis usando) + as configurações."""
    hoje = hoje or dt.date.today()
    destino = pasta_backup() / hoje.isoformat()
    destino.mkdir(parents=True, exist_ok=True)
    origem = store.caminho_banco()
    alvo = destino / "haizen.db"
    src = sqlite3.connect(origem, timeout=30)
    dst = sqlite3.connect(alvo)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    from core.data_paths import data_dir
    for nome in _CONFIGS:
        f = Path(data_dir()) / nome
        if f.is_file():
            shutil.copy2(f, destino / nome)
    agentes_dir = Path(data_dir()) / "conhecimento"
    if agentes_dir.is_dir():
        shutil.copytree(agentes_dir, destino / "conhecimento", dirs_exist_ok=True)
    _limpar_backups(pasta_backup(), int(config()["backup_dias"] or 14))
    _marcar("ultimo_backup", hoje.isoformat())
    return alvo


def _limpar_backups(raiz: Path, dias: int) -> None:
    pastas = sorted(p for p in raiz.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name))
    for p in pastas[:-max(1, dias)]:
        shutil.rmtree(p, ignore_errors=True)


def backups() -> list[dict]:
    raiz = pasta_backup()
    if not raiz.is_dir():
        return []
    out = []
    for p in sorted(raiz.iterdir(), reverse=True):
        db = p / "haizen.db"
        if db.is_file():
            out.append({"dia": p.name, "pasta": str(p), "tamanho": db.stat().st_size})
    return out


# ── cobranças (só saem com o seu OK) ────────────────────────────────────────
def _primeiro_nome(nome: str) -> str:
    return (nome or "").split()[0] if (nome or "").strip() else ""


def texto_cobranca(etapa: str, cliente: str, descricao: str, valor: int, vencimento: str) -> str:
    c = config()
    oi = "Oi, tudo bem?"
    servico = descricao or "nossos serviços"
    v, d = _brl(valor), _data_br(vencimento)
    pag = f"\n\n{c['cobranca_pagamento']}" if c["cobranca_pagamento"] else ""
    ass = f"\n\n{c['cobranca_assinatura']}" if c["cobranca_assinatura"] else ""
    if etapa == "antes":
        corpo = (f"{oi} Passando para lembrar que o pagamento de {servico} ({v}) vence dia {d}.{pag}\n\n"
                 "Qualquer dúvida é só me chamar.")
    elif etapa == "dia":
        corpo = f"{oi} Hoje é o vencimento de {servico} ({v}).{pag}\n\nSe já pagou, pode desconsiderar. Obrigado!"
    else:
        corpo = (f"{oi} Não identificamos ainda o pagamento de {servico} ({v}), que venceu dia {d}. "
                 f"Consegue verificar para mim?{pag}\n\nSe já pagou, me manda o comprovante que eu dou baixa. Obrigado!")
    return corpo + ass


def _contato_cliente(contato: str | None, dados: str | dict | None) -> str:
    """O WhatsApp do cliente: o campo contato (se tiver número) ou o da ficha."""
    if contato and re.search(r"\d{8,}", re.sub(r"\D", "", contato)):
        return contato.strip()
    try:
        d = dados if isinstance(dados, dict) else json.loads(dados or "{}")
    except ValueError:
        d = {}
    for k in ("whatsapp", "telefone", "celular", "contato"):
        v = str((d or {}).get(k) or "").strip()
        if v and len(re.sub(r"\D", "", v)) >= 8:
            return v
    return (contato or "").strip()


def gerar_cobrancas(hoje: dt.date | None = None) -> int:
    """Prepara os lembretes do dia (2 dias antes, no dia, 3 dias depois). Não envia nada."""
    hoje = hoje or dt.date.today()
    c = config()
    antes = (hoje + dt.timedelta(days=int(c["cobranca_dias_antes"]))).isoformat()
    atraso = (hoje - dt.timedelta(days=int(c["cobranca_dias_atraso"]))).isoformat()
    novas = 0
    agora = time.time()
    with store.conexao() as con:
        _garantir(con)
        rows = con.execute(
            "SELECT r.*, c.nome cliente, c.contato ccontato, c.dados cdados FROM receitas r "
            "LEFT JOIN clientes c ON c.id=r.cliente_id "
            "WHERE r.recebido=0 AND r.vencimento IN (?,?,?)", (antes, hoje.isoformat(), atraso)).fetchall()
        for r in rows:
            etapa = {antes: "antes", hoje.isoformat(): "dia", atraso: "atraso"}[r["vencimento"]]
            contato = _contato_cliente(r["ccontato"], r["cdados"])
            texto = texto_cobranca(etapa, r["cliente"] or "", r["descricao"], r["valor_centavos"], r["vencimento"])
            cur = con.execute("INSERT OR IGNORE INTO cobrancas(receita_id, etapa, cliente_id, contato, texto, criado_em,"
                              " atualizado_em) VALUES(?,?,?,?,?,?,?)",
                              (r["id"], etapa, r["cliente_id"], contato, texto, agora, agora))
            novas += cur.rowcount
        # Recebeu antes de você enviar: o lembrete some.
        con.execute("UPDATE cobrancas SET status='descartada', atualizado_em=? WHERE status='proposta' AND receita_id IN "
                    "(SELECT id FROM receitas WHERE recebido=1)", (agora,))
    _marcar("ultima_cobranca", hoje.isoformat())
    return novas


def cobrancas(status: str | tuple = ("proposta", "falhou")) -> list[dict]:
    st = (status,) if isinstance(status, str) else tuple(status)
    with store.conexao() as con:
        _garantir(con)
        rows = con.execute(
            f"SELECT b.*, c.nome cliente, r.valor_centavos, r.vencimento, r.descricao FROM cobrancas b "
            f"LEFT JOIN clientes c ON c.id=b.cliente_id LEFT JOIN receitas r ON r.id=b.receita_id "
            f"WHERE b.status IN ({','.join('?' * len(st))}) ORDER BY b.id DESC LIMIT 100", st).fetchall()
    return [{**dict(r), "valor": (r["valor_centavos"] or 0) / 100} for r in rows]


def _cobranca(bid: int) -> dict:
    with store.conexao() as con:
        _garantir(con)
        r = con.execute("SELECT * FROM cobrancas WHERE id=?", (int(bid),)).fetchone()
    if r is None:
        raise KeyError("lembrete não encontrado")
    return dict(r)


def _mudar_cobranca(bid: int, **campos) -> dict:
    campos["atualizado_em"] = time.time()
    with store.conexao() as con:
        con.execute(f"UPDATE cobrancas SET {', '.join(k + '=?' for k in campos)} WHERE id=?",
                    (*campos.values(), int(bid)))
    return _cobranca(bid)


def enviar_cobranca(bid: int, texto: str | None = None, contato: str | None = None) -> dict:
    """Envia UM lembrete, depois do seu clique em Enviar (com o texto que você revisou)."""
    b = _cobranca(bid)
    if b["status"] not in ("proposta", "falhou"):
        raise ValueError("este lembrete já foi enviado ou descartado")
    texto = (texto if texto is not None else b["texto"]).strip()
    contato = (contato if contato is not None else b["contato"]).strip()
    if not contato:
        raise ValueError("o cliente não tem WhatsApp no cadastro: preencha o contato")
    if not texto:
        raise ValueError("a mensagem está vazia")
    from core import whatsapp_web
    ok, _code, res = whatsapp_web.run_op({"op": "send", "recipient": contato, "text": texto}, timeout=60)
    if not ok:
        return _mudar_cobranca(bid, status="falhou", erro=str(res)[:300], texto=texto, contato=contato)
    return _mudar_cobranca(bid, status="enviada", erro="", texto=texto, contato=contato)


def descartar_cobranca(bid: int) -> dict:
    return _mudar_cobranca(bid, status="descartada")


# ── relatório mensal de tráfego ─────────────────────────────────────────────
def _mes_anterior(hoje: dt.date) -> str:
    return (hoje.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")


def relatorios(status: str | tuple = ("gerando", "pronto", "aprovado", "erro")) -> list[dict]:
    st = (status,) if isinstance(status, str) else tuple(status)
    with store.conexao() as con:
        _garantir(con)
        rows = con.execute(
            f"SELECT m.*, c.nome cliente, t.nome conta FROM relatorios_mensais m LEFT JOIN clientes c ON c.id=m.cliente_id "
            f"LEFT JOIN trafego_contas t ON t.id=m.conta_id WHERE m.status IN ({','.join('?' * len(st))}) "
            f"ORDER BY m.id DESC LIMIT 60", st).fetchall()
    return [{**dict(r), "dados": json.loads(r["dados"] or "{}")} for r in rows]


def relatorio(rid: int) -> dict:
    for r in relatorios(("gerando", "pronto", "aprovado", "enviado", "erro")):
        if r["id"] == int(rid):
            return r
    raise KeyError("relatório não encontrado")


def _mudar_relatorio(rid: int, **campos) -> None:
    campos["atualizado_em"] = time.time()
    with store.conexao() as con:
        con.execute(f"UPDATE relatorios_mensais SET {', '.join(k + '=?' for k in campos)} WHERE id=?",
                    (*campos.values(), int(rid)))


def gerar_relatorio(conta_id: str, mes: str) -> dict:
    """Lê o mês no Meta Ads (Claude, só leitura) e monta o PDF com a cara da HAIZEN."""
    from haizen import trafego
    from haizen.trafego import mensal
    c = trafego.conta(conta_id)
    agora = time.time()
    with store.conexao() as con:
        _garantir(con)
        con.execute("INSERT OR IGNORE INTO relatorios_mensais(conta_id, cliente_id, mes, criado_em, atualizado_em) "
                    "VALUES(?,?,?,?,?)", (conta_id, c.get("cliente_id"), mes, agora, agora))
        rid = con.execute("SELECT id FROM relatorios_mensais WHERE conta_id=? AND mes=?", (conta_id, mes)).fetchone()[0]
    _mudar_relatorio(rid, status="gerando", erro="")
    try:
        dados = mensal.coletar(c, mes)
        pdf = mensal.montar_pdf(c, mes, dados, _pasta_relatorios() / f"{mes} - {_seguro(c.get('cliente_nome') or c['nome'])}.pdf")
        _mudar_relatorio(rid, status="pronto", dados=json.dumps(dados, ensure_ascii=False)[:60000], arquivo=str(pdf),
                         mensagem=mensal.mensagem_cliente(c, mes, dados))
    except Exception as e:  # noqa: BLE001
        _mudar_relatorio(rid, status="erro", erro=str(e)[:600])
    return relatorio(rid)


def _seguro(nome: str) -> str:
    return " ".join(re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", nome or "").split())[:60] or "cliente"


def _pasta_relatorios() -> Path:
    p = store.pasta_entregas().parent / "Relatorios mensais"
    p.mkdir(parents=True, exist_ok=True)
    return p


def gerar_relatorios_do_mes(hoje: dt.date | None = None) -> int:
    from haizen import executor, trafego
    hoje = hoje or dt.date.today()
    mes = _mes_anterior(hoje)
    if not executor.claude_disponivel() or not trafego.config().get("conectado_em"):
        return 0
    feitos = 0
    with store.conexao() as con:
        _garantir(con)
        prontos = {r[0] for r in con.execute("SELECT conta_id FROM relatorios_mensais WHERE mes=? AND status<>'erro'",
                                              (mes,))}
    for c in trafego.contas_lista():
        if c["ativo"] and c["id"] not in prontos:
            gerar_relatorio(c["id"], mes)
            feitos += 1
    _marcar("ultimo_relatorio", hoje.strftime("%Y-%m"))
    return feitos


def aprovar_relatorio(rid: int) -> dict:
    """Aprovado: o PDF vai para a pasta do cliente (Relatórios de tráfego)."""
    r = relatorio(rid)
    if r["status"] not in ("pronto", "aprovado"):
        raise ValueError("o relatório ainda não está pronto")
    pdf = Path(r["arquivo"])
    destino = pdf
    marca = store.pasta_da_marca(r.get("cliente_id"), "") if r.get("cliente_id") else ""
    if marca and Path(marca).is_dir() and pdf.is_file():
        d = Path(marca) / "Relatórios de tráfego"
        d.mkdir(exist_ok=True)
        destino = d / pdf.name
        shutil.copy2(pdf, destino)
    _mudar_relatorio(rid, status="aprovado", arquivo=str(destino))
    return relatorio(rid)


def enviar_relatorio(rid: int, texto: str, contato: str = "") -> dict:
    """Manda o resumo do relatório para o cliente (você anexa o PDF na conversa)."""
    r = relatorio(rid)
    if r["status"] != "aprovado":
        raise ValueError("aprove o relatório antes de enviar")
    cli = store.cliente_por_id(r.get("cliente_id")) if r.get("cliente_id") else None
    contato = (contato or _contato_cliente((cli or {}).get("contato"), (cli or {}).get("dados"))).strip()
    if not contato:
        raise ValueError("o cliente não tem WhatsApp no cadastro")
    from core import whatsapp_web
    ok, _code, res = whatsapp_web.run_op({"op": "send", "recipient": contato, "text": texto.strip()}, timeout=60)
    if not ok:
        raise RuntimeError(f"o WhatsApp não enviou: {res}")
    _mudar_relatorio(rid, status="enviado", mensagem=texto.strip())
    return relatorio(rid)


# ── agenda ──────────────────────────────────────────────────────────────────
def _hora_ok(agora: dt.datetime, hhmm: str) -> bool:
    h, m = map(int, hhmm.split(":"))
    return (agora.hour, agora.minute) >= (h, m)


def tarefas_devidas(agora: dt.datetime | None = None) -> list[str]:
    """O que já deveria ter rodado hoje e ainda não rodou."""
    agora = agora or dt.datetime.now()
    c = config()
    hoje = agora.date().isoformat()
    devidas = []
    if c["backup_ativo"] and c["ultimo_backup"] != hoje and agora.hour >= 3:
        devidas.append("backup")
    if c["cobranca_ativa"] and c["ultima_cobranca"] != hoje and _hora_ok(agora, c["resumo_horario"]):
        devidas.append("cobranca")
    if (c["relatorio_ativo"] and agora.day <= 5 and c["ultimo_relatorio"] != agora.strftime("%Y-%m")
            and _hora_ok(agora, c["resumo_horario"])):
        devidas.append("relatorio")
    if c["resumo_ativo"] and c["ultimo_resumo"] != hoje and _hora_ok(agora, c["resumo_horario"]):
        devidas.append("resumo")
    return devidas


def _trafego_ocupado() -> bool:
    try:
        from haizen import ecommerce, trafego
        return bool(trafego.ESTADO.get("fazendo") or ecommerce.ESTADO.get("fazendo"))
    except Exception:  # noqa: BLE001
        return False


def rodar_devidas(agora: dt.datetime | None = None) -> list[str]:
    agora = agora or dt.datetime.now()
    feitas = []
    for t in tarefas_devidas(agora):
        try:
            if t == "backup":
                fazer_backup(agora.date())
            elif t == "cobranca":
                gerar_cobrancas(agora.date())
            elif t == "relatorio":
                threading.Thread(target=gerar_relatorios_do_mes, args=(agora.date(),), daemon=True,
                                 name="rotina-relatorios").start()
                _marcar("ultimo_relatorio", agora.strftime("%Y-%m"))
            elif t == "resumo":
                # Espera a análise do tráfego da manhã terminar (até 1 hora) para entrar no resumo.
                if _trafego_ocupado() and not _hora_ok(agora, _mais(config()["resumo_horario"], 60)):
                    continue
                _marcar("ultimo_resumo", agora.date().isoformat())
                enviar_resumo()
            feitas.append(t)
        except Exception as e:  # noqa: BLE001
            print(f"[Rotina] {t}: {e}")
            if t == "backup":
                _marcar("ultimo_backup", agora.date().isoformat())     # tenta amanhã; não fica em laço
    return feitas


def _mais(hhmm: str, minutos: int) -> str:
    h, m = map(int, hhmm.split(":"))
    t = min(23 * 60 + 59, h * 60 + m + minutos)
    return f"{t // 60:02d}:{t % 60:02d}"


_AGENDA = {"thread": None}


def iniciar_agenda() -> None:
    if os.environ.get("HAIZEN_ROTINA_AGENDA", "1") == "0":
        return
    if _AGENDA["thread"] and _AGENDA["thread"].is_alive():
        return

    def _laco():
        time.sleep(20)
        while True:
            try:
                rodar_devidas()
            except Exception as e:  # noqa: BLE001
                print(f"[Rotina] {e}")
            time.sleep(60)
    _AGENDA["thread"] = threading.Thread(target=_laco, daemon=True, name="rotina-agenda")
    _AGENDA["thread"].start()


def painel() -> dict:
    c = config()
    return {"config": {k: v for k, v in c.items()}, "contato": contato_do_dono(), "resumo": resumo(),
            "cobrancas": cobrancas(), "relatorios": relatorios(), "backups": backups()[:5],
            "pasta_backup": str(pasta_backup())}

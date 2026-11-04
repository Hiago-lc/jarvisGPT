"""Gestor de tráfego da HAIZEN: análise diária do Meta Ads e otimizações com aprovação.

O Claude (Claude Code da assinatura) lê as contas pelo conector oficial da Meta
(Meta Ads MCP, https://mcp.facebook.com/ads, cadastrado no Claude Code como
"meta-ads" por conectar-meta.bat). Na análise ele só tem as ferramentas de
LEITURA; as otimizações viram propostas na tela Tráfego. Só depois que você
aprova, uma segunda chamada do Claude, com as ferramentas de alteração, aplica
exatamente aquela mudança e confere.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time
from pathlib import Path

from haizen import executor, store

SERVIDOR = "meta-ads"
PREFIXO = f"mcp__{SERVIDOR}__"
PLAYBOOK = Path(__file__).resolve().parent / "playbook.md"
TIMEOUT = int(os.environ.get("HAIZEN_TRAFEGO_TIMEOUT", "900"))

# Ferramentas do conector oficial (documentação da Meta, jul/2026).
LEITURA = ("ads_get_ad_accounts", "ads_get_field_context", "ads_get_ad_entities", "ads_get_creatives",
           "ads_get_creative_ads", "ads_get_ad_preview", "ads_get_ad_account_pages",
           "ads_get_ad_account_custom_audiences", "ads_get_custom_audience", "ads_get_custom_audience_adsets",
           "ads_get_opportunity_score", "ads_insights_advertiser_context", "ads_insights_anomaly_signal",
           "ads_insights_auction_ranking_benchmarks", "ads_insights_industry_benchmark",
           "ads_insights_performance_trend", "ads_library_search")
ESCRITA = ("ads_update_entity", "ads_activate_entity")       # o que uma ação aprovada pode usar
_ESCREVE = re.compile(r"create|update|delete|activate|boost|upload|publish|archive|remove|set_|edit|pause", re.I)
_LE = re.compile(r"^ads_(get|insights|library|search|list|read|help)", re.I)

TIPOS = ("pausar", "reativar", "orcamento", "criativo", "manual")
ESTADO = {"fazendo": "", "desde": 0.0, "erro": "", "progresso": ""}
_TRAVA = threading.Lock()


# ── configuração ────────────────────────────────────────────────────────────
def _arq_config() -> Path:
    from core.data_paths import data_dir
    return Path(data_dir()) / "trafego.json"


PADRAO = {"horario": "07:30", "whatsapp_ativo": False, "whatsapp_contato": "", "ferramentas": [],
          "conectado_em": 0, "ultima_rodada": "", "aviso_conexao": ""}


def config() -> dict:
    try:
        return {**PADRAO, **json.loads(_arq_config().read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(PADRAO)


def salvar_config(mudancas: dict) -> dict:
    c = config()
    for k in ("horario", "whatsapp_ativo", "whatsapp_contato"):
        if k in mudancas:
            c[k] = mudancas[k]
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(c["horario"])):
        raise ValueError("horário no formato HH:MM, ex.: 07:30")
    c["whatsapp_ativo"] = bool(c["whatsapp_ativo"])
    c["whatsapp_contato"] = str(c["whatsapp_contato"] or "").strip()[:80]
    return _gravar(c)


def _gravar(c: dict) -> dict:
    _arq_config().write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return c


def ferramentas_leitura() -> list[str]:
    """Nomes completos (mcp__meta-ads__...) das ferramentas de leitura."""
    achadas = [n for n in config().get("ferramentas") or [] if _LE.match(n) and not _ESCREVE.search(n)]
    return [PREFIXO + n for n in dict.fromkeys([*LEITURA, *achadas])]


def ferramentas_escrita() -> list[str]:
    return [PREFIXO + n for n in ESCRITA]


# ── o Claude com o conector da Meta ────────────────────────────────────────
def _pasta() -> Path:
    from core.data_paths import data_dir
    p = Path(data_dir()) / "jarvis-claude" / "trafego"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _claude(prompt: str, ferramentas: list[str], instrucao: str, referencia: str = "") -> str:
    from haizen import uso
    modelo = uso.modelo("trafego")
    args = ["-p", instrucao, "--output-format", "json", "--permission-mode", "dontAsk",
            "--allowedTools", ",".join(ferramentas), *(["--model", modelo] if modelo else [])]
    try:
        return executor._rodar_claude(args, prompt, _pasta(), TIMEOUT, origem="trafego", referencia=referencia)
    except RuntimeError as e:
        if _sem_conexao(str(e)):
            raise ConnectionError(AVISO_CONEXAO) from None
        raise


AVISO_CONEXAO = ("O Jarvis não conseguiu entrar no Meta Ads. Dê dois cliques em conectar-meta.bat (em C:\\JARVIS), "
                 "faça o login no Facebook e volte aqui. O acesso da Meta vence a cada ~60 dias.")


def _sem_conexao(texto: str) -> bool:
    t = (texto or "").lower()
    return any(s in t for s in ("needs authentication", "not authenticated", "unauthorized", "401",
                                "oauth", "invalid oauth", "session has expired", "error validating access token",
                                "meta-ads", "sem_conexao_meta"))


def _json(texto: str) -> dict:
    bloco = re.search(r"```(?:json)?\s*(\{.*\})\s*```", texto or "", re.S)
    bruto = bloco.group(1) if bloco else (texto or "")[(texto or "").find("{"):(texto or "").rfind("}") + 1]
    try:
        return json.loads(bruto)
    except ValueError:
        raise ValueError("o Claude não devolveu o JSON combinado") from None


def descobrir() -> dict:
    """Confere a conexão, anota as ferramentas e traz as contas de anúncio."""
    prompt = (
        "Você está conectado ao Meta Ads pelo servidor MCP 'meta-ads'.\n"
        "1. Liste o nome de TODAS as ferramentas mcp__meta-ads__ que você tem (sem o prefixo).\n"
        "2. Chame ads_get_ad_accounts e traga todas as contas de anúncio que o usuário acessa.\n"
        "Se as ferramentas meta-ads não existirem ou pedirem autenticação, responda só "
        '{"erro": "SEM_CONEXAO_META", "detalhe": "..."}.\n'
        "Responda SÓ com JSON: {\"ferramentas\": [\"ads_...\"], \"contas\": [{\"id\": \"act_...\", "
        "\"nome\": \"...\", \"negocio\": \"nome do business ou vazio\", \"moeda\": \"BRL\", "
        "\"status\": \"ativa|desativada|...\"}]}")
    r = _json(_claude(prompt, [PREFIXO + "ads_get_ad_accounts"], "Siga a entrada. Responda só com o JSON pedido."))
    if r.get("erro"):
        raise ConnectionError(AVISO_CONEXAO + (f" ({r.get('detalhe')})" if r.get("detalhe") else ""))
    c = config()
    c["ferramentas"] = sorted({str(n).removeprefix(PREFIXO) for n in r.get("ferramentas") or []})
    c["conectado_em"], c["aviso_conexao"] = time.time(), ""
    _gravar(c)
    return {"contas": sincronizar_contas(r.get("contas") or []), "ferramentas": c["ferramentas"]}


def sincronizar_contas(contas: list[dict]) -> list[dict]:
    agora = time.time()
    with store.conexao() as con:
        for c in contas:
            cid = str(c.get("id") or "").strip()
            if not cid:
                continue
            cid = cid if cid.startswith("act_") else f"act_{cid}"
            con.execute(
                "INSERT INTO trafego_contas(id, nome, negocio, moeda, status_meta, atualizado_em) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET nome=excluded.nome, negocio=excluded.negocio, moeda=excluded.moeda, "
                "status_meta=excluded.status_meta, atualizado_em=excluded.atualizado_em",
                (cid, str(c.get("nome") or cid)[:120], str(c.get("negocio") or "")[:120],
                 str(c.get("moeda") or "BRL")[:8], str(c.get("status") or "")[:40], agora))
    _ligar_clientes()
    return contas_lista()


def _ligar_clientes() -> None:
    """Conta sem cliente: liga ao cliente de nome igual ou contido no nome da conta."""
    clientes = [(store.chave(c["nome"]), c["id"]) for c in _clientes()]
    with store.conexao() as con:
        for r in con.execute("SELECT id, nome, negocio FROM trafego_contas WHERE cliente_id IS NULL").fetchall():
            alvo = f" {store.chave(r['nome'])} {store.chave(r['negocio'])} "
            achados = [cid for k, cid in clientes if len(k) >= 3 and f" {k} " in alvo]
            if len(set(achados)) == 1:
                con.execute("UPDATE trafego_contas SET cliente_id=? WHERE id=?", (achados[0], r["id"]))


def _clientes() -> list[dict]:
    from haizen.central import dados
    return dados.listar("clientes")


# ── contas ──────────────────────────────────────────────────────────────────
def contas_lista() -> list[dict]:
    with store.conexao() as con:
        rows = con.execute("SELECT t.*, c.nome AS cliente_nome FROM trafego_contas t "
                           "LEFT JOIN clientes c ON c.id = t.cliente_id ORDER BY t.ativo DESC, t.nome").fetchall()
    return [dict(r) for r in rows]


def conta(cid: str) -> dict:
    for c in contas_lista():
        if c["id"] == cid:
            return c
    raise KeyError(f"conta {cid} não encontrada")


def atualizar_conta(cid: str, campos: dict) -> dict:
    conta(cid)
    sets, args = [], []
    for k in ("ativo", "cliente_id", "objetivo", "meta_cpa", "meta_roas", "verba_mensal", "notas"):
        if k not in campos:
            continue
        v = campos[k]
        if k == "ativo":
            v = 1 if v else 0
        elif k in ("meta_cpa", "meta_roas", "verba_mensal"):
            v = _numero(v)
        elif k == "cliente_id":
            v = int(v) if v not in (None, "", 0, "0") else None
        else:
            v = str(v or "").strip()[:1000]
        sets.append(f"{k}=?")
        args.append(v)
    if sets:
        with store.conexao() as con:
            con.execute(f"UPDATE trafego_contas SET {', '.join(sets)}, atualizado_em=? WHERE id=?",
                        (*args, time.time(), cid))
    return conta(cid)


def _numero(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).replace("R$", "").replace(" ", "").strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", t):         # 3.000 = três mil
        t = t.replace(".", "")
    elif "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        raise ValueError(f"número inválido: {v}") from None


# ── análise diária ──────────────────────────────────────────────────────────
def _historico(cid: str) -> str:
    """O que a conta viveu: últimas análises e o destino das ações propostas."""
    with store.conexao() as con:
        an = con.execute("SELECT dia, situacao, resumo FROM trafego_analises WHERE conta_id=? AND erro='' "
                         "ORDER BY id DESC LIMIT 5", (cid,)).fetchall()
        ac = con.execute("SELECT criado_em, tipo, nivel, alvo_nome, de, para, status, resultado, motivo "
                         "FROM trafego_acoes WHERE conta_id=? ORDER BY id DESC LIMIT 15", (cid,)).fetchall()
    linhas = []
    if an:
        linhas.append("Análises anteriores:")
        linhas += [f"- {r['dia']} ({r['situacao']}): {r['resumo'][:400]}" for r in an]
    if ac:
        linhas.append("Ações recentes e o que aconteceu com elas (respeite os 3 dias entre mudanças de orçamento):")
        for r in ac:
            dia = dt.date.fromtimestamp(r["criado_em"]).isoformat()
            mud = f" de {r['de']} para {r['para']}" if r["de"] or r["para"] else ""
            linhas.append(f"- {dia}: {r['tipo']} {r['nivel']} \"{r['alvo_nome']}\"{mud} → {r['status']}"
                          f"{(': ' + r['resultado'][:150]) if r['resultado'] else ''}")
    return "\n".join(linhas) or "Primeira análise desta conta."


def prompt_analise(c: dict, hoje: dt.date | None = None) -> str:
    hoje = hoje or dt.date.today()
    def reais(v):
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    metas = []
    if c.get("objetivo"):
        metas.append(f"objetivo: {c['objetivo']}")
    if c.get("meta_cpa"):
        metas.append(f"custo por resultado alvo: {reais(c['meta_cpa'])}")
    if c.get("meta_roas"):
        metas.append(f"ROAS alvo: {c['meta_roas']:.2f}".replace(".", ","))
    if c.get("verba_mensal"):
        metas.append(f"verba mensal: {reais(c['verba_mensal'])}")
    return "\n".join([
        PLAYBOOK.read_text(encoding="utf-8"),
        "",
        "## A conta de hoje",
        f"- Conta: {c['id']} ({c['nome']}){' — cliente ' + c['cliente_nome'] if c.get('cliente_nome') else ''}",
        f"- Hoje: {hoje.isoformat()} ({['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo'][hoje.weekday()]})",
        f"- Metas: {'; '.join(metas) if metas else 'sem metas cadastradas (use a média de 30 dias da conta)'}",
        f"- Notas do dono: {c.get('notas') or '—'}",
        "",
        _historico(c["id"]),
        "",
        "## O que fazer",
        "Use ads_get_field_context antes de ads_get_ad_entities. Puxe campanhas, conjuntos e anúncios ativos "
        "(e os pausados nos últimos 7 dias) com gasto, impressões, alcance, frequência, cliques, CTR, CPC, CPM, "
        "resultados, custo por resultado e ROAS, para ontem, últimos 7 dias e os 7 anteriores. Use também os "
        "sinais de anomalia e tendência quando ajudarem. Depois analise com o playbook.",
        "",
        "Responda SÓ com um JSON neste formato:",
        "```json",
        json.dumps({
            "situacao": "bem | atencao | critico",
            "resumo": "3 a 5 frases para o dono: como está, o que mudou e por quê",
            "metricas": {"gasto_7d": 0, "resultados_7d": 0, "custo_resultado_7d": 0, "roas_7d": None,
                         "ctr_7d": 0, "cpm_7d": 0, "frequencia_7d": 0, "gasto_ontem": 0, "resultados_ontem": 0,
                         "variacao_custo_resultado_pct": 0, "nome_resultado": "compras | leads | conversas | ...",
                         "projecao_gasto_mes": 0},
            "alertas": ["frases curtas"],
            "acoes": [{"tipo": "pausar | reativar | orcamento | criativo | manual",
                       "nivel": "campanha | conjunto | anuncio | conta", "alvo_id": "id no Meta",
                       "alvo_nome": "nome", "de": "valor atual (orçamento em reais) ou status", "para": "novo valor",
                       "motivo": "números que justificam", "impacto": "o que se espera", "prioridade": "alta | media | baixa"}],
            "relatorio": "relatório em Markdown para o dono: números por campanha, diagnóstico do funil, o que testar",
        }, ensure_ascii=False, indent=1),
        "```",
    ])


def analisar_conta(cid: str) -> dict:
    c = conta(cid)
    hoje = dt.date.today()
    try:
        r = _json(_claude(prompt_analise(c, hoje), ferramentas_leitura(),
                          "Analise a conta descrita na entrada só com ferramentas de leitura. Responda só com o JSON.",
                          f"análise {c['nome']}"))
    except Exception as e:  # noqa: BLE001 - a análise com erro fica registrada
        _guardar_analise(cid, hoje, {"situacao": "erro"}, erro=str(e)[:600])
        raise
    if r.get("erro"):
        raise ConnectionError(AVISO_CONEXAO)
    return _guardar_analise(cid, hoje, r)


def _guardar_analise(cid: str, hoje: dt.date, r: dict, erro: str = "") -> dict:
    agora = time.time()
    situacao = str(r.get("situacao") or "").strip().lower()
    situacao = situacao if situacao in ("bem", "atencao", "critico", "erro") else "atencao"
    with store.conexao() as con:
        cur = con.execute(
            "INSERT INTO trafego_analises(conta_id, dia, criado_em, situacao, resumo, metricas, alertas, relatorio, erro)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (cid, hoje.isoformat(), agora, situacao, str(r.get("resumo") or "")[:3000],
             json.dumps(r.get("metricas") or {}, ensure_ascii=False), json.dumps(r.get("alertas") or [], ensure_ascii=False),
             str(r.get("relatorio") or "")[:40000], erro))
        aid = cur.lastrowid
        if not erro:
            # Propostas antigas que você não decidiu: a análise nova substitui.
            con.execute("UPDATE trafego_acoes SET status='substituida', atualizado_em=? "
                        "WHERE conta_id=? AND status='proposta'", (agora, cid))
            for a in (r.get("acoes") or [])[:5]:
                tipo = str(a.get("tipo") or "manual").strip().lower()
                tipo = tipo if tipo in TIPOS else "manual"
                con.execute(
                    "INSERT INTO trafego_acoes(conta_id, analise_id, criado_em, atualizado_em, tipo, nivel, alvo_id,"
                    " alvo_nome, de, para, motivo, impacto, prioridade) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (cid, aid, agora, agora, tipo, str(a.get("nivel") or "")[:20], str(a.get("alvo_id") or "")[:60],
                     str(a.get("alvo_nome") or "")[:200], str(a.get("de") if a.get("de") is not None else "")[:60],
                     str(a.get("para") if a.get("para") is not None else "")[:60], str(a.get("motivo") or "")[:1500],
                     str(a.get("impacto") or "")[:600],
                     str(a.get("prioridade") or "media").lower()[:10]))
    return analise(aid)


def analise(aid: int) -> dict:
    with store.conexao() as con:
        r = con.execute("SELECT * FROM trafego_analises WHERE id=?", (int(aid),)).fetchone()
    if r is None:
        raise KeyError("análise não encontrada")
    d = dict(r)
    d["metricas"], d["alertas"] = json.loads(d["metricas"] or "{}"), json.loads(d["alertas"] or "[]")
    return d


def ultimas_analises() -> dict[str, dict]:
    with store.conexao() as con:
        rows = con.execute("SELECT * FROM trafego_analises WHERE id IN "
                           "(SELECT MAX(id) FROM trafego_analises GROUP BY conta_id)").fetchall()
    out = {}
    for r in rows:
        d = dict(r)
        d["metricas"], d["alertas"] = json.loads(d["metricas"] or "{}"), json.loads(d["alertas"] or "[]")
        d.pop("relatorio", None)
        out[d["conta_id"]] = d
    return out


def rodada(contas: list[str] | None = None, avisar=print) -> dict:
    """Analisa as contas ativas (ou as pedidas), uma por vez."""
    if not _TRAVA.acquire(blocking=False):
        raise RuntimeError("já há uma análise de tráfego em andamento")
    feitas, erros = [], []
    try:
        alvo = contas or [c["id"] for c in contas_lista() if c["ativo"]]
        if not alvo:
            raise ValueError("nenhuma conta marcada para a análise diária (marque na tela Tráfego)")
        ESTADO.update(fazendo="analisando", desde=time.time(), erro="")
        for i, cid in enumerate(alvo, 1):
            ESTADO["progresso"] = f"{i}/{len(alvo)}: {cid}"
            try:
                feitas.append(analisar_conta(cid))
            except ConnectionError as e:
                c = config()
                c["aviso_conexao"] = str(e)
                _gravar(c)
                erros.append(f"{cid}: {e}")
                break                      # sem conexão, as outras também falham
            except Exception as e:  # noqa: BLE001
                erros.append(f"{cid}: {e}")
                avisar(f"[Tráfego] {cid}: {e}")
        ESTADO["erro"] = "; ".join(erros)[:800]
        pend = acoes("proposta")
        try:
            from haizen import notificar
            if pend:
                notificar.avisar("Tráfego: otimizações para aprovar",
                                 f"{len(pend)} sugestão(ões) do gestor de tráfego esperando você.", "trafego", "#/trafego")
            elif erros:
                notificar.avisar("Tráfego: a análise teve problemas", erros[0][:200], "erro", "#/trafego")
        except Exception:  # noqa: BLE001
            pass
    finally:
        ESTADO.update(fazendo="", progresso="")
        _TRAVA.release()
    return {"analises": feitas, "erros": erros}


# ── ações: aprovar, rejeitar, aplicar ──────────────────────────────────────
def acoes(status: str | tuple = ("proposta", "aplicando", "falhou"), limite: int = 60) -> list[dict]:
    estados = (status,) if isinstance(status, str) else tuple(status)
    with store.conexao() as con:
        rows = con.execute(
            f"SELECT a.*, t.nome AS conta_nome FROM trafego_acoes a LEFT JOIN trafego_contas t ON t.id = a.conta_id "
            f"WHERE a.status IN ({','.join('?' * len(estados))}) ORDER BY a.id DESC LIMIT ?",
            (*estados, int(limite))).fetchall()
    return [dict(r) for r in rows]


def acao(aid: int) -> dict:
    with store.conexao() as con:
        r = con.execute("SELECT a.*, t.nome AS conta_nome FROM trafego_acoes a LEFT JOIN trafego_contas t "
                        "ON t.id = a.conta_id WHERE a.id=?", (int(aid),)).fetchone()
    if r is None:
        raise KeyError(f"ação {aid} não encontrada")
    return dict(r)


def _mudar(aid: int, status: str, resultado: str = "") -> dict:
    with store.conexao() as con:
        con.execute("UPDATE trafego_acoes SET status=?, resultado=?, atualizado_em=? WHERE id=?",
                    (status, resultado[:2000], time.time(), int(aid)))
    return acao(aid)


def propor(conta_id: str, tipo: str, alvo_nome: str, motivo: str, nivel: str = "", alvo_id: str = "",
           de: str = "", para: str = "", impacto: str = "", prioridade: str = "media") -> dict:
    """Uma proposta feita na conversa ("pausa o anúncio X"): espera a sua aprovação."""
    conta(conta_id)
    tipo = tipo if tipo in TIPOS else "manual"
    agora = time.time()
    with store.conexao() as con:
        cur = con.execute(
            "INSERT INTO trafego_acoes(conta_id, criado_em, atualizado_em, tipo, nivel, alvo_id, alvo_nome, de, para,"
            " motivo, impacto, prioridade) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (conta_id, agora, agora, tipo, nivel[:20], str(alvo_id)[:60], alvo_nome[:200], str(de)[:60],
             str(para)[:60], motivo[:1500], impacto[:600], prioridade[:10]))
    return acao(cur.lastrowid)


def rejeitar(aid: int, motivo: str = "") -> dict:
    a = acao(aid)
    if a["status"] not in ("proposta", "falhou"):
        raise ValueError(f"a ação {aid} está {a['status']}")
    return _mudar(aid, "rejeitada", motivo or "rejeitada por você")


def aprovar(aid: int, em_segundo_plano: bool = True) -> dict:
    """Sua aprovação. Pausar/reativar/orçamento: o Claude aplica no Meta.
    Criativo: abre um projeto para a equipe. Manual: fica anotada para você."""
    a = acao(aid)
    if a["status"] not in ("proposta", "falhou"):
        raise ValueError(f"a ação {aid} está {a['status']}, não esperando aprovação")
    if a["tipo"] == "manual":
        return _mudar(aid, "anotada", "aprovada: é para fazer à mão (o Jarvis não altera isso sozinho)")
    if a["tipo"] == "criativo":
        return _criativo(a)
    if not a["alvo_id"]:
        raise ValueError("a ação não tem o id do Meta; peça uma nova análise")
    _mudar(aid, "aplicando", "")
    if em_segundo_plano:
        threading.Thread(target=aplicar, args=(aid,), daemon=True, name=f"trafego-acao-{aid}").start()
        return acao(aid)
    return aplicar(aid)


def _criativo(a: dict) -> dict:
    from haizen import servicos, worker
    c = conta(a["conta_id"])
    pedido = (f"Criativos novos para o Meta Ads da conta {c['nome']} ({a['nivel']} \"{a['alvo_nome']}\").\n"
              f"Por quê: {a['motivo']}\nO que se espera: {a['impacto']}\n{a['para']}")
    r = servicos.criar_projeto(pedido, c.get("cliente_nome") or "", f"Criativos Meta Ads - {c['nome']}"[:80])
    worker.iniciar()
    return _mudar(a["id"], "aplicada", f"projeto {r['projeto']['id']} aberto para a equipe de criação")


def instrucao_aplicar(a: dict) -> str:
    if a["tipo"] == "pausar":
        o_que = f"Mude o status do {a['nivel']} {a['alvo_id']} (\"{a['alvo_nome']}\") para PAUSED com ads_update_entity."
    elif a["tipo"] == "reativar":
        o_que = f"Reative o {a['nivel']} {a['alvo_id']} (\"{a['alvo_nome']}\") com ads_activate_entity."
    elif a["tipo"] == "orcamento":
        o_que = (f"Mude o orçamento do {a['nivel']} {a['alvo_id']} (\"{a['alvo_nome']}\") de R$ {a['de']} para "
                 f"R$ {a['para']} com ads_update_entity (no mesmo tipo de orçamento que já existe, diário ou "
                 f"vitalício; a API do Meta usa centavos). Se o orçamento atual não for R$ {a['de']}, NÃO altere e "
                 f"responda ok=false explicando.")
    else:
        raise ValueError(f"o tipo {a['tipo']} não é aplicado pelo Jarvis")
    return (f"O dono da HAIZEN APROVOU exatamente esta mudança na conta {a['conta_id']}:\n{o_que}\n"
            "Antes, leia o item com ads_get_ad_entities para confirmar que é ele. Faça só esta mudança, nada mais. "
            "Depois leia de novo e confira que mudou.\n"
            'Responda SÓ com JSON: {"ok": true|false, "detalhe": "o que foi feito e conferido, ou por que não"}')


def aplicar(aid: int) -> dict:
    a = acao(aid)
    try:
        r = _json(_claude(instrucao_aplicar(a), ferramentas_leitura() + ferramentas_escrita(),
                          "Aplique só a mudança aprovada descrita na entrada. Responda só com o JSON.",
                          f"aplicar ação {aid}"))
        ok, detalhe = bool(r.get("ok")), str(r.get("detalhe") or "")
    except Exception as e:  # noqa: BLE001
        ok, detalhe = False, str(e)
    feito = _mudar(aid, "aplicada" if ok else "falhou", detalhe or ("feito" if ok else "não aplicada"))
    try:
        from haizen import notificar
        notificar.avisar("Tráfego: mudança aplicada" if ok else "Tráfego: a mudança não foi aplicada",
                         f"{a['alvo_nome']}: {detalhe}"[:200], "trafego" if ok else "erro", "#/trafego")
    except Exception:  # noqa: BLE001
        pass
    return feito


# ── resumo e agenda diária ──────────────────────────────────────────────────
def resumo_texto() -> str:
    """O resumo da manhã (WhatsApp e conversa)."""
    contas = {c["id"]: c for c in contas_lista()}
    ultimas = ultimas_analises()
    hoje = dt.date.today().isoformat()
    linhas = [f"Tráfego de hoje ({dt.date.today().strftime('%d/%m')}):"]
    icone = {"bem": "🟢", "atencao": "🟡", "critico": "🔴", "erro": "⚠️"}
    for cid, an in sorted(ultimas.items(), key=lambda x: ("critico", "atencao", "erro", "bem").index(x[1]["situacao"])
                          if x[1]["situacao"] in ("critico", "atencao", "erro", "bem") else 9):
        if an["dia"] != hoje or cid not in contas:
            continue
        nome = contas[cid].get("cliente_nome") or contas[cid]["nome"]
        m = an["metricas"] or {}
        num = ""
        if m.get("gasto_7d") is not None and m.get("custo_resultado_7d"):
            num = f" — 7d: R$ {float(m['gasto_7d']):.0f}, {m.get('resultados_7d', 0)} {m.get('nome_resultado') or 'resultados'}, R$ {float(m['custo_resultado_7d']):.2f} cada"
        linhas.append(f"{icone.get(an['situacao'], '•')} {nome}{num}" + (f" ({an['erro'][:80]})" if an["erro"] else ""))
    pend = acoes("proposta")
    if pend:
        linhas.append(f"\n{len(pend)} otimização(ões) esperando sua aprovação na tela Tráfego.")
    return "\n".join(linhas) if len(linhas) > 1 else "Nenhuma conta analisada hoje."


def enviar_whatsapp_resumo() -> bool:
    """Só para o seu próprio contato, configurado por você na tela Tráfego."""
    c = config()
    if not (c["whatsapp_ativo"] and c["whatsapp_contato"]):
        return False
    from core import whatsapp_web
    ok, _code, r = whatsapp_web.run_op({"op": "send", "recipient": c["whatsapp_contato"], "text": resumo_texto()},
                                       timeout=60)
    if not ok:
        print(f"[Tráfego] resumo no WhatsApp não foi: {r}")
    return bool(ok)


def hora_de_rodar(agora: dt.datetime | None = None) -> bool:
    agora = agora or dt.datetime.now()
    c = config()
    if c["ultima_rodada"] == agora.date().isoformat():
        return False
    if not any(x["ativo"] for x in contas_lista()):
        return False
    h, m = map(int, c["horario"].split(":"))
    return (agora.hour, agora.minute) >= (h, m)


def rodada_diaria() -> None:
    c = config()
    c["ultima_rodada"] = dt.date.today().isoformat()
    _gravar(c)
    try:
        rodada()
    finally:
        try:
            enviar_whatsapp_resumo()
        except Exception as e:  # noqa: BLE001
            print(f"[Tráfego] resumo no WhatsApp: {e}")


_AGENDA = {"thread": None}


def iniciar_agenda() -> None:
    """Confere a cada minuto se chegou o horário da análise diária."""
    if os.environ.get("HAIZEN_TRAFEGO_AGENDA", "1") == "0":
        return
    if _AGENDA["thread"] and _AGENDA["thread"].is_alive():
        return

    def _laco():
        while True:
            try:
                if hora_de_rodar() and executor.claude_disponivel():
                    rodada_diaria()
            except Exception as e:  # noqa: BLE001
                print(f"[Tráfego] análise diária: {e}")
            time.sleep(60)
    _AGENDA["thread"] = threading.Thread(target=_laco, daemon=True, name="trafego-agenda")
    _AGENDA["thread"].start()


def em_segundo_plano(fazer, rotulo: str) -> None:
    if ESTADO["fazendo"]:
        raise RuntimeError(f"já estou {ESTADO['fazendo']}")
    ESTADO.update(fazendo=rotulo, desde=time.time(), erro="")

    def _rodar():
        try:
            fazer()
        except Exception as e:  # noqa: BLE001
            ESTADO["erro"] = str(e)[:800]
        finally:
            if ESTADO["fazendo"] == rotulo:
                ESTADO["fazendo"] = ""
    threading.Thread(target=_rodar, daemon=True, name=f"trafego-{rotulo}").start()


def painel() -> dict:
    c = config()
    return {"config": {k: c[k] for k in ("horario", "whatsapp_ativo", "whatsapp_contato", "ultima_rodada",
                                           "aviso_conexao")},
            "conectado": bool(c["conectado_em"]), "conectado_em": c["conectado_em"],
            "estado": dict(ESTADO), "contas": contas_lista(), "analises": ultimas_analises(),
            "acoes": acoes(("proposta", "aplicando", "falhou")),
            "historico": acoes(("aplicada", "rejeitada", "anotada"), 20)}

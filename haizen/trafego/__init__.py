"""Gestor de tráfego da HAIZEN: análise diária do Meta Ads e otimizações com aprovação.

O Claude (Claude Code da assinatura) lê as contas pelas ferramentas próprias do Jarvis
(haizen/trafego/mcp_meta.py), que falam com a Marketing API usando o token do usuário do sistema,
o que não vence (Tráfego → Configurar). Não depende mais do login do conector oficial da Meta.
Na análise ele só tem as ferramentas de LEITURA; as otimizações viram propostas na tela Tráfego.
Só depois que você aprova, uma segunda chamada do Claude, com as ferramentas de alteração, aplica
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

SERVIDOR = "meta"
PREFIXO = f"mcp__{SERVIDOR}__"
MCP_META = Path(__file__).resolve().parent / "mcp_meta.py"
PLAYBOOK = Path(__file__).resolve().parent / "playbook.md"
TIMEOUT = int(os.environ.get("HAIZEN_TRAFEGO_TIMEOUT", "900"))

# Ferramentas próprias (mcp_meta.py), com os mesmos nomes do conector oficial da Meta.
LEITURA = ("ads_get_ad_accounts", "ads_get_ad_entities", "ads_insights_performance_trend", "ads_get_creatives",
           "ads_get_ad_preview", "ads_get_ad_account_pages", "ads_get_ad_account_custom_audiences",
           "ads_get_activity_log", "ads_graph_get")
ESCRITA = ("ads_update_entity", "ads_activate_entity", "ads_create_campaign", "ads_create_ad_set",
           "ads_create_creative", "ads_create_ad")
# Ferramentas de alteração por tipo de ação aprovada (nada além disso). Pela API a mudança vale
# na hora (não há rascunho).
ESCRITA_POR_TIPO = {
    "pausar": ("ads_update_entity",),
    "reativar": ("ads_activate_entity",),
    "orcamento": ("ads_update_entity",),
    "publico": ("ads_update_entity",),
    # Estrutura nova inclui os anúncios (com criativos que já existem na conta).
    "estrutura": ("ads_create_campaign", "ads_create_ad_set", "ads_create_ad", "ads_update_entity"),
    "subir_criativo": ("ads_create_creative", "ads_create_ad"),
}
_ESCREVE = re.compile(r"create|update|delete|activate|boost|upload|publish|archive|remove|set_|edit|pause", re.I)
_LE = re.compile(r"^ads_(get|insights|library|search|list|read|help)", re.I)

TIPOS = ("pausar", "reativar", "orcamento", "publico", "estrutura", "subir_criativo", "criativo", "manual")
CRIAM = ("estrutura", "subir_criativo")     # criam coisas novas: você escolhe pausado ou já ativo
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


def _compartilhar_com_social(tk: str) -> None:
    """Token único: se o token do Meta Ads também publica no Instagram, a aba Social passa a usá-lo."""
    try:
        from haizen import social
        from haizen.social import instagram
        escopos = (instagram.info_do_token(tk) or {}).get("escopos") or []
        if "instagram_content_publish" in escopos and "pages_manage_posts" in escopos:
            social.conectar(tk)
    except Exception:  # noqa: BLE001
        pass


def salvar_config(mudancas: dict) -> dict:
    if str(mudancas.get("meta_token") or "").strip():
        from haizen.trafego import envio
        envio.salvar_token(str(mudancas["meta_token"]))
        _ENVIO_CACHE.clear()
        _compartilhar_com_social(str(mudancas["meta_token"]).strip())
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
    """Nomes completos (mcp__meta__...) das ferramentas de leitura."""
    return [PREFIXO + n for n in LEITURA]


def ferramentas_escrita() -> list[str]:
    return [PREFIXO + n for n in ESCRITA]


# ── o Claude com o conector da Meta ────────────────────────────────────────
def _pasta() -> Path:
    from core.data_paths import data_dir
    p = Path(data_dir()) / "jarvis-claude" / "trafego"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _config_mcp() -> Path:
    cfg = {"mcpServers": {SERVIDOR: {"command": executor._python_console(), "args": [str(MCP_META)],
                                     "env": {"PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(MCP_META.parents[2])}}}}
    arq = _pasta() / "mcp-meta.json"
    arq.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return arq


def _claude(prompt: str, ferramentas: list[str], instrucao: str, referencia: str = "",
            pastas: list[Path] | None = None) -> str:
    from haizen import uso
    modelo = uso.modelo("trafego")
    args = ["-p", instrucao, "--output-format", "json", "--permission-mode", "dontAsk",
            "--mcp-config", str(_config_mcp()), "--strict-mcp-config",
            "--allowedTools", ",".join(ferramentas), *(["--model", modelo] if modelo else [])]
    for d in pastas or []:
        args += ["--add-dir", str(d)]
    try:
        return executor._rodar_claude(args, prompt, _pasta(), TIMEOUT, origem="trafego", referencia=referencia)
    except RuntimeError as e:
        if _sem_conexao(str(e)):
            raise ConnectionError(AVISO_CONEXAO) from None
        raise


AVISO_CONEXAO = ("O Jarvis não conseguiu entrar no Meta Ads: confira o token do Meta Ads (usuário do sistema) em "
                 "Tráfego → Configurar. Ele precisa da permissão ads_management e de acesso às contas.")


def _sem_conexao(texto: str) -> bool:
    t = (texto or "").lower()
    return any(s in t for s in ("sem_conexao_meta", "o token do meta ads venceu", "error validating access token",
                                "invalid oauth access token", "sem token do meta ads"))


def _json(texto: str) -> dict:
    bloco = re.search(r"```(?:json)?\s*(\{.*\})\s*```", texto or "", re.S)
    bruto = bloco.group(1) if bloco else (texto or "")[(texto or "").find("{"):(texto or "").rfind("}") + 1]
    try:
        return json.loads(bruto)
    except ValueError:
        raise ValueError("o Claude não devolveu o JSON combinado") from None


def descobrir() -> dict:
    """Confere o token e traz as contas de anúncio (direto da API, sem gastar Claude)."""
    from haizen.trafego import envio
    if not envio.token():
        raise ConnectionError(AVISO_CONEXAO)
    try:
        url = f"{envio.GRAPH}/me/adaccounts?" + __import__("urllib.parse").parse.urlencode(
            {"fields": "id,name,currency,account_status,business{name}", "limit": 200, "access_token": envio.token()})
        contas, n = [], 0
        while url and n < 20:
            r = envio._http("GET", url, timeout=60)
            contas += r.get("data") or []
            url = (r.get("paging") or {}).get("next")
            n += 1
    except envio.ErroEnvio as e:
        raise ConnectionError(f"{AVISO_CONEXAO} ({e})") from None
    situacoes = {1: "ativa", 2: "desativada", 3: "com pendência", 7: "em análise", 9: "em período de carência",
                 100: "fechando", 101: "fechada"}
    c = config()
    c["ferramentas"] = [*LEITURA, *ESCRITA]
    c["conectado_em"], c["aviso_conexao"] = time.time(), ""
    _gravar(c)
    return {"contas": sincronizar_contas([{"id": x.get("id"), "nome": x.get("name"), "moeda": x.get("currency"),
                                           "negocio": (x.get("business") or {}).get("name", ""),
                                           "status": situacoes.get(x.get("account_status"), str(x.get("account_status") or ""))}
                                          for x in contas]),
            "ferramentas": c["ferramentas"]}


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
    if "resultado" in campos:
        from haizen import indicadores
        if campos["resultado"] and campos["resultado"] not in indicadores.RESULTADOS_META:
            raise ValueError("resultado desconhecido")
    for k in ("ativo", "cliente_id", "objetivo", "meta_cpa", "meta_roas", "verba_mensal", "notas", "resultado"):
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
    if c.get("resultado"):
        from haizen import indicadores
        metas.append(f"resultado principal desta conta (use para custo por resultado): "
                     f"{indicadores.RESULTADOS_META.get(c['resultado'], c['resultado'])}")
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
        "Use ads_get_field_context antes de ads_get_ad_entities. Puxe campanhas (objetivo, orçamento), conjuntos "
        "(segmentação, evento de otimização, status de aprendizado) e anúncios ativos (e os pausados nos últimos "
        "7 dias) com gasto, impressões, alcance, frequência, cliques, CTR, CPC, CPM, resultados, custo por "
        "resultado, ROAS e, em vídeo, visualizações de 3 s e ThruPlay, para ontem, últimos 7 dias e os 7 "
        "anteriores. Veja os criativos dos anúncios que mais gastam (texto, título, CTA, formato). Use os sinais "
        "de anomalia, tendência e oportunidade quando ajudarem. Depois faça os QUATRO diagnósticos do playbook.",
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
            "diagnostico": {"criativos": "Markdown curto: o que funciona, o que cansou, o que testar",
                            "publicos": "Markdown curto", "estrutura": "Markdown curto", "funil": "Markdown curto"},
            "ranking_criativos": [{"alvo_id": "id do anúncio", "nome": "nome", "formato": "imagem | video | carrossel",
                                   "gasto_7d": 0, "resultados_7d": 0, "custo_resultado_7d": 0, "ctr_7d": 0,
                                   "frequencia_7d": 0, "taxa_gancho": None,
                                   "veredito": "escalar | manter | cansado | pausar", "porque": "uma frase"}],
            "acoes": [{"tipo": "pausar | reativar | orcamento | publico | estrutura | criativo | manual",
                       "nivel": "campanha | conjunto | anuncio | conta", "alvo_id": "id no Meta",
                       "alvo_nome": "nome", "de": "valor atual (orçamento em reais) ou status", "para": "novo valor",
                       "detalhes": {"o_que_muda": "para publico/estrutura: a especificação completa",
                                    "criativos": [{"id": "id do criativo", "nome": "nome do anúncio/criativo",
                                                   "formato": "video | imagem | carrossel | catalogo",
                                                   "custo_resultado_30d": 0, "resultados_30d": 0, "roas_30d": None,
                                                   "ctr_30d": 0, "porque": "por que serve para ESTA campanha"}]},
                       "motivo": "números que justificam", "impacto": "o que se espera", "prioridade": "alta | media | baixa"}],
            "relatorio": "relatório em Markdown para o dono: números por campanha e conjunto, o que testar na semana",
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
            "INSERT INTO trafego_analises(conta_id, dia, criado_em, situacao, resumo, metricas, alertas, relatorio, erro,"
            " diagnostico) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (cid, hoje.isoformat(), agora, situacao, str(r.get("resumo") or "")[:3000],
             json.dumps(r.get("metricas") or {}, ensure_ascii=False), json.dumps(r.get("alertas") or [], ensure_ascii=False),
             str(r.get("relatorio") or "")[:40000], erro,
             json.dumps({**(r.get("diagnostico") or {}), "ranking": (r.get("ranking_criativos") or [])[:30]},
                        ensure_ascii=False)[:60000]))
        aid = cur.lastrowid
        if not erro:
            # Propostas antigas que você não decidiu: a análise nova substitui.
            con.execute("UPDATE trafego_acoes SET status='substituida', atualizado_em=? "
                        "WHERE conta_id=? AND status='proposta'", (agora, cid))
            for a in (r.get("acoes") or [])[:5]:
                tipo = str(a.get("tipo") or "manual").strip().lower()
                tipo = tipo if tipo in TIPOS else "manual"
                if tipo == "subir_criativo":
                    tipo = "criativo"           # subir arquivos é só pelo fluxo "Subir criativos"
                con.execute(
                    "INSERT INTO trafego_acoes(conta_id, analise_id, criado_em, atualizado_em, tipo, nivel, alvo_id,"
                    " alvo_nome, de, para, motivo, impacto, prioridade, detalhes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (cid, aid, agora, agora, tipo, str(a.get("nivel") or "")[:20], str(a.get("alvo_id") or "")[:60],
                     str(a.get("alvo_nome") or "")[:200], str(a.get("de") if a.get("de") is not None else "")[:60],
                     str(a.get("para") if a.get("para") is not None else "")[:60], str(a.get("motivo") or "")[:1500],
                     str(a.get("impacto") or "")[:600],
                     str(a.get("prioridade") or "media").lower()[:10],
                     json.dumps(a.get("detalhes") or {}, ensure_ascii=False)[:8000]))
    return analise(aid)


def analise(aid: int) -> dict:
    with store.conexao() as con:
        r = con.execute("SELECT * FROM trafego_analises WHERE id=?", (int(aid),)).fetchone()
    if r is None:
        raise KeyError("análise não encontrada")
    d = dict(r)
    d["metricas"], d["alertas"] = json.loads(d["metricas"] or "{}"), json.loads(d["alertas"] or "[]")
    d["diagnostico"] = json.loads(d.get("diagnostico") or "{}")
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
        d["tem_diagnostico"] = len(d.pop("diagnostico", "") or "") > 4
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
           de: str = "", para: str = "", impacto: str = "", prioridade: str = "media",
           detalhes: dict | None = None) -> dict:
    """Uma proposta feita na conversa ("pausa o anúncio X"): espera a sua aprovação."""
    conta(conta_id)
    tipo = tipo if tipo in TIPOS else "manual"
    if tipo == "subir_criativo":
        raise ValueError("para subir criativos use o fluxo 'Subir criativos' (trafego_subir_criativos)")
    agora = time.time()
    with store.conexao() as con:
        cur = con.execute(
            "INSERT INTO trafego_acoes(conta_id, criado_em, atualizado_em, tipo, nivel, alvo_id, alvo_nome, de, para,"
            " motivo, impacto, prioridade, detalhes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (conta_id, agora, agora, tipo, nivel[:20], str(alvo_id)[:60], alvo_nome[:200], str(de)[:60],
             str(para)[:60], motivo[:1500], impacto[:600], prioridade[:10],
             json.dumps(detalhes or {}, ensure_ascii=False)[:8000]))
    return acao(cur.lastrowid)


_EDITAVEIS = ("nivel", "alvo_id", "alvo_nome", "de", "para", "motivo", "impacto", "prioridade")


def _caminho_peca(ref: str) -> str:
    """Caminho do arquivo de uma peça: aceita o id do anexo ([anexo:ID]) ou o caminho."""
    ref = str(ref or "").strip()
    alvo = Path(ref)
    if alvo.is_file():
        return str(alvo)
    from haizen.central import anexos as _anexos
    m = re.fullmatch(r"\[?(?:anexo:)?([^\]/\\]+)\]?", ref)
    if m:
        try:
            p = _anexos.caminho(m.group(1))
            if p.is_file():
                return str(p)
        except Exception:  # noqa: BLE001
            pass
    raise ValueError(f"arquivo não encontrado: {ref}")


def editar(aid: int, campos: dict) -> dict:
    """Muda uma proposta que ainda não foi aplicada (pedido no chat: "troca o texto", "usa este
    outro conjunto", "acrescenta esta peça"). Detalhes são mesclados; "pecas" substitui a lista."""
    a = acao(aid)
    if a["status"] not in ("proposta", "falhou"):
        raise ValueError(f"a ação {aid} está {a['status']}: só dá para editar proposta ainda não aplicada")
    sets = {k: str(campos[k])[:1500] for k in _EDITAVEIS if k in campos and campos[k] is not None}
    det = _detalhes(a)
    novos = campos.get("detalhes") or {}
    if not isinstance(novos, dict):
        raise ValueError("detalhes precisa ser um objeto")
    antigas = {str(p.get("arquivo")): p for p in det.get("pecas") or []}
    det.update({k: v for k, v in novos.items() if k != "pecas"})
    if "pecas" in novos:
        pecas = []
        for p in novos["pecas"] or []:
            p = dict(p)
            p["arquivo"] = _caminho_peca(p.get("arquivo"))
            velha = antigas.get(p["arquivo"]) or {}
            for k in ("image_hash", "image_url", "video_id", "thumbnail_url"):    # já enviado: não sobe de novo
                if velha.get(k) and k not in p:
                    p[k] = velha[k]
            pecas.append(p)
        if not pecas and a["tipo"] == "subir_criativo":
            raise ValueError("a proposta precisa de pelo menos uma peça")
        det["pecas"] = pecas
        det["arquivos"] = [p["arquivo"] for p in pecas]
    sets["detalhes"] = json.dumps(det, ensure_ascii=False)[:12000]
    sets["atualizado_em"] = time.time()
    if a["status"] == "falhou":
        sets["status"] = "proposta"
    historico = (a.get("resultado") or "") if a["status"] == "falhou" else ""
    sets["resultado"] = (historico + f"\nEditada em {time.strftime('%d/%m %H:%M')}: {campos.get('nota') or 'ajustes do dono'}").strip()[-2000:]
    with store.conexao() as con:
        con.execute(f"UPDATE trafego_acoes SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), int(aid)))
    return acao(aid)


def rejeitar(aid: int, motivo: str = "") -> dict:
    a = acao(aid)
    if a["status"] not in ("proposta", "falhou"):
        raise ValueError(f"a ação {aid} está {a['status']}")
    return _mudar(aid, "rejeitada", motivo or "rejeitada por você")


def aprovar(aid: int, em_segundo_plano: bool = True, ativar: bool = False, nota: str = "") -> dict:
    """Sua aprovação. Pausar/reativar/orçamento/público/estrutura/subir criativo:
    o Claude aplica no Meta. O que é criado nasce pausado, a não ser que você
    aprove com "ativar". Criativo: abre um projeto para a equipe. Manual: anotada."""
    a = acao(aid)
    if a["status"] not in ("proposta", "falhou"):
        raise ValueError(f"a ação {aid} está {a['status']}, não esperando aprovação")
    if a["tipo"] == "manual":
        return _mudar(aid, "anotada", "aprovada: é para fazer à mão (o Jarvis não altera isso sozinho)")
    if a["tipo"] == "criativo":
        return _criativo(a)
    if not a["alvo_id"] and a["tipo"] not in CRIAM:
        raise ValueError("a ação não tem o id do Meta; peça uma nova análise")
    with store.conexao() as con:
        con.execute("UPDATE trafego_acoes SET ativar=? WHERE id=?", (1 if (ativar and a["tipo"] in CRIAM) else 0, aid))
    # Numa nova tentativa, o relato da anterior fica para o Claude continuar de onde parou.
    anterior = a["resultado"] if a["status"] == "falhou" else ""
    if (nota or "").strip():
        anterior += f"\n\nRESPOSTA DO DONO PARA ESTA TENTATIVA (vale como autorização dentro da mudança aprovada): {nota.strip()}"
    _mudar(aid, "aplicando", anterior.strip())
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
    elif a["tipo"] == "publico":
        o_que = (f"Mude a segmentação do conjunto {a['alvo_id']} (\"{a['alvo_nome']}\") com ads_update_entity, "
                 f"exatamente assim (mantenha o resto da segmentação como está):\n{_detalhes_texto(a)}")
    elif a["tipo"] == "estrutura":
        o_que = (f"Crie/ajuste a estrutura abaixo com ads_create_campaign / ads_create_ad_set / ads_create_ad / "
                 f"ads_update_entity. Tudo o que for criado nasce PAUSADO.\n{_detalhes_texto(a)}\n"
                 "Anúncios: use SOMENTE os criativos listados em criativos (o dono aprovou exatamente esses). Se algum "
                 "não puder ser usado (arquivado, reprovado, não existe), NÃO escolha outro por conta própria, a não ser "
                 "que a resposta do dono abaixo diga qual usar ou dê o critério: crie com os válidos e, no detalhe, "
                 "liste o que faltou e até 3 candidatos com custo por resultado, ROAS e relevância para o dono escolher.")
    elif a["tipo"] == "subir_criativo":
        o_que = _instrucao_subir(a)
    else:
        raise ValueError(f"o tipo {a['tipo']} não é aplicado pelo Jarvis")
    if a["tipo"] in CRIAM:
        o_que += ("\nDepois de criar, ATIVE o que criou com ads_activate_entity (o dono escolheu publicar já ativo)."
                  if a.get("ativar") else
                  "\nNÃO ative nada: deixe tudo PAUSADO para o dono revisar no Gerenciador. Neste modo NÃO pause "
                  "nem altere o que já está rodando (isso depende da ativação). SUCESSO aqui = tudo criado e conferido "
                  "como pausado: responda ok=true e diga no detalhe o que fica para o dono (ativar, pausar os "
                  "antigos depois).")
    if a.get("resultado") and a.get("status") in ("falhou", "aplicando"):
        o_que += ("\n\nTENTATIVA ANTERIOR (continue de onde parou; NÃO recrie o que já foi criado, use os ids abaixo):\n"
                  + a["resultado"][:2000])
    return (f"O dono da HAIZEN APROVOU exatamente esta mudança na conta {a['conta_id']}:\n{o_que}\n"
            "Antes, leia o item com ads_get_ad_entities para confirmar que é ele. Faça só esta mudança, nada mais. "
            "Depois leia de novo e confira que mudou.\n"
            'Responda SÓ com JSON: {"ok": true|false, "detalhe": "o que foi feito e conferido, ou por que não"}')


def aplicar(aid: int) -> dict:
    a = acao(aid)
    try:
        escrita = list(ESCRITA_POR_TIPO.get(a["tipo"], ()))
        if a["tipo"] in CRIAM and a.get("ativar"):
            escrita.append("ads_activate_entity")
        extra, pastas = [], []
        det = _detalhes(a)
        if det.get("pecas") and a["tipo"] in ("subir_criativo", "estrutura"):
            # O Jarvis envia os arquivos antes e passa hash/id prontos para ads_create_creative.
            from haizen.trafego import envio
            anterior = a.get("resultado") or ""        # notas da tentativa anterior e a resposta do dono

            def _aviso(texto):
                _mudar(aid, "aplicando", texto)
            try:
                envio.preparar_pecas(a["conta_id"], det["pecas"], _aviso)
            finally:
                with store.conexao() as con:          # o que já subiu fica guardado: tentar de novo não reenvia
                    con.execute("UPDATE trafego_acoes SET detalhes=?, resultado=? WHERE id=?",
                                (json.dumps(det, ensure_ascii=False)[:12000], anterior[:2000], aid))
            a = acao(aid)
        if a["tipo"] == "subir_criativo":
            arquivos = [Path(x) for x in (_detalhes(a).get("arquivos") or [])]
            pastas = list(dict.fromkeys(f.parent for f in arquivos))
            extra = ["Read"]
        prompt = (instrucao_aplicar(a) + "\nFerramentas de alteração LIBERADAS nesta aplicação: " + ", ".join(escrita)
                  + ". Se uma tentativa anterior parou por falta de permissão, isso já foi corrigido: prossiga com o "
                    "que foi aprovado.")
        r = _json(_claude(prompt, ferramentas_leitura() + [PREFIXO + n for n in escrita] + extra,
                          "Aplique só a mudança aprovada descrita na entrada. Responda só com o JSON.",
                          f"aplicar ação {aid}", pastas))
        ok, detalhe = bool(r.get("ok")), str(r.get("detalhe") or "")
    except Exception as e:  # noqa: BLE001
        ok, detalhe = False, str(e)
    if not ok and detalhe.upper().startswith("SEM_UPLOAD"):
        detalhe = ("O Meta não recebeu o arquivo (" + detalhe.split(":", 1)[-1].strip()[:300] +
                   "). Cadastre o token do Meta Ads em Tráfego → Configurar para o Jarvis enviar as peças e tente de novo.")
    elif not ok and "ErroEnvio" not in detalhe and _e_erro_envio(detalhe):
        detalhe = "Não consegui enviar as peças para a conta de anúncios: " + detalhe
    feito = _mudar(aid, "aplicada" if ok else "falhou", detalhe or ("feito" if ok else "não aplicada"))
    try:
        from haizen import notificar
        notificar.avisar("Tráfego: mudança aplicada" if ok else "Tráfego: a mudança não foi aplicada",
                         f"{a['alvo_nome']}: {detalhe}"[:200], "trafego" if ok else "erro", "#/trafego")
    except Exception:  # noqa: BLE001
        pass
    return feito


def _e_erro_envio(texto: str) -> bool:
    return any(x in texto for x in ("token do Meta Ads", "ads_management", "conta de anúncios", "não devolveu o hash",
                                    "processar o vídeo", "arquivo não encontrado"))


def _detalhes(a: dict) -> dict:
    try:
        return json.loads(a.get("detalhes") or "{}")
    except ValueError:
        return {}


def _detalhes_texto(a: dict) -> str:
    d = _detalhes(a)
    return json.dumps(d, ensure_ascii=False, indent=1) if d else (a.get("para") or a.get("motivo") or "")


def _instrucao_subir(a: dict) -> str:
    d = _detalhes(a)
    def midia(p):
        if p.get("video_id"):
            return f"video_id {p['video_id']} (vídeo já na conta; miniatura image_url {p.get('thumbnail_url') or '(a padrão)'})"
        if p.get("image_hash"):
            return f"image_hash {p['image_hash']} (imagem já na conta)"
        if p.get("image_url"):
            return f"image_url {p['image_url']} (imagem pública)"
        return "(sem mídia enviada)"
    pecas = "\n".join(
        f"- Peça `{Path(str(p.get('arquivo'))).name}` → use {midia(p)}: texto principal: {p.get('texto_principal')!r}; "
        f"título: {p.get('titulo')!r}; descrição: {p.get('descricao') or ''!r}; CTA: {p.get('cta') or d.get('cta')!r}"
        for p in d.get("pecas") or [])
    return (f"Suba estes criativos como anúncios NOVOS no conjunto {a['alvo_id']} (\"{a['alvo_nome']}\"), "
            f"página {d.get('page_id') or '(a do conjunto)'}, destino {d.get('destino') or '(o dos outros anúncios do conjunto)'}"
            f"{', Instagram ' + str(d.get('instagram_id')) if d.get('instagram_id') else ''}:\n{pecas}\n"
            "As mídias JÁ ESTÃO na conta de anúncios (o Jarvis enviou): para cada peça crie o criativo com "
            "ads_create_creative usando o image_hash / video_id / image_url indicado (não tente enviar arquivo) e depois "
            "o anúncio com ads_create_ad no conjunto, com o nome do arquivo como nome do anúncio. Use exatamente os "
            "textos aprovados. Se alguma peça estiver '(sem mídia enviada)', responda ok=false com detalhe começando "
            "por 'SEM_UPLOAD:'.")


# ── subir criativos da HAIZEN com legendas prontas ─────────────────────────
_IMAGENS = (".png", ".jpg", ".jpeg")
_VIDEOS = (".mp4", ".mov")


def arquivos_do_trabalho(tid: int) -> tuple[list[Path], str]:
    """As peças finais de um trabalho da HAIZEN e os textos que o agente escreveu."""
    t = store.trabalho(int(tid))
    if t is None or not t.get("pasta") or not Path(t["pasta"]).is_dir():
        raise ValueError(f"o trabalho {tid} não tem pasta de arquivos")
    pasta = Path(t["pasta"])
    finais = sorted(f for f in pasta.iterdir() if f.is_file() and f.suffix.lower() in _IMAGENS + _VIDEOS)
    textos = ""
    for nome in ("Textos.txt", "Legendas.txt", "Roteiro.txt"):
        if (pasta / nome).is_file():
            textos = (pasta / nome).read_text(encoding="utf-8", errors="replace")[:6000]
            break
    return finais, textos


def preparar_criativos(conta_id: str, pedido: str, trabalho_id: int | None = None,
                       anexos: list | None = None) -> dict:
    """O gestor monta a proposta 'subir criativo': escolhe o conjunto, escreve o texto
    principal, o título e o CTA de cada peça. Nada sobe antes da sua aprovação."""
    c = conta(conta_id)
    arquivos, textos = ([], "")
    if trabalho_id:
        arquivos, textos = arquivos_do_trabalho(trabalho_id)
    if anexos:
        from haizen.central import anexos as _anexos
        arquivos += [Path(d["caminho"]) for d in _anexos.varios(anexos)]
    arquivos = [f for f in arquivos if f.suffix.lower() in _IMAGENS + _VIDEOS][:10]
    if not arquivos:
        raise ValueError("escolha as peças (um trabalho da HAIZEN com PNG/JPG/MP4 ou arquivos enviados)")
    lista = "\n".join(f"- {f.as_posix()}" for f in arquivos)
    prompt = "\n".join([
        PLAYBOOK.read_text(encoding="utf-8"), "",
        f"## Tarefa: preparar a subida de criativos na conta {c['id']} ({c['nome']})"
        f"{' — cliente ' + c['cliente_nome'] if c.get('cliente_nome') else ''}",
        f"Pedido do dono: {pedido or '(sem instruções extras: escolha o melhor conjunto ativo para estas peças)'}",
        "", "Peças (abra cada uma com Read para ver):", lista, "",
        "Textos que a equipe já escreveu para estas peças (use como base):", textos or "(nenhum)", "",
        "1. Leia a conta (ads_get_ad_entities): ache a campanha e o conjunto certos pelo pedido; sem indicação, o "
        "conjunto ativo de melhor resultado com objetivo compatível. Veja os anúncios que já rodam ali (página, "
        "Instagram, destino/link ou WhatsApp, CTA) para repetir a configuração.",
        "2. Para cada peça escreva: texto principal (gancho na 1ª linha, benefício concreto, prova ou oferta, CTA; "
        "até ~125 caracteres antes do 'ver mais'), título (até 40 caracteres), descrição curta e o CTA do Meta "
        "(LEARN_MORE, SHOP_NOW, SEND_MESSAGE, WHATSAPP_MESSAGE, BOOK_TRAVEL, SIGN_UP, CONTACT_US...). "
        "Nunca invente preço, prazo ou número que não esteja nos textos ou no pedido.",
        "3. NÃO crie nada no Meta agora: só a proposta.",
        "Responda SÓ com JSON: " + json.dumps({
            "alvo_id": "id do conjunto", "alvo_nome": "nome do conjunto", "campanha": "nome da campanha",
            "page_id": "id da página", "instagram_id": "id do Instagram ou vazio", "destino": "link ou WhatsApp",
            "cta": "CTA padrão",
            "pecas": [{"arquivo": "caminho exato da lista", "texto_principal": "...", "titulo": "...",
                       "descricao": "...", "cta": "..."}],
            "motivo": "por que este conjunto e estes textos"}, ensure_ascii=False)])
    r = _json(_claude(prompt, ferramentas_leitura() + ["Read"],
                      "Prepare a proposta descrita na entrada só com leitura. Responda só com o JSON.",
                      f"preparar criativos {c['nome']}", list(dict.fromkeys(f.parent for f in arquivos))))
    validos = {f.as_posix() for f in arquivos}
    pecas = [p for p in r.get("pecas") or [] if Path(str(p.get("arquivo") or "")).as_posix() in validos]
    if not pecas or not r.get("alvo_id"):
        raise ValueError("o gestor não conseguiu montar a proposta (conjunto ou peças não encontrados)")
    detalhes = {k: r.get(k) for k in ("campanha", "page_id", "instagram_id", "destino", "cta")}
    detalhes.update(pecas=pecas, arquivos=[str(Path(p["arquivo"])) for p in pecas])
    agora = time.time()
    with store.conexao() as con:
        cur = con.execute(
            "INSERT INTO trafego_acoes(conta_id, criado_em, atualizado_em, tipo, nivel, alvo_id, alvo_nome, para,"
            " motivo, impacto, prioridade, detalhes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (conta_id, agora, agora, "subir_criativo", "conjunto", str(r["alvo_id"])[:60],
             str(r.get("alvo_nome") or "")[:200], f"{len(pecas)} anúncio(s) novo(s)", str(r.get("motivo") or "")[:1500],
             "", "alta", json.dumps(detalhes, ensure_ascii=False)[:8000]))
    proposta = acao(cur.lastrowid)
    try:
        from haizen import notificar
        notificar.avisar("Tráfego: criativos prontos para subir", f"{len(pecas)} peça(s) com legenda para {c['nome']}",
                         "trafego", "#/trafego")
    except Exception:  # noqa: BLE001
        pass
    return proposta


def arquivo_da_acao(aid: int, i: int) -> Path:
    """Uma peça de uma proposta 'subir criativo' (só as listadas nela)."""
    arquivos = _detalhes(acao(aid)).get("arquivos") or []
    if not 0 <= int(i) < len(arquivos):
        raise KeyError("arquivo não encontrado")
    p = Path(arquivos[int(i)])
    if not p.is_file():
        raise KeyError("arquivo não encontrado")
    return p


def trabalhos_com_pecas(limite: int = 30) -> list[dict]:
    """Trabalhos da HAIZEN com peças prontas, para escolher no 'Subir criativos'."""
    out = []
    for t in store.listar_trabalhos(None, 200):
        if t["status"] not in ("aguardando_aprovacao", "aprovado") or not t.get("pasta"):
            continue
        p = Path(t["pasta"])
        if p.is_dir() and any(f.suffix.lower() in _IMAGENS + _VIDEOS for f in p.iterdir() if f.is_file()):
            cli = store.cliente_por_id(t["cliente_id"])
            out.append({"id": t["id"], "titulo": t.get("titulo") or t["agente"], "agente": t["agente"],
                        "cliente": cli["nome"] if cli else "", "status": t["status"], "cliente_id": t["cliente_id"]})
        if len(out) >= limite:
            break
    return out


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
    try:
        from haizen import rotina
        rc = rotina.config()
        if rc["resumo_ativo"] and rc["resumo_whatsapp"]:
            return False            # o tráfego vai junto no resumo da manhã: uma mensagem só
    except Exception:  # noqa: BLE001
        pass
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


_ENVIO_CACHE: dict = {}


def situacao_envio() -> dict:
    if _ENVIO_CACHE.get("em", 0) > time.time() - 600:
        return _ENVIO_CACHE["v"]
    try:
        from haizen.trafego import envio
        v = envio.situacao()
    except Exception as e:  # noqa: BLE001
        v = {"pronto": False, "aviso": str(e)}
    _ENVIO_CACHE.update(em=time.time(), v=v)
    return v


def painel() -> dict:
    c = config()
    return {"config": {k: c[k] for k in ("horario", "whatsapp_ativo", "whatsapp_contato", "ultima_rodada",
                                           "aviso_conexao")}, "envio": situacao_envio(),
            "conectado": bool(c["conectado_em"]), "conectado_em": c["conectado_em"],
            "estado": dict(ESTADO), "contas": contas_lista(), "analises": ultimas_analises(),
            "acoes": [{**a, "detalhes": _detalhes(a)} for a in acoes(("proposta", "aplicando", "falhou"))],
            "historico": acoes(("aplicada", "rejeitada", "anotada"), 20)}

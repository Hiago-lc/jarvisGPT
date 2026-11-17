"""Gestor de Google Ads: as contas dos clientes, com análise diária e mudanças
só com a sua aprovação.

Os números (campanhas, palavras-chave, termos de pesquisa, anúncios) são lidos
pela Google Ads API e resumidos aqui, sem gastar o Claude. O Claude lê o
resumo e propõe ações (orçamento, pausar, negativar termos). Ao aprovar, quem
aplica é este código, exatamente o que está na proposta.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time
from pathlib import Path

from haizen import store
from haizen.googleads import api

TIPOS = {"orcamento": "Orçamento", "pausar_campanha": "Pausar campanha", "ativar_campanha": "Ativar campanha",
         "negativar_termos": "Negativar termos", "pausar_palavra": "Pausar palavra-chave",
         "pausar_anuncio": "Pausar anúncio", "criar_campanha_pesquisa": "Nova campanha de pesquisa",
         "criar_campanha_demand_gen": "Nova campanha YouTube / Demand Gen", "criar_campanha_display": "Nova campanha de Display",
         "alerta": "Aviso"}
PESADAS = ("criar_campanha_demand_gen", "criar_campanha_display")      # sobem arquivos: rodam em segundo plano
CTAS = ("LEARN_MORE", "SHOP_NOW", "BUY_NOW", "ORDER_NOW", "SIGN_UP", "SUBSCRIBE", "CONTACT_US", "GET_QUOTE", "BOOK_NOW",
        "APPLY_NOW", "DOWNLOAD", "SEE_MORE", "START_NOW", "VISIT_SITE", "WATCH_NOW")
BRASIL = "geoTargetConstants/2076"
PORTUGUES = "languageConstants/1014"
LANCES = ("conversoes", "cliques", "cpa")
PLAYBOOK = Path(__file__).resolve().parent / "playbook.md"
TIMEOUT = 900

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gads_contas (
    id TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    login_id TEXT NOT NULL DEFAULT '',
    moeda TEXT NOT NULL DEFAULT '',
    cliente_id INTEGER,
    ativo INTEGER NOT NULL DEFAULT 0,
    objetivo TEXT NOT NULL DEFAULT '',
    meta_cpa REAL,
    ultima_analise REAL,
    erro TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS gads_analises (
    id INTEGER PRIMARY KEY,
    conta_id TEXT NOT NULL,
    criado_em REAL NOT NULL,
    metricas TEXT NOT NULL DEFAULT '{}',
    resumo TEXT NOT NULL DEFAULT '',
    saude INTEGER,
    alertas TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS gads_acoes (
    id INTEGER PRIMARY KEY,
    conta_id TEXT NOT NULL,
    analise_id INTEGER,
    tipo TEXT NOT NULL,
    titulo TEXT NOT NULL,
    motivo TEXT NOT NULL DEFAULT '',
    impacto TEXT NOT NULL DEFAULT '',
    detalhes TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'proposta',   -- proposta | aplicada | rejeitada | erro
    resultado TEXT NOT NULL DEFAULT '',
    origem TEXT NOT NULL DEFAULT 'analise',
    criado_em REAL NOT NULL,
    atualizado_em REAL NOT NULL
);
"""


def _garantir(con) -> None:
    con.executescript(_SCHEMA)


# ── configuração ────────────────────────────────────────────────────────────
def _arq_config() -> Path:
    from core.data_paths import data_dir
    return Path(data_dir()) / "googleads.json"


PADRAO = {"horario": "07:20", "agenda_ativa": True, "ultima_rodada": ""}


def config() -> dict:
    try:
        return {**PADRAO, **json.loads(_arq_config().read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(PADRAO)


def salvar_config(mud: dict) -> dict:
    c = config()
    if "horario" in mud:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(mud["horario"])):
            raise ValueError("horário no formato HH:MM")
        c["horario"] = mud["horario"]
    for k in ("agenda_ativa",):
        if k in mud:
            c[k] = bool(mud[k])
    if "ultima_rodada" in mud:
        c["ultima_rodada"] = str(mud["ultima_rodada"])
    if mud.get("client_id") or mud.get("client_secret"):
        api.salvar_cliente(str(mud.get("client_id") or ""), str(mud.get("client_secret") or ""))
    _arq_config().parent.mkdir(parents=True, exist_ok=True)
    _arq_config().write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return c


# ── contas ──────────────────────────────────────────────────────────────────
def contas(so_ativas: bool = False) -> list[dict]:
    with store.conexao() as con:
        _garantir(con)
        rows = con.execute("SELECT g.*, c.nome cliente_nome FROM gads_contas g LEFT JOIN clientes c ON c.id=g.cliente_id "
                           + ("WHERE g.ativo=1 " if so_ativas else "") + "ORDER BY g.ativo DESC, g.nome").fetchall()
    return [{**dict(r), "id_formatado": api.formatar_id(r["id"])} for r in rows]


def conta(cid: str) -> dict:
    cid = str(cid).replace("-", "")
    for c in contas():
        if c["id"] == cid:
            return c
    raise KeyError("conta do Google Ads não encontrada")


def sincronizar_contas() -> list[dict]:
    """Traz as contas que o seu login enxerga. As novas entram desligadas: você escolhe quais analisar."""
    achadas = api.contas_acessiveis()
    with store.conexao() as con:
        _garantir(con)
        for c in achadas:
            con.execute("INSERT INTO gads_contas(id, nome, login_id, moeda) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE "
                        "SET nome=excluded.nome, login_id=excluded.login_id, moeda=excluded.moeda",
                        (c["id"], c["nome"], c["login_id"], c["moeda"]))
    return contas()


def editar_conta(cid: str, d: dict) -> dict:
    c = conta(cid)
    campos = {}
    if "ativo" in d:
        campos["ativo"] = 1 if d["ativo"] else 0
    if "cliente_id" in d:
        campos["cliente_id"] = int(d["cliente_id"]) if str(d["cliente_id"] or "").isdigit() else None
    if "objetivo" in d:
        campos["objetivo"] = str(d["objetivo"] or "")[:600]
    if "meta_cpa" in d:
        campos["meta_cpa"] = float(d["meta_cpa"]) if str(d["meta_cpa"] or "").strip() else None
    if campos:
        with store.conexao() as con:
            con.execute(f"UPDATE gads_contas SET {', '.join(k + '=?' for k in campos)} WHERE id=?", (*campos.values(), c["id"]))
    return conta(c["id"])


def _mudar_conta(cid: str, **campos) -> None:
    with store.conexao() as con:
        con.execute(f"UPDATE gads_contas SET {', '.join(k + '=?' for k in campos)} WHERE id=?", (*campos.values(), cid))


# ── coleta e métricas (sem Claude) ──────────────────────────────────────────
def _m(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _reais(micros) -> float:
    return round(_m(micros) / 1_000_000, 2)


def _resumo_metricas(met: dict) -> dict:
    custo = _reais(met.get("costMicros"))
    conv = round(_m(met.get("conversions")), 2)
    valor = round(_m(met.get("conversionsValue")), 2)
    cliques = int(_m(met.get("clicks")))
    imp = int(_m(met.get("impressions")))
    return {"custo": custo, "conversoes": conv, "valor": valor, "cliques": cliques, "impressoes": imp,
            "cpa": round(custo / conv, 2) if conv else None, "roas": round(valor / custo, 2) if custo and valor else None,
            "ctr": round(cliques / imp * 100, 2) if imp else None, "cpc": round(custo / cliques, 2) if cliques else None}


def _somar(linhas: list[dict]) -> dict:
    tot = {"costMicros": 0, "conversions": 0, "conversionsValue": 0, "clicks": 0, "impressions": 0}
    for l in linhas:
        for k in tot:
            tot[k] += _m((l.get("metrics") or {}).get(k))
    return _resumo_metricas(tot)


def _periodo(ini: dt.date, fim: dt.date) -> str:
    return f"segments.date BETWEEN '{ini.isoformat()}' AND '{fim.isoformat()}'"


def coletar(c: dict, hoje: dt.date | None = None) -> dict:
    hoje = hoje or dt.date.today()
    ontem = hoje - dt.timedelta(days=1)
    p30 = _periodo(hoje - dt.timedelta(days=30), ontem)
    a30 = _periodo(hoje - dt.timedelta(days=60), hoje - dt.timedelta(days=31))
    p7 = _periodo(hoje - dt.timedelta(days=7), ontem)
    a7 = _periodo(hoje - dt.timedelta(days=14), hoje - dt.timedelta(days=8))
    met = ("metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions, "
           "metrics.conversions_value")
    camp = api.gaql(c, f"""SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,
        campaign.bidding_strategy_type, campaign_budget.amount_micros, campaign_budget.resource_name,
        campaign_budget.explicitly_shared, {met}, metrics.search_impression_share,
        metrics.search_budget_lost_impression_share, metrics.search_rank_lost_impression_share
        FROM campaign WHERE {p30} AND campaign.status != 'REMOVED'""")
    camp_ant = api.gaql(c, f"SELECT campaign.id, {met} FROM campaign WHERE {a30} AND campaign.status != 'REMOVED'")
    dias = api.gaql(c, f"SELECT segments.date, {met} FROM customer WHERE {p30}")
    sete = api.gaql(c, f"SELECT {met} FROM customer WHERE {p7}")
    sete_ant = api.gaql(c, f"SELECT {met} FROM customer WHERE {a7}")
    try:
        palavras = api.gaql(c, f"""SELECT ad_group_criterion.resource_name, ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type, ad_group_criterion.status, ad_group_criterion.quality_info.quality_score,
            campaign.id, campaign.name, ad_group.name, {met} FROM keyword_view
            WHERE {p30} AND ad_group_criterion.status != 'REMOVED' ORDER BY metrics.cost_micros DESC LIMIT 60""")
    except api.ErroGoogleAds:
        palavras = []
    try:
        termos = api.gaql(c, f"""SELECT search_term_view.search_term, search_term_view.status, campaign.id, campaign.name,
            {met} FROM search_term_view WHERE {p30} ORDER BY metrics.cost_micros DESC LIMIT 100""")
    except api.ErroGoogleAds:
        termos = []
    try:
        anuncios = api.gaql(c, f"""SELECT ad_group_ad.resource_name, ad_group_ad.ad.id, ad_group_ad.ad.type,
            ad_group_ad.status, ad_group_ad.ad_strength, campaign.name, ad_group.name, ad_group.id, {met}
            FROM ad_group_ad WHERE {p30} AND ad_group_ad.status != 'REMOVED' ORDER BY metrics.cost_micros DESC LIMIT 40""")
    except api.ErroGoogleAds:
        anuncios = []
    return metricas(camp, camp_ant, dias, sete, sete_ant, palavras, termos, anuncios, hoje)


def _var(a, b):
    try:
        return round((a - b) / b * 100, 1) if a is not None and b else None
    except TypeError:
        return None


def metricas(camp, camp_ant, dias, sete, sete_ant, palavras, termos, anuncios, hoje: dt.date) -> dict:
    ant = {str((l.get("campaign") or {}).get("id")): _resumo_metricas(l.get("metrics") or {}) for l in camp_ant}
    campanhas = []
    for l in camp:
        cp, b, m = l.get("campaign") or {}, l.get("campaignBudget") or {}, l.get("metrics") or {}
        r = _resumo_metricas(m)
        a = ant.get(str(cp.get("id"))) or {}
        campanhas.append({
            "id": str(cp.get("id")), "nome": cp.get("name"), "status": cp.get("status"),
            "tipo": cp.get("advertisingChannelType"), "lance": cp.get("biddingStrategyType"),
            "orcamento_diario": _reais(b.get("amountMicros")), "orcamento_recurso": b.get("resourceName"),
            "orcamento_compartilhado": bool(b.get("explicitlyShared")), **r,
            "parcela_impressoes": _pct(m.get("searchImpressionShare")),
            "perda_orcamento": _pct(m.get("searchBudgetLostImpressionShare")),
            "perda_classificacao": _pct(m.get("searchRankLostImpressionShare")),
            "anterior": {k: a.get(k) for k in ("custo", "conversoes", "cpa", "roas")},
            "var_cpa": _var(r["cpa"], a.get("cpa")), "var_conversoes": _var(r["conversoes"], a.get("conversoes"))})
    campanhas.sort(key=lambda x: -x["custo"])
    tot30, tot_ant = _somar(camp), _somar(camp_ant)
    t7, t7a = _somar(sete), _somar(sete_ant)
    por_dia = {str((l.get("segments") or {}).get("date")): _resumo_metricas(l.get("metrics") or {}) for l in dias}
    serie = []
    for i in range(30, 0, -1):
        d = (hoje - dt.timedelta(days=i)).isoformat()
        x = por_dia.get(d) or {}
        serie.append({"dia": d, "custo": x.get("custo", 0), "conversoes": x.get("conversoes", 0)})
    pal = []
    for l in palavras:
        k, m = l.get("adGroupCriterion") or {}, l.get("metrics") or {}
        pal.append({"recurso": k.get("resourceName"), "texto": (k.get("keyword") or {}).get("text"),
                    "correspondencia": (k.get("keyword") or {}).get("matchType"), "status": k.get("status"),
                    "qualidade": (k.get("qualityInfo") or {}).get("qualityScore"),
                    "campanha": (l.get("campaign") or {}).get("name"), "campanha_id": str((l.get("campaign") or {}).get("id")),
                    "grupo": (l.get("adGroup") or {}).get("name"), **_resumo_metricas(m)})
    ter = []
    for l in termos:
        s, m = l.get("searchTermView") or {}, l.get("metrics") or {}
        r = _resumo_metricas(m)
        if r["custo"] <= 0:
            continue
        ter.append({"termo": s.get("searchTerm"), "status": s.get("status"),
                    "campanha": (l.get("campaign") or {}).get("name"), "campanha_id": str((l.get("campaign") or {}).get("id")),
                    **{k: r[k] for k in ("custo", "cliques", "conversoes", "cpa")}})
    sem_conv = [t for t in ter if not t["conversoes"]]
    anu = []
    for l in anuncios:
        a, m = l.get("adGroupAd") or {}, l.get("metrics") or {}
        anu.append({"recurso": a.get("resourceName"), "tipo": (a.get("ad") or {}).get("type"), "status": a.get("status"),
                    "forca": a.get("adStrength"), "campanha": (l.get("campaign") or {}).get("name"),
                    "grupo": (l.get("adGroup") or {}).get("name"), "grupo_id": str((l.get("adGroup") or {}).get("id")),
                    **{k: v for k, v in _resumo_metricas(m).items() if k in ("custo", "cliques", "ctr", "conversoes")}})
    return {
        "dia": hoje.isoformat(), "ult30": tot30, "ant30": tot_ant, "ult7": t7, "ant7": t7a,
        "var30": {k: _var(tot30[k], tot_ant[k]) for k in ("custo", "conversoes", "cpa", "roas")},
        "var7": {k: _var(t7[k], t7a[k]) for k in ("custo", "conversoes", "cpa")},
        "ontem": {k: (serie[-1] if serie else {}).get(k, 0) for k in ("custo", "conversoes")},
        "por_dia": serie, "campanhas": campanhas[:25], "palavras": pal[:40],
        "termos_sem_conversao": sorted(sem_conv, key=lambda x: -x["custo"])[:40],
        "termos_que_convertem": sorted((t for t in ter if t["conversoes"]), key=lambda x: -x["conversoes"])[:15],
        "desperdicio_termos": round(sum(t["custo"] for t in sem_conv), 2), "anuncios": anu[:25],
        "rastreamento_suspeito": tot30["cliques"] > 100 and not tot30["conversoes"],
    }


def _pct(x):
    try:
        return round(float(x) * 100, 1) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ── análise ─────────────────────────────────────────────────────────────────
def _pasta() -> Path:
    from core.data_paths import data_dir
    p = Path(data_dir()) / "googleads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def prompt_analise(c: dict, m: dict) -> str:
    leve = {k: v for k, v in m.items() if k != "por_dia"}
    leve["por_dia_ultimos_14"] = m["por_dia"][-14:]
    return f"""{PLAYBOOK.read_text(encoding='utf-8')}

---
Hoje é {m['dia']}. Conta: {c['nome']} ({c['id_formatado']}), cliente da agência: {c.get('cliente_nome') or '—'}.
Objetivo/observações do dono: {c.get('objetivo') or 'não informado'}. CPA alvo: {c.get('meta_cpa') or 'não informado'}.

Números da conta (Google Ads API; valores em reais; percentuais já em %):
{json.dumps(leve, ensure_ascii=False)}

Use os ids/recursos EXATOS acima. Responda SÓ com JSON:
{{"resumo": "3 a 5 frases diretas para o dono da agência",
  "saude": 0-100,
  "alertas": ["avisos curtos que não mudam a conta"],
  "acoes": [{{"tipo": "...", "titulo": "curto", "motivo": "o número que justifica", "impacto": "o que esperar",
             "detalhes": {{...}}}}]}}"""


def _json(texto: str) -> dict:
    bloco = re.search(r"```(?:json)?\s*(\{.*\})\s*```", texto or "", re.S)
    bruto = bloco.group(1) if bloco else (texto or "")[(texto or "").find("{"):(texto or "").rfind("}") + 1]
    try:
        return json.loads(bruto)
    except ValueError:
        raise ValueError("o Claude não devolveu o JSON combinado") from None


def _claude(prompt: str, referencia: str) -> str:
    from haizen import executor, uso
    modelo = uso.modelo("googleads")
    args = ["-p", "Analise a conta descrita na entrada e responda só com o JSON pedido.", "--output-format", "json",
            "--permission-mode", "dontAsk", *(["--model", modelo] if modelo else [])]
    return executor._rodar_claude(args, prompt, _pasta(), TIMEOUT, origem="googleads", referencia=referencia)


def validar(tipo: str, det: dict, m: dict | None = None) -> dict:
    if tipo not in TIPOS:
        raise ValueError(f"tipo de ação desconhecido: {tipo}")
    det = dict(det or {})
    camps = {x["id"]: x for x in (m or {}).get("campanhas", [])}
    if tipo in ("orcamento", "pausar_campanha", "ativar_campanha", "negativar_termos"):
        det["campanha_id"] = str(det.get("campanha_id") or "")
        if not det["campanha_id"].isdigit() or (m is not None and det["campanha_id"] not in camps):
            raise ValueError("campanha não encontrada na conta")
        if m is not None:
            det["campanha_nome"] = camps[det["campanha_id"]]["nome"]
    if tipo == "orcamento":
        det["orcamento_diario"] = round(float(det.get("orcamento_diario") or 0), 2)
        if det["orcamento_diario"] <= 0:
            raise ValueError("orçamento inválido")
        if m is not None:
            cp = camps[det["campanha_id"]]
            if cp["orcamento_compartilhado"]:
                raise ValueError("orçamento compartilhado entre campanhas: mude no Google Ads")
            atual = cp["orcamento_diario"] or 0
            if atual and not (0.5 * atual <= det["orcamento_diario"] <= 1.5 * atual):
                raise ValueError("mudança de orçamento acima de 50% de uma vez")
            det["orcamento_anterior"] = atual
            det["orcamento_recurso"] = cp["orcamento_recurso"]
    if tipo == "negativar_termos":
        termos = [re.sub(r"\s+", " ", str(t)).strip().lower() for t in det.get("termos") or []]
        det["termos"] = [t for t in dict.fromkeys(termos) if 1 < len(t) <= 80][:20]
        if not det["termos"]:
            raise ValueError("faltaram os termos")
        det["correspondencia"] = det.get("correspondencia") if det.get("correspondencia") in ("EXACT", "PHRASE", "BROAD") \
            else "PHRASE"
    if tipo == "criar_campanha_pesquisa":
        return _validar_campanha(det)
    if tipo == "criar_campanha_demand_gen":
        return _validar_demand_gen(det)
    if tipo == "criar_campanha_display":
        return _validar_display(det)
    if tipo in ("pausar_palavra", "pausar_anuncio"):
        det["recurso"] = str(det.get("recurso") or "")
        padrao = r"customers/\d+/adGroupCriteria/\d+~\d+" if tipo == "pausar_palavra" else r"customers/\d+/adGroupAds/\d+~\d+"
        if not re.fullmatch(padrao, det["recurso"]):
            raise ValueError("recurso inválido")
        if m is not None:
            lista = m.get("palavras" if tipo == "pausar_palavra" else "anuncios") or []
            if det["recurso"] not in {x["recurso"] for x in lista}:
                raise ValueError("palavra-chave/anúncio não encontrado")
    return det


def _validar_campanha(det: dict) -> dict:
    """Campanha de pesquisa completa: confere tudo que o Google recusaria, com mensagem clara."""
    erros = []
    d = {"nome": re.sub(r"\s+", " ", str(det.get("nome") or "")).strip()[:120]}
    if len(d["nome"]) < 3:
        erros.append("falta o nome da campanha")
    d["orcamento_diario"] = round(float(det.get("orcamento_diario") or 0), 2)
    if not 1 <= d["orcamento_diario"] <= 5000:
        erros.append("orçamento diário entre R$ 1 e R$ 5.000")
    d["lance"] = det.get("lance") if det.get("lance") in LANCES else "conversoes"
    if d["lance"] == "cpa":
        d["cpa_alvo"] = round(float(det.get("cpa_alvo") or 0), 2)
        if d["cpa_alvo"] <= 0:
            erros.append("lance por CPA alvo precisa do cpa_alvo")
    d["locais"] = [str(x).strip() for x in det.get("locais") or [] if str(x).strip()][:20]
    d["url_final"] = str(det.get("url_final") or "").strip()
    if not re.fullmatch(r"https?://[^\s]+\.[^\s]+", d["url_final"]):
        erros.append("url_final inválida (use o link completo da página, com https://)")
    d["rede_de_pesquisa"] = bool(det.get("rede_de_pesquisa"))
    d["negativas"] = [str(x).strip().lower() for x in det.get("negativas") or [] if 1 < len(str(x).strip()) <= 80][:50]
    grupos = det.get("grupos") or []
    if not 1 <= len(grupos) <= 5:
        erros.append("de 1 a 5 grupos de anúncios")
    d["grupos"] = []
    for i, g in enumerate(grupos[:5], 1):
        nome = str(g.get("nome") or f"Grupo {i}").strip()[:100]
        pal = []
        for k in g.get("palavras") or []:
            texto = k.get("texto") if isinstance(k, dict) else k
            corr = (k.get("correspondencia") if isinstance(k, dict) else "") or "PHRASE"
            texto = re.sub(r"\s+", " ", str(texto or "")).strip().lower()
            if 1 < len(texto) <= 80:
                pal.append({"texto": texto, "correspondencia": corr if corr in ("EXACT", "PHRASE", "BROAD") else "PHRASE"})
        tit = [str(t).strip() for t in g.get("titulos") or [] if str(t).strip()]
        desc = [str(t).strip() for t in g.get("descricoes") or [] if str(t).strip()]
        longos = [t for t in tit if len(t) > 30] + [t for t in desc if len(t) > 90]
        if not 1 <= len(pal) <= 50:
            erros.append(f"{nome}: de 1 a 50 palavras-chave")
        if not 3 <= len(tit) <= 15:
            erros.append(f"{nome}: de 3 a 15 títulos")
        if not 2 <= len(desc) <= 4:
            erros.append(f"{nome}: de 2 a 4 descrições")
        if longos:
            erros.append(f"{nome}: passam do limite (títulos 30, descrições 90 caracteres): " + " | ".join(longos[:4]))
        c1, c2 = str(g.get("caminho1") or "")[:15], str(g.get("caminho2") or "")[:15]
        d["grupos"].append({"nome": nome, "palavras": pal, "titulos": tit[:15], "descricoes": desc[:4],
                            "caminho1": re.sub(r"\s+", "-", c1), "caminho2": re.sub(r"\s+", "-", c2) if c1 else ""})
    if erros:
        raise ValueError("a campanha não passaria no Google: " + "; ".join(erros))
    d["ativar"] = bool(det.get("ativar"))
    return d


def _textos(lista, minimo: int, maximo: int, limite: int, rotulo: str, erros: list) -> list[str]:
    itens = [re.sub(r"\s+", " ", str(t)).strip() for t in lista or [] if str(t).strip()]
    longos = [t for t in itens if len(t) > limite]
    if not minimo <= len(itens) <= maximo:
        erros.append(f"{rotulo}: de {minimo} a {maximo}")
    if longos:
        erros.append(f"{rotulo} passam de {limite} caracteres: " + " | ".join(longos[:3]))
    return itens[:maximo]


def _validar_base(det: dict, erros: list) -> dict:
    d = {"nome": re.sub(r"\s+", " ", str(det.get("nome") or "")).strip()[:120]}
    if len(d["nome"]) < 3:
        erros.append("falta o nome da campanha")
    d["orcamento_diario"] = round(float(det.get("orcamento_diario") or 0), 2)
    if not 1 <= d["orcamento_diario"] <= 5000:
        erros.append("orçamento diário entre R$ 1 e R$ 5.000")
    d["lance"] = det.get("lance") if det.get("lance") in LANCES else "conversoes"
    if d["lance"] == "cpa":
        d["cpa_alvo"] = round(float(det.get("cpa_alvo") or 0), 2)
        if d["cpa_alvo"] <= 0:
            erros.append("lance por CPA alvo precisa do cpa_alvo")
    d["locais"] = [str(x).strip() for x in det.get("locais") or [] if str(x).strip()][:20]
    d["url_final"] = str(det.get("url_final") or "").strip()
    if not re.fullmatch(r"https?://[^\s]+\.[^\s]+", d["url_final"]):
        erros.append("url_final inválida (link completo da página, com https://)")
    d["nome_empresa"] = str(det.get("nome_empresa") or "").strip()
    if not 1 <= len(d["nome_empresa"]) <= 25:
        erros.append("nome_empresa de 1 a 25 caracteres")
    d["logo"] = str(det.get("logo") or "").strip()
    if not d["logo"]:
        erros.append("falta o logo (imagem; vira quadrado 1:1)")
    else:
        try:
            from haizen.googleads import midia
            midia.conferir_imagem(d["logo"])
        except ValueError as e:
            erros.append(f"logo: {e}")
    d["ativar"] = bool(det.get("ativar"))
    return d


def _validar_imagens(refs, erros: list, rotulo: str = "imagens") -> list[str]:
    from haizen.googleads import midia
    ok = []
    for r in (refs or [])[:10]:
        try:
            i = midia.conferir_imagem(r)
            if min(i["largura"], i["altura"]) < 314:
                erros.append(f"{i['nome']}: pequena demais (mínimo ~600x314 px)")
            ok.append(str(r))
        except ValueError as e:
            erros.append(f"{rotulo}: {e}")
    if not ok:
        erros.append(f"falta pelo menos 1 imagem em {rotulo} (cortada sozinha em 1,91:1, 1:1 e 4:5)")
    return ok


def _validar_demand_gen(det: dict) -> dict:
    erros: list = []
    d = _validar_base(det, erros)
    v = det.get("anuncio_video") or None
    im = det.get("anuncio_imagem") or None
    if not v and not im:
        erros.append("inclua anuncio_video (YouTube) e/ou anuncio_imagem")
    if v:
        from haizen.googleads import midia
        vids = []
        for ref in (v.get("videos") or [])[:5]:
            if isinstance(ref, dict):                       # já normalizado (reaprovação)
                ref = ref.get("youtube") or ref.get("arquivo") or ""
            if midia.id_youtube(ref):
                vids.append({"youtube": midia.id_youtube(ref)})
            else:
                try:
                    p = midia.arquivo(ref)
                    if p.suffix.lower() not in midia.VIDEOS:
                        raise ValueError(f"não é vídeo: {p.name}")
                    vids.append({"arquivo": str(ref)})
                except ValueError as e:
                    erros.append(f"vídeo: {e}")
        if not vids:
            erros.append("anuncio_video: falta o vídeo (link do YouTube ou o arquivo anexado)")
        d["anuncio_video"] = {
            "videos": vids, "titulos": _textos(v.get("titulos"), 1, 5, 40, "títulos do vídeo", erros),
            "titulos_longos": _textos(v.get("titulos_longos"), 1, 5, 90, "títulos longos do vídeo", erros),
            "descricoes": _textos(v.get("descricoes"), 1, 5, 90, "descrições do vídeo", erros),
            "cta": v.get("cta") if v.get("cta") in CTAS else "LEARN_MORE",
            "caminho1": str(v.get("caminho1") or "")[:15], "caminho2": str(v.get("caminho2") or "")[:15]}
    if im:
        d["anuncio_imagem"] = {"imagens": _validar_imagens(im.get("imagens"), erros),
                               "titulos": _textos(im.get("titulos"), 1, 5, 40, "títulos da imagem", erros),
                               "descricoes": _textos(im.get("descricoes"), 1, 5, 90, "descrições da imagem", erros),
                               "cta_texto": _cta_curto(im.get("cta_texto"))}
    if erros:
        raise ValueError("a campanha não passaria no Google: " + "; ".join(erros))
    return d


def _cta_curto(t) -> str:
    """O botão do anúncio de imagem do Demand Gen aceita até 10 caracteres."""
    t = " ".join(str(t or "").split()) or "Saiba mais"
    if len(t) <= 10:
        return t
    curto = ""
    for palavra in t.split():
        if len(f"{curto} {palavra}".strip()) > 10:
            break
        curto = f"{curto} {palavra}".strip()
    return curto or t[:10]


def _validar_display(det: dict) -> dict:
    erros: list = []
    d = _validar_base(det, erros)
    d["imagens"] = _validar_imagens(det.get("imagens"), erros)
    d["titulos"] = _textos(det.get("titulos"), 1, 5, 30, "títulos", erros)
    d["titulo_longo"] = (_textos([det.get("titulo_longo")], 1, 1, 90, "título longo", erros) or [""])[0]
    d["descricoes"] = _textos(det.get("descricoes"), 1, 5, 90, "descrições", erros)
    if erros:
        raise ValueError("a campanha não passaria no Google: " + "; ".join(erros))
    return d


def _lance(d: dict) -> dict:
    return {"conversoes": {"maximizeConversions": {}}, "cliques": {"targetSpend": {}},
            "cpa": {"maximizeConversions": {"targetCpaMicros": str(int(d.get("cpa_alvo", 0) * 1_000_000))}}}[d["lance"]]


def _locais_recursos(d: dict) -> list[str]:
    if not d["locais"]:
        return [BRASIL]
    achados = api.sugerir_locais(d["locais"])
    faltou = [x for x in d["locais"] if x.lower() not in achados]
    if faltou:
        raise ValueError(f"não achei estes locais no Google: {', '.join(faltou)}")
    return [achados[x.lower()]["recurso"] for x in d["locais"]]


class _Ids:
    """Ids temporários negativos para ligar tudo numa chamada só."""
    def __init__(self, cid: str):
        self.cid, self.n = cid, 0

    def novo(self, tipo: str) -> str:
        self.n -= 1
        return f"customers/{self.cid}/{tipo}/{self.n}"


def _asset_imagem(ids: _Ids, ops: list, nome: str, dados: bytes) -> str:
    import base64
    rn = ids.novo("assets")
    ops.append({"assetOperation": {"create": {"resourceName": rn, "name": nome[:120], "type": "IMAGE",
                                              "imageAsset": {"data": base64.b64encode(dados).decode()}}}})
    return rn


def _base_campanha(c: dict, d: dict, canal: str, ids: _Ids, ops: list) -> str:
    orc, camp = ids.novo("campaignBudgets"), ids.novo("campaigns")
    ops.append({"campaignBudgetOperation": {"create": {"resourceName": orc, "name": f"{d['nome']} · orçamento {time.strftime('%Y%m%d-%H%M')}",
                                                       "amountMicros": str(int(d["orcamento_diario"] * 1_000_000)),
                                                       "deliveryMethod": "STANDARD", "explicitlyShared": False}}})
    ops.append({"campaignOperation": {"create": {"resourceName": camp, "name": d["nome"],
                                                 "status": "ENABLED" if d["ativar"] else "PAUSED",
                                                 "advertisingChannelType": canal, "campaignBudget": orc,
                                                 "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
                                                 **_lance(d)}}})
    return camp


def _criar_demand_gen(c: dict, d: dict) -> dict:
    from haizen.googleads import midia
    ids, ops = _Ids(c["id"]), []
    camp = _base_campanha(c, d, "DEMAND_GEN", ids, ops)
    grupo = ids.novo("adGroups")
    ops.append({"adGroupOperation": {"create": {"resourceName": grupo, "name": f"{d['nome']} · público", "campaign": camp,
                                                "status": "ENABLED"}}})
    for g in _locais_recursos(d):          # no Demand Gen, local e idioma ficam no grupo
        ops.append({"adGroupCriterionOperation": {"create": {"adGroup": grupo, "location": {"geoTargetConstant": g}}}})
    ops.append({"adGroupCriterionOperation": {"create": {"adGroup": grupo, "language": {"languageConstant": PORTUGUES}}}})
    logo = _asset_imagem(ids, ops, f"{d['nome_empresa']} logo", midia.logo_quadrado(d["logo"]))
    enviados = []
    if d.get("anuncio_video"):
        v = d["anuncio_video"]
        videos = []
        for x in v["videos"]:
            vid = x.get("youtube")
            if not vid:
                vid = midia.subir_youtube(x["arquivo"], d["nome"], f"Anúncio · {d['nome_empresa']}")
                x.clear()
                x["youtube"] = vid          # guardado na proposta: tentar de novo não sobe o vídeo outra vez
                if d.get("_ao_mudar"):
                    d["_ao_mudar"](f"Vídeo enviado ao YouTube (youtu.be/{vid}). Criando a campanha…")
            enviados.append(vid)
            rn = ids.novo("assets")
            ops.append({"assetOperation": {"create": {"resourceName": rn, "name": f"{d['nome']} vídeo {vid}",
                                                      "type": "YOUTUBE_VIDEO", "youtubeVideoAsset": {"youtubeVideoId": vid}}}})
            videos.append({"asset": rn})
        cta = ids.novo("assets")
        ops.append({"assetOperation": {"create": {"resourceName": cta, "name": f"{d['nome']} CTA",
                                                  "type": "CALL_TO_ACTION", "callToActionAsset": {"callToAction": v["cta"]}}}})
        anuncio = {"headlines": [{"text": t} for t in v["titulos"]], "longHeadlines": [{"text": t} for t in v["titulos_longos"]],
                   "descriptions": [{"text": t} for t in v["descricoes"]], "videos": videos, "logoImages": [{"asset": logo}],
                   "businessName": {"text": d["nome_empresa"]}, "callToActions": [{"asset": cta}]}
        if v.get("caminho1"):
            anuncio["breadcrumb1"] = v["caminho1"]
            if v.get("caminho2"):
                anuncio["breadcrumb2"] = v["caminho2"]
        ops.append({"adGroupAdOperation": {"create": {"adGroup": grupo, "status": "ENABLED", "ad": {
            "name": f"{d['nome']} · vídeo", "finalUrls": [d["url_final"]], "demandGenVideoResponsiveAd": anuncio}}}})
    if d.get("anuncio_imagem"):
        im = d["anuncio_imagem"]
        campos = {"paisagem": "marketingImages", "quadrada": "squareMarketingImages", "retrato": "portraitMarketingImages"}
        imagens: dict = {v: [] for v in campos.values()}
        # Demand Gen aceita até 20 imagens somando os três formatos.
        sel = midia.selecionar_cortes(im["imagens"], ("paisagem", "quadrada", "retrato"), 20, ("paisagem", "quadrada"))
        for formato, lista in sel.items():
            for i, dados in enumerate(lista):
                imagens[campos[formato]].append({"asset": _asset_imagem(ids, ops, f"{d['nome']} {formato} {i + 1}", dados)})
        anuncio = {k: v for k, v in imagens.items() if v}
        anuncio.update({"logoImages": [{"asset": logo}], "headlines": [{"text": t} for t in im["titulos"]],
                        "descriptions": [{"text": t} for t in im["descricoes"]], "businessName": d["nome_empresa"],
                        "callToActionText": im["cta_texto"]})
        ops.append({"adGroupAdOperation": {"create": {"adGroup": grupo, "status": "ENABLED", "ad": {
            "name": f"{d['nome']} · imagem", "finalUrls": [d["url_final"]], "demandGenMultiAssetAd": anuncio}}}})
    r = _mutate_esperando_youtube(c, ops, d)
    criada = next((x.get("campaignResult", {}).get("resourceName") for x in r.get("mutateOperationResponses") or []
                   if x.get("campaignResult")), "")
    return {"campanha": criada, "videos_youtube": enviados, "operacoes": len(ops)}


def _mutate_esperando_youtube(c: dict, ops: list, d: dict, tentativas: int = 20, espera: float = 45) -> dict:
    """Vídeo recém-enviado fica alguns minutos "sem duração" enquanto o YouTube processa: espera e tenta de novo."""
    for i in range(tentativas):
        try:
            return api.mutate_tudo(c, ops)
        except api.ErroGoogleAds as e:
            msg = str(e)
            outros = [p for p in msg.split("; ") if "YOUTUBE_VIDEO_DURATION_NOT_DEFINED" not in p]
            if "YOUTUBE_VIDEO_DURATION_NOT_DEFINED" not in msg or outros or i == tentativas - 1:
                raise
            if d.get("_ao_mudar"):
                d["_ao_mudar"](f"O YouTube ainda está processando o vídeo; tentando de novo ({i + 1}/{tentativas})…")
            time.sleep(espera)
    raise api.ErroGoogleAds("o YouTube não terminou de processar o vídeo")


def _criar_display(c: dict, d: dict) -> dict:
    from haizen.googleads import midia
    ids, ops = _Ids(c["id"]), []
    camp = _base_campanha(c, d, "DISPLAY", ids, ops)
    for g in _locais_recursos(d):
        ops.append({"campaignCriterionOperation": {"create": {"campaign": camp, "location": {"geoTargetConstant": g}}}})
    ops.append({"campaignCriterionOperation": {"create": {"campaign": camp, "language": {"languageConstant": PORTUGUES}}}})
    grupo = ids.novo("adGroups")
    ops.append({"adGroupOperation": {"create": {"resourceName": grupo, "name": f"{d['nome']} · grupo", "campaign": camp,
                                                "status": "ENABLED", "type": "DISPLAY_STANDARD"}}})
    logo = _asset_imagem(ids, ops, f"{d['nome_empresa']} logo", midia.logo_quadrado(d["logo"]))
    # Display responsivo aceita até 15 imagens somando paisagem e quadrada.
    sel = midia.selecionar_cortes(d["imagens"], ("paisagem", "quadrada"), 15, ("paisagem", "quadrada"))
    paisagem = [{"asset": _asset_imagem(ids, ops, f"{d['nome']} paisagem {i + 1}", b)} for i, b in enumerate(sel["paisagem"])]
    quadrada = [{"asset": _asset_imagem(ids, ops, f"{d['nome']} quadrada {i + 1}", b)} for i, b in enumerate(sel["quadrada"])]
    if not paisagem or not quadrada:
        raise ValueError("as imagens precisam render pelo menos um corte 1,91:1 (600x314) e um 1:1 (300x300)")
    ops.append({"adGroupAdOperation": {"create": {"adGroup": grupo, "status": "ENABLED", "ad": {
        "finalUrls": [d["url_final"]], "responsiveDisplayAd": {
            "marketingImages": paisagem, "squareMarketingImages": quadrada, "squareLogoImages": [{"asset": logo}],
            "headlines": [{"text": t} for t in d["titulos"]], "longHeadline": {"text": d["titulo_longo"]},
            "descriptions": [{"text": t} for t in d["descricoes"]], "businessName": d["nome_empresa"]}}}}})
    r = api.mutate_tudo(c, ops)
    criada = next((x.get("campaignResult", {}).get("resourceName") for x in r.get("mutateOperationResponses") or []
                   if x.get("campaignResult")), "")
    return {"campanha": criada, "operacoes": len(ops)}


def _criar_campanha(c: dict, d: dict) -> dict:
    cid = c["id"]
    rec = lambda tipo, n: f"customers/{cid}/{tipo}/{n}"  # noqa: E731
    locais = []
    if d["locais"]:
        achados = api.sugerir_locais(d["locais"])
        faltou = [x for x in d["locais"] if x.lower() not in achados]
        if faltou:
            raise ValueError(f"não achei estes locais no Google: {', '.join(faltou)}")
        locais = [achados[x.lower()]["recurso"] for x in d["locais"]]
    lance = {"conversoes": {"maximizeConversions": {}}, "cliques": {"targetSpend": {}},
             "cpa": {"maximizeConversions": {"targetCpaMicros": str(int(d.get("cpa_alvo", 0) * 1_000_000))}}}[d["lance"]]
    carimbo = time.strftime("%Y%m%d-%H%M")
    ops = [
        {"campaignBudgetOperation": {"create": {"resourceName": rec("campaignBudgets", -1),
                                                "name": f"{d['nome']} · orçamento {carimbo}",
                                                "amountMicros": str(int(d["orcamento_diario"] * 1_000_000)),
                                                "deliveryMethod": "STANDARD", "explicitlyShared": False}}},
        {"campaignOperation": {"create": {"resourceName": rec("campaigns", -2), "name": d["nome"],
                                          "status": "ENABLED" if d["ativar"] else "PAUSED",
                                          "advertisingChannelType": "SEARCH", "campaignBudget": rec("campaignBudgets", -1),
                                          "networkSettings": {"targetGoogleSearch": True,
                                                              "targetSearchNetwork": d["rede_de_pesquisa"],
                                                              "targetContentNetwork": False,
                                                              "targetPartnerSearchNetwork": False},
                                          "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
                                          **lance}}},
        {"campaignCriterionOperation": {"create": {"campaign": rec("campaigns", -2),
                                                   "language": {"languageConstant": PORTUGUES}}}},
    ]
    for g in locais or [BRASIL]:
        ops.append({"campaignCriterionOperation": {"create": {"campaign": rec("campaigns", -2),
                                                              "location": {"geoTargetConstant": g}}}})
    for n in d["negativas"]:
        ops.append({"campaignCriterionOperation": {"create": {"campaign": rec("campaigns", -2), "negative": True,
                                                              "keyword": {"text": n, "matchType": "PHRASE"}}}})
    for i, g in enumerate(d["grupos"]):
        grupo = rec("adGroups", -(10 + i))
        ops.append({"adGroupOperation": {"create": {"resourceName": grupo, "name": g["nome"], "campaign": rec("campaigns", -2),
                                                    "status": "ENABLED", "type": "SEARCH_STANDARD"}}})
        for k in g["palavras"]:
            ops.append({"adGroupCriterionOperation": {"create": {"adGroup": grupo, "status": "ENABLED",
                                                                 "keyword": {"text": k["texto"], "matchType": k["correspondencia"]}}}})
        rsa = {"headlines": [{"text": t} for t in g["titulos"]], "descriptions": [{"text": t} for t in g["descricoes"]]}
        if g["caminho1"]:
            rsa["path1"] = g["caminho1"]
            if g["caminho2"]:
                rsa["path2"] = g["caminho2"]
        ops.append({"adGroupAdOperation": {"create": {"adGroup": grupo, "status": "ENABLED",
                                                      "ad": {"finalUrls": [d["url_final"]], "responsiveSearchAd": rsa}}}})
    r = api.mutate_tudo(c, ops)
    criada = next((x.get("campaignResult", {}).get("resourceName") for x in r.get("mutateOperationResponses") or []
                   if x.get("campaignResult")), "")
    return {"campanha": criada, "operacoes": len(ops)}


def analisar(cid: str, hoje: dt.date | None = None) -> dict:
    c = conta(cid)
    try:
        m = coletar(c, hoje)
    except Exception as e:  # noqa: BLE001
        _mudar_conta(c["id"], erro=str(e)[:400])
        raise
    r = _json(_claude(prompt_analise(c, m), f"{c['nome']} {m['dia']}"))
    agora = time.time()
    with store.conexao() as con:
        _garantir(con)
        aid = con.execute("INSERT INTO gads_analises(conta_id, criado_em, metricas, resumo, saude, alertas) VALUES(?,?,?,?,?,?)",
                          (c["id"], agora, json.dumps(m, ensure_ascii=False), str(r.get("resumo") or ""),
                           int(r["saude"]) if str(r.get("saude", "")).isdigit() else None,
                           json.dumps([str(a) for a in r.get("alertas") or []][:12], ensure_ascii=False))).lastrowid
        con.execute("UPDATE gads_acoes SET status='rejeitada', resultado='substituída pela análise nova', atualizado_em=? "
                    "WHERE conta_id=? AND status='proposta' AND origem='analise'", (agora, c["id"]))
        for a in (r.get("acoes") or [])[:8]:
            tipo = str(a.get("tipo") or "")
            try:
                det = validar(tipo, a.get("detalhes") or {}, m) if tipo != "alerta" else {}
            except (ValueError, TypeError) as e:
                print(f"[Google Ads] proposta descartada ({tipo}): {e}")
                continue
            con.execute("INSERT INTO gads_acoes(conta_id, analise_id, tipo, titulo, motivo, impacto, detalhes, criado_em,"
                        " atualizado_em) VALUES(?,?,?,?,?,?,?,?,?)",
                        (c["id"], aid, tipo, str(a.get("titulo") or TIPOS[tipo])[:160], str(a.get("motivo") or "")[:600],
                         str(a.get("impacto") or "")[:300], json.dumps(det, ensure_ascii=False), agora, agora))
    _mudar_conta(c["id"], ultima_analise=agora, erro="")
    return ultima_analise(c["id"])


def ultima_analise(cid: str) -> dict | None:
    with store.conexao() as con:
        _garantir(con)
        r = con.execute("SELECT * FROM gads_analises WHERE conta_id=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    if r is None:
        return None
    return {**dict(r), "metricas": json.loads(r["metricas"] or "{}"), "alertas": json.loads(r["alertas"] or "[]")}


# ── propostas e aplicação ───────────────────────────────────────────────────
def acoes(cid: str | None = None, status: tuple = ("proposta",), limite: int = 100) -> list[dict]:
    with store.conexao() as con:
        _garantir(con)
        sql = (f"SELECT a.*, g.nome conta_nome FROM gads_acoes a JOIN gads_contas g ON g.id=a.conta_id "
               f"WHERE a.status IN ({','.join('?' * len(status))})")
        args: list = list(status)
        if cid:
            sql += " AND a.conta_id=?"
            args.append(cid)
        rows = con.execute(sql + " ORDER BY a.id DESC LIMIT ?", (*args, limite)).fetchall()
    return [{**dict(r), "detalhes": json.loads(r["detalhes"] or "{}"), "tipo_nome": TIPOS.get(r["tipo"], r["tipo"])}
            for r in rows]


def acao(aid: int) -> dict:
    for a in acoes(status=("proposta", "aplicando", "aplicada", "rejeitada", "erro"), limite=100000):
        if a["id"] == int(aid):
            return a
    raise KeyError("ação não encontrada")


def _mudar_acao(aid: int, **campos) -> dict:
    campos["atualizado_em"] = time.time()
    if "detalhes" in campos and not isinstance(campos["detalhes"], str):
        campos["detalhes"] = json.dumps(campos["detalhes"], ensure_ascii=False)
    with store.conexao() as con:
        con.execute(f"UPDATE gads_acoes SET {', '.join(k + '=?' for k in campos)} WHERE id=?", (*campos.values(), int(aid)))
    return acao(aid)


def propor(cid: str, tipo: str, titulo: str, motivo: str = "", detalhes: dict | None = None, origem: str = "pedido") -> dict:
    c = conta(cid)
    an = ultima_analise(c["id"])
    m = (an or {}).get("metricas") or None
    det = validar(tipo, detalhes or {}, m) if tipo != "alerta" else {}
    agora = time.time()
    with store.conexao() as con:
        _garantir(con)
        aid = con.execute("INSERT INTO gads_acoes(conta_id, tipo, titulo, motivo, detalhes, origem, criado_em, atualizado_em)"
                          " VALUES(?,?,?,?,?,?,?,?)", (c["id"], tipo, (titulo or TIPOS[tipo])[:160], (motivo or "")[:600],
                                                      json.dumps(det, ensure_ascii=False), origem, agora, agora)).lastrowid
    return acao(aid)


def editar(aid: int, detalhes: dict) -> dict:
    """Ajusta uma proposta antes de aprovar (ex.: verba de campanha nova), validando de novo."""
    a = acao(aid)
    if a["status"] not in ("proposta", "erro"):
        raise ValueError("esta proposta não pode mais ser ajustada")
    det = {k: v for k, v in (detalhes or {}).items() if not k.startswith("_")}
    det = validar(a["tipo"], det) if a["tipo"] != "alerta" else {}
    return _mudar_acao(aid, detalhes=det, status="proposta" if a["status"] == "erro" else a["status"])


def rejeitar(aid: int, nota: str = "") -> dict:
    if acao(aid)["status"] not in ("proposta", "erro"):
        raise ValueError("esta proposta não está mais esperando aprovação (a tela foi atualizada)")
    return _mudar_acao(aid, status="rejeitada", resultado=nota[:300])


def aprovar(aid: int, detalhes: dict | None = None, ativar: bool | None = None, em_segundo_plano: bool = True) -> dict:
    a = acao(aid)
    if a["status"] not in ("proposta", "erro"):
        if a["status"] == "aplicando":
            raise ValueError("esta campanha já está sendo criada: aguarde")
        if a["status"] == "rejeitada" and str(a.get("resultado") or "").startswith("substituída"):
            raise ValueError("esta proposta foi trocada por uma análise mais nova: a tela foi atualizada com as propostas atuais")
        raise ValueError("esta ação já foi aplicada ou rejeitada (a tela foi atualizada)")
    c = conta(a["conta_id"])
    det = {k: v for k, v in (detalhes if detalhes is not None else a["detalhes"]).items() if not k.startswith("_")}
    if ativar is not None:
        det["ativar"] = bool(ativar)
    if a["tipo"] != "alerta":
        extra = {k: det[k] for k in ("orcamento_recurso", "orcamento_anterior", "campanha_nome") if k in det}
        det = {**validar(a["tipo"], det), **extra}
    if a["tipo"] in PESADAS and em_segundo_plano:
        # Sobe vídeo ao YouTube e imagens: pode levar minutos. A tela acompanha pelo status.
        _mudar_acao(aid, status="aplicando", detalhes=det, resultado="Subindo arquivos e criando a campanha…")
        threading.Thread(target=_aplicar_e_guardar, args=(aid, c, a["tipo"], det), daemon=True,
                         name=f"googleads-aplicar-{aid}").start()
        return acao(aid)
    return _aplicar_e_guardar(aid, c, a["tipo"], det)


def _aplicar_e_guardar(aid: int, c: dict, tipo: str, det: dict) -> dict:
    if tipo in PESADAS:
        det["_ao_mudar"] = lambda texto: _mudar_acao(aid, resultado=texto[:300],
                                                     detalhes={k: v for k, v in det.items() if not k.startswith("_")})
    try:
        res = _aplicar(c, tipo, det)
    except Exception as e:  # noqa: BLE001
        det.pop("_ao_mudar", None)
        r = _mudar_acao(aid, status="erro", detalhes=det, resultado=str(e)[:600])
        _avisar_fim(r)
        return r
    det.pop("_ao_mudar", None)
    r = _mudar_acao(aid, status="aplicada", detalhes={**det, "_aplicado": res}, resultado=_descrever(tipo, det))
    if tipo in PESADAS:
        _avisar_fim(r)
    return r


def _avisar_fim(a: dict) -> None:
    try:
        from haizen import notificar
        ok = a["status"] == "aplicada"
        notificar.avisar("Google Ads: " + ("campanha criada" if ok else "não aplicou"), a["resultado"][:200],
                         "info" if ok else "erro", "#/googleads")
    except Exception:  # noqa: BLE001
        pass


def _aplicar(c: dict, tipo: str, det: dict) -> dict:
    cid = c["id"]
    if tipo == "alerta":
        return {"ok": True}
    if tipo in ("pausar_campanha", "ativar_campanha"):
        return api.mutate(c, "campaigns", [{"update": {"resourceName": f"customers/{cid}/campaigns/{det['campanha_id']}",
                                                      "status": "PAUSED" if tipo == "pausar_campanha" else "ENABLED"},
                                           "updateMask": "status"}])
    if tipo == "orcamento":
        recurso = det.get("orcamento_recurso")
        if not recurso:
            linhas = api.gaql(c, f"SELECT campaign_budget.resource_name, campaign_budget.explicitly_shared FROM campaign "
                                 f"WHERE campaign.id = {int(det['campanha_id'])}")
            b = (linhas[0].get("campaignBudget") if linhas else {}) or {}
            if b.get("explicitlyShared"):
                raise ValueError("orçamento compartilhado entre campanhas: mude no Google Ads")
            recurso = b.get("resourceName")
        if not recurso:
            raise ValueError("não achei o orçamento da campanha")
        return api.mutate(c, "campaignBudgets", [{"update": {"resourceName": recurso,
                                                            "amountMicros": str(int(round(det["orcamento_diario"] * 1_000_000)))},
                                                 "updateMask": "amount_micros"}])
    if tipo == "negativar_termos":
        ops = [{"create": {"campaign": f"customers/{cid}/campaigns/{det['campanha_id']}", "negative": True,
                           "keyword": {"text": t, "matchType": det["correspondencia"]}}} for t in det["termos"]]
        return api.mutate(c, "campaignCriteria", ops)
    if tipo == "criar_campanha_pesquisa":
        return _criar_campanha(c, det)
    if tipo == "criar_campanha_demand_gen":
        return _criar_demand_gen(c, det)
    if tipo == "criar_campanha_display":
        return _criar_display(c, det)
    if tipo == "pausar_palavra":
        return api.mutate(c, "adGroupCriteria", [{"update": {"resourceName": det["recurso"], "status": "PAUSED"},
                                                 "updateMask": "status"}])
    if tipo == "pausar_anuncio":
        return api.mutate(c, "adGroupAds", [{"update": {"resourceName": det["recurso"], "status": "PAUSED"},
                                            "updateMask": "status"}])
    raise ValueError(f"tipo desconhecido: {tipo}")


def _brl(v) -> str:
    return "R$ " + f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _descrever(tipo: str, d: dict) -> str:
    nome = d.get("campanha_nome") or d.get("campanha_id", "")
    if tipo == "orcamento":
        return f"Orçamento de {nome}: {_brl(d.get('orcamento_anterior'))} → {_brl(d['orcamento_diario'])} por dia."
    if tipo == "negativar_termos":
        return f"{len(d['termos'])} termo(s) negativado(s) em {nome}."
    if tipo in ("criar_campanha_demand_gen", "criar_campanha_display"):
        rot = "YouTube / Demand Gen" if tipo == "criar_campanha_demand_gen" else "Display"
        return (f"Campanha {rot} \"{d['nome']}\" criada {'ATIVA' if d.get('ativar') else 'PAUSADA (ative no Google Ads ou peça aqui)'}"
                f" com {_brl(d['orcamento_diario'])}/dia.")
    if tipo == "criar_campanha_pesquisa":
        return (f"Campanha \"{d['nome']}\" criada {'ATIVA' if d.get('ativar') else 'PAUSADA (ative no Google Ads ou peça aqui)'}"
                f" com {len(d['grupos'])} grupo(s) e {_brl(d['orcamento_diario'])}/dia.")
    return {"pausar_campanha": f"Campanha {nome} pausada.", "ativar_campanha": f"Campanha {nome} ativada.",
            "pausar_palavra": "Palavra-chave pausada.", "pausar_anuncio": "Anúncio pausado.", "alerta": "Ciente."}.get(tipo, "Feito.")


# ── agenda, painel, resumo ──────────────────────────────────────────────────
ESTADO = {"fazendo": "", "erro": ""}
# Uma análise por vez: duas ao mesmo tempo geravam duas levas de propostas e a primeira
# (ainda na tela) virava "substituída" — o clique dava "já foi aplicada ou rejeitada".
_UMA_POR_VEZ = threading.Lock()


def rodada(hoje: dt.date | None = None) -> dict:
    feitas, erros = [], []
    for c in contas(so_ativas=True):
        ESTADO["fazendo"] = c["nome"]
        try:
            analisar(c["id"], hoje)
            feitas.append(c["nome"])
        except Exception as e:  # noqa: BLE001
            erros.append(f"{c['nome']}: {e}")
    ESTADO["fazendo"] = ""
    ESTADO["erro"] = "; ".join(erros)[:600]
    if feitas or erros:
        try:
            from haizen import notificar
            notificar.avisar("Google Ads analisado", f"{len(feitas)} conta(s); {len(acoes())} proposta(s) para aprovar."
                             + (f" Erros: {len(erros)}" if erros else ""), "erro" if erros else "info", "#/googleads")
        except Exception:  # noqa: BLE001
            pass
    return {"feitas": feitas, "erros": erros}


def analisar_em_segundo_plano(cid: str | None = None) -> bool:
    """Começa a análise; False se já tem uma rodando."""
    if not _UMA_POR_VEZ.acquire(blocking=False):
        return False

    def _fazer():
        try:
            if cid:
                ESTADO["fazendo"] = conta(cid)["nome"]
                analisar(cid)
                ESTADO["erro"] = ""
            else:
                rodada()
        except Exception as e:  # noqa: BLE001
            ESTADO["erro"] = str(e)[:400]
        finally:
            ESTADO["fazendo"] = ""
            _UMA_POR_VEZ.release()
    threading.Thread(target=_fazer, daemon=True, name="googleads-analise").start()
    return True


_AGENDA = {"thread": None}


def iniciar_agenda() -> None:
    if os.environ.get("HAIZEN_GADS_AGENDA", "1") == "0" or (_AGENDA["thread"] and _AGENDA["thread"].is_alive()):
        return

    def _laco():
        time.sleep(50)
        while True:
            try:
                agora = dt.datetime.now()
                c = config()
                h, mi = map(int, c["horario"].split(":"))
                if (c["agenda_ativa"] and c["ultima_rodada"] != agora.date().isoformat()
                        and (agora.hour, agora.minute) >= (h, mi) and api.conectado() and contas(so_ativas=True)):
                    salvar_config({"ultima_rodada": agora.date().isoformat()})
                    from haizen import executor
                    if executor.claude_disponivel():
                        with _UMA_POR_VEZ:
                            rodada(agora.date())
            except Exception as e:  # noqa: BLE001
                print(f"[Google Ads] {e}")
            time.sleep(120)
    _AGENDA["thread"] = threading.Thread(target=_laco, daemon=True, name="googleads-agenda")
    _AGENDA["thread"].start()


def painel() -> dict:
    out = []
    for c in contas():
        an = ultima_analise(c["id"])
        m = (an or {}).get("metricas") or {}
        out.append({**c, "analise": {k: an.get(k) for k in ("criado_em", "resumo", "saude", "alertas")} if an else None,
                    "metricas": {k: m.get(k) for k in ("ontem", "ult7", "ult30", "var7", "var30", "por_dia", "campanhas",
                                                        "desperdicio_termos", "termos_sem_conversao",
                                                        "rastreamento_suspeito")} if m else None,
                    "propostas": acoes(c["id"], ("proposta", "erro")), "historico": acoes(c["id"], ("aplicando", "aplicada"), 8)})
    return {"conectado": api.conectado(), "tem_cliente": api.tem_cliente(), "contas": out, "estado": ESTADO,
            "config": config(), "tipos": TIPOS}


def resumo_linhas() -> list[str]:
    linhas = []
    for c in contas(so_ativas=True):
        an = ultima_analise(c["id"])
        if not an:
            continue
        m = an["metricas"]
        o, t30 = m.get("ontem") or {}, m.get("ult30") or {}
        linhas.append(f"{c['nome']}: ontem {_brl(o.get('custo'))} e {o.get('conversoes', 0):g} conversão(ões); "
                      f"30 dias CPA {_brl(t30.get('cpa')) if t30.get('cpa') else '—'}")
        if m.get("rastreamento_suspeito"):
            linhas.append(f"  ⚠️ {c['nome']}: cliques sem nenhuma conversão — conferir rastreamento")
    n = len(acoes())
    if n:
        linhas.append(f"{n} proposta(s) do Google Ads para você aprovar")
    return linhas

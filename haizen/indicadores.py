"""Indicadores de mídia paga por período, direto das APIs (sem Claude): Meta Ads e Google Ads.

Para a página de cada conta: totais do período, comparação com o período anterior de mesmo
tamanho, série por dia (ou semana/mês em períodos longos), campanhas e quebras (plataforma,
dispositivo, idade). Fica em cache por alguns minutos para trocar de período sem esperar.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
import urllib.parse

_CACHE: dict = {}
_TRAVA = threading.Lock()
CACHE_SEG = 600
MAX_DIAS = 731


# ── período ─────────────────────────────────────────────────────────────────
def periodo(ini: str = "", fim: str = "", hoje: dt.date | None = None) -> tuple[dt.date, dt.date, dt.date, dt.date]:
    """(ini, fim, ini_anterior, fim_anterior). Padrão: últimos 30 dias até ontem."""
    hoje = hoje or dt.date.today()
    try:
        f = dt.date.fromisoformat(fim) if fim else hoje - dt.timedelta(days=1)
        i = dt.date.fromisoformat(ini) if ini else f - dt.timedelta(days=29)
    except ValueError:
        raise ValueError("datas no formato AAAA-MM-DD") from None
    f = min(f, hoje)
    if i > f:
        i, f = f, i
    if (f - i).days + 1 > MAX_DIAS:
        raise ValueError("período de no máximo 2 anos")
    n = (f - i).days + 1
    fa = i - dt.timedelta(days=1)
    return i, f, fa - dt.timedelta(days=n - 1), fa


def agrupamento(ini: dt.date, fim: dt.date) -> str:
    n = (fim - ini).days + 1
    return "dia" if n <= 62 else "semana" if n <= 200 else "mes"


def _chave_grupo(d: dt.date, grupo: str) -> str:
    if grupo == "semana":
        return (d - dt.timedelta(days=d.weekday())).isoformat()
    if grupo == "mes":
        return d.replace(day=1).isoformat()
    return d.isoformat()


def _var(a, b):
    try:
        return round((a - b) / b * 100, 1) if a is not None and b else None
    except TypeError:
        return None


def _div(a, b, casas=2):
    return round(a / b, casas) if a and b else None


def _cache(chave: tuple, gerar):
    with _TRAVA:
        x = _CACHE.get(chave)
        if x and time.time() - x[0] < CACHE_SEG:
            return x[1]
    r = gerar()
    with _TRAVA:
        _CACHE[chave] = (time.time(), r)
        if len(_CACHE) > 60:
            for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:20]:
                _CACHE.pop(k, None)
    return r


def limpar_cache() -> None:
    with _TRAVA:
        _CACHE.clear()


def _serie(linhas: dict[str, dict], ini: dt.date, fim: dt.date, somar, finalizar) -> list[dict]:
    """Preenche os dias sem dado com zero e agrupa por semana/mês em períodos longos."""
    grupo = agrupamento(ini, fim)
    grupos: dict[str, dict] = {}
    d = ini
    while d <= fim:
        k = _chave_grupo(d, grupo)
        grupos.setdefault(k, {})
        somar(grupos[k], linhas.get(d.isoformat()) or {})
        d += dt.timedelta(days=1)
    return [{"dia": k, **finalizar(v)} for k, v in grupos.items()]


# ── Meta Ads ────────────────────────────────────────────────────────────────
_COMPRAS = ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase")
_LEADS = ("lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead")
_CONVERSAS = ("onsite_conversion.messaging_conversation_started_7d",)
_CAMPOS_META = "spend,impressions,reach,clicks,inline_link_clicks,frequency,actions,action_values"
RESULTADOS_META = {"compras": "Compras", "conversas": "Conversas iniciadas", "leads": "Leads",
                   "cliques_link": "Cliques no link"}


def _acao(lista, tipos) -> float:
    por_tipo = {a.get("action_type"): a.get("value") for a in lista or []}
    for t in tipos:
        if t in por_tipo:
            try:
                return float(por_tipo[t] or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def meta_linha(l: dict) -> dict:
    """Números brutos de uma linha do Insights."""
    return {"gasto": _f(l.get("spend")), "impressoes": _f(l.get("impressions")), "alcance": _f(l.get("reach")),
            "cliques": _f(l.get("clicks")), "cliques_link": _f(l.get("inline_link_clicks")),
            "compras": _acao(l.get("actions"), _COMPRAS), "valor": _acao(l.get("action_values"), _COMPRAS),
            "leads": _acao(l.get("actions"), _LEADS), "conversas": _acao(l.get("actions"), _CONVERSAS),
            "frequencia": _f(l.get("frequency"))}


def _meta_somar(acc: dict, x: dict) -> None:
    for k in ("gasto", "impressoes", "cliques", "cliques_link", "compras", "valor", "leads", "conversas", "alcance"):
        acc[k] = acc.get(k, 0) + x.get(k, 0)


def meta_resumo(x: dict, principal: str) -> dict:
    g, imp, res = x.get("gasto", 0), x.get("impressoes", 0), x.get(principal, 0)
    return {"gasto": round(g, 2), "impressoes": int(imp), "alcance": int(x.get("alcance", 0)),
            "cliques": int(x.get("cliques", 0)), "cliques_link": int(x.get("cliques_link", 0)),
            "compras": round(x.get("compras", 0), 2), "valor": round(x.get("valor", 0), 2),
            "leads": round(x.get("leads", 0), 2), "conversas": round(x.get("conversas", 0), 2),
            "resultados": round(res, 2), "custo_resultado": _div(g, res),
            "ctr": _div(x.get("cliques_link", 0) * 100, imp), "cpc": _div(g, x.get("cliques_link", 0)),
            "cpm": _div(g * 1000, imp), "roas": _div(x.get("valor", 0), g),
            "frequencia": round(x["frequencia"], 2) if x.get("frequencia") else _div(imp, x.get("alcance", 0))}


def escolher_resultado(tot: dict, objetivo: str = "") -> str:
    o = (objetivo or "").lower()
    for chave, palavras in (("compras", ("venda", "compra", "e-commerce", "loja")),
                            ("conversas", ("mensage", "whatsapp", "conversa", "direct")),
                            ("leads", ("lead", "cadastro", "formul"))):
        if any(p in o for p in palavras) and tot.get(chave):
            return chave
    for chave in ("compras", "leads", "conversas"):
        if tot.get(chave, 0) >= 1:
            return chave
    return "cliques_link"


def _meta_get(caminho: str, **params) -> list[dict]:
    from haizen.trafego import envio
    tk = envio.token()
    if not tk:
        raise envio.ErroEnvio("cadastre o token do Meta Ads em Tráfego → Configurar para ver os indicadores")
    params["access_token"] = tk
    url = f"{envio.GRAPH}/{caminho}?{urllib.parse.urlencode(params)}"
    linhas: list[dict] = []
    for _ in range(20):
        r = envio._http("GET", url, timeout=120)
        linhas += r.get("data") or []
        url = ((r.get("paging") or {}).get("next")) or ""
        if not url:
            break
    return linhas


def _faixa(i: dt.date, f: dt.date) -> str:
    return json.dumps({"since": i.isoformat(), "until": f.isoformat()})


def meta(conta_id: str, ini: str = "", fim: str = "", objetivo: str = "") -> dict:
    i, f, ia, fa = periodo(ini, fim)
    return _cache(("meta", conta_id, i, f, objetivo), lambda: _meta(conta_id, i, f, ia, fa, objetivo))


def _meta(conta_id: str, i, f, ia, fa, objetivo: str) -> dict:
    from haizen.trafego import envio
    act = envio._act(conta_id)
    tot = (_meta_get(f"{act}/insights", fields=_CAMPOS_META, time_range=_faixa(i, f)) or [{}])[0]
    tot_a = (_meta_get(f"{act}/insights", fields=_CAMPOS_META, time_range=_faixa(ia, fa)) or [{}])[0]
    dias = _meta_get(f"{act}/insights", fields=_CAMPOS_META, time_range=_faixa(i, f), time_increment=1, limit=500)
    camp = _meta_get(f"{act}/insights", fields="campaign_id,campaign_name,objective," + _CAMPOS_META, level="campaign",
                     time_range=_faixa(i, f), limit=200)
    camp_a = _meta_get(f"{act}/insights", fields="campaign_id," + _CAMPOS_META, level="campaign",
                       time_range=_faixa(ia, fa), limit=200)
    quebras = {}
    for nome, br in (("plataforma", "publisher_platform"), ("idade", "age"), ("genero", "gender")):
        try:
            quebras[nome] = _meta_get(f"{act}/insights", fields=_CAMPOS_META, breakdowns=br,
                                      time_range=_faixa(i, f), limit=100)
        except Exception:  # noqa: BLE001
            quebras[nome] = []
    try:
        status = {c["id"]: c.get("effective_status") for c in
                  _meta_get(f"{act}/campaigns", fields="id,effective_status,daily_budget", limit=300)}
    except Exception:  # noqa: BLE001
        status = {}
    bruto, bruto_a = meta_linha(tot), meta_linha(tot_a)
    principal = escolher_resultado(bruto, objetivo)
    total, anterior = meta_resumo(bruto, principal), meta_resumo(bruto_a, principal)
    por_dia = {l.get("date_start"): meta_linha(l) for l in dias}

    def fim_grupo(acc):
        r = meta_resumo(acc, principal)
        return {k: r[k] for k in ("gasto", "resultados", "custo_resultado", "impressoes", "cliques_link", "ctr",
                                  "cpc", "cpm", "valor", "roas")}
    serie = _serie(por_dia, i, f, _meta_somar, fim_grupo)
    ant_c = {l.get("campaign_id"): meta_resumo(meta_linha(l), principal) for l in camp_a}
    campanhas = []
    for l in camp:
        r = meta_resumo(meta_linha(l), principal)
        a = ant_c.get(l.get("campaign_id")) or {}
        campanhas.append({"id": l.get("campaign_id"), "nome": l.get("campaign_name"), "objetivo": l.get("objective"),
                          "status": status.get(l.get("campaign_id"), ""), **r,
                          "var_gasto": _var(r["gasto"], a.get("gasto")),
                          "var_resultados": _var(r["resultados"], a.get("resultados")),
                          "var_custo_resultado": _var(r["custo_resultado"], a.get("custo_resultado"))})
    campanhas.sort(key=lambda c: -c["gasto"])

    def quebra(linhas, campo, nomes=None):
        out = []
        for l in linhas:
            r = meta_resumo(meta_linha(l), principal)
            rot = str(l.get(campo) or "—")
            out.append({"nome": (nomes or {}).get(rot, rot), "gasto": r["gasto"], "resultados": r["resultados"],
                        "custo_resultado": r["custo_resultado"], "impressoes": r["impressoes"], "ctr": r["ctr"]})
        return sorted(out, key=lambda x: -x["gasto"])
    plataformas = {"facebook": "Facebook", "instagram": "Instagram", "audience_network": "Audience Network",
                   "messenger": "Messenger", "threads": "Threads"}
    genero = {"male": "Homens", "female": "Mulheres", "unknown": "Não informado"}
    return {
        "plataforma": "meta", "conta": conta_id, "moeda": "BRL",
        "periodo": {"ini": i.isoformat(), "fim": f.isoformat(), "dias": (f - i).days + 1, "agrupamento": agrupamento(i, f)},
        "anterior": {"ini": ia.isoformat(), "fim": fa.isoformat()},
        "resultado": principal, "resultado_nome": RESULTADOS_META[principal],
        "total": total, "total_anterior": anterior,
        "variacao": {k: _var(total[k], anterior[k]) for k in total if isinstance(total[k], (int, float))},
        "serie": serie, "campanhas": campanhas[:60],
        "quebras": {"plataforma": quebra(quebras["plataforma"], "publisher_platform", plataformas),
                    "idade": sorted(quebra(quebras["idade"], "age"), key=lambda x: x["nome"]),
                    "genero": quebra(quebras["genero"], "gender", genero)},
        "gerado_em": time.time()}


# ── Google Ads ──────────────────────────────────────────────────────────────
_MET_G = ("metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions, "
          "metrics.conversions_value")


def _g_linha(m: dict) -> dict:
    return {"costMicros": _f(m.get("costMicros")), "conversions": _f(m.get("conversions")),
            "conversionsValue": _f(m.get("conversionsValue")), "clicks": _f(m.get("clicks")),
            "impressions": _f(m.get("impressions"))}


def _g_somar(acc: dict, x: dict) -> None:
    for k in ("costMicros", "conversions", "conversionsValue", "clicks", "impressions"):
        acc[k] = acc.get(k, 0) + x.get(k, 0)


def _g_resumo(x: dict) -> dict:
    from haizen import googleads
    return googleads._resumo_metricas(x)


def google(conta_id: str, ini: str = "", fim: str = "") -> dict:
    i, f, ia, fa = periodo(ini, fim)
    return _cache(("google", conta_id, i, f), lambda: _google(conta_id, i, f, ia, fa))


def _google(conta_id: str, i, f, ia, fa) -> dict:
    from haizen import googleads
    from haizen.googleads import api
    c = googleads.conta(conta_id)
    p = f"segments.date BETWEEN '{i.isoformat()}' AND '{f.isoformat()}'"
    pa = f"segments.date BETWEEN '{ia.isoformat()}' AND '{fa.isoformat()}'"
    dias = api.gaql(c, f"SELECT segments.date, {_MET_G} FROM customer WHERE {p}")
    tot_a = api.gaql(c, f"SELECT {_MET_G} FROM customer WHERE {pa}")
    camp = api.gaql(c, f"""SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,
        campaign_budget.amount_micros, {_MET_G}, metrics.search_impression_share
        FROM campaign WHERE {p} AND campaign.status != 'REMOVED'""")
    camp_a = api.gaql(c, f"SELECT campaign.id, {_MET_G} FROM campaign WHERE {pa} AND campaign.status != 'REMOVED'")
    try:
        disp = api.gaql(c, f"SELECT segments.device, {_MET_G} FROM customer WHERE {p}")
    except api.ErroGoogleAds:
        disp = []
    try:
        termos = api.gaql(c, f"""SELECT search_term_view.search_term, {_MET_G} FROM search_term_view WHERE {p}
            ORDER BY metrics.cost_micros DESC LIMIT 50""")
    except api.ErroGoogleAds:
        termos = []
    por_dia = {str((l.get("segments") or {}).get("date")): _g_linha(l.get("metrics") or {}) for l in dias}
    bruto = {}
    for x in por_dia.values():
        _g_somar(bruto, x)
    bruto_a = {}
    for l in tot_a:
        _g_somar(bruto_a, _g_linha(l.get("metrics") or {}))
    total, anterior = _g_resumo(bruto), _g_resumo(bruto_a)

    def fim_grupo(acc):
        return _g_resumo(acc)
    serie = _serie(por_dia, i, f, _g_somar, fim_grupo)
    ant_c = {str((l.get("campaign") or {}).get("id")): _g_resumo(_g_linha(l.get("metrics") or {})) for l in camp_a}
    tipos = {"SEARCH": "Pesquisa", "DISPLAY": "Display", "VIDEO": "Vídeo", "PERFORMANCE_MAX": "Performance Max",
             "DEMAND_GEN": "Demand Gen", "SHOPPING": "Shopping", "MULTI_CHANNEL": "App"}
    campanhas = []
    for l in camp:
        cp, b, m = l.get("campaign") or {}, l.get("campaignBudget") or {}, l.get("metrics") or {}
        r = _g_resumo(_g_linha(m))
        a = ant_c.get(str(cp.get("id"))) or {}
        campanhas.append({"id": str(cp.get("id")), "nome": cp.get("name"), "status": cp.get("status"),
                          "tipo": tipos.get(cp.get("advertisingChannelType"), cp.get("advertisingChannelType")),
                          "orcamento_diario": round(_f(b.get("amountMicros")) / 1e6, 2), **r,
                          "parcela_impressoes": round(_f(m.get("searchImpressionShare")) * 100, 1)
                          if m.get("searchImpressionShare") not in (None, "") else None,
                          "var_custo": _var(r["custo"], a.get("custo")),
                          "var_conversoes": _var(r["conversoes"], a.get("conversoes")),
                          "var_cpa": _var(r["cpa"], a.get("cpa"))})
    campanhas.sort(key=lambda x: -x["custo"])
    nomes_disp = {"MOBILE": "Celular", "DESKTOP": "Computador", "TABLET": "Tablet", "CONNECTED_TV": "TV",
                  "OTHER": "Outros"}
    dispositivos = []
    for l in disp:
        r = _g_resumo(_g_linha(l.get("metrics") or {}))
        d = str((l.get("segments") or {}).get("device") or "")
        dispositivos.append({"nome": nomes_disp.get(d, d.title() or "—"), "custo": r["custo"], "conversoes": r["conversoes"],
                             "cpa": r["cpa"], "cliques": r["cliques"], "ctr": r["ctr"]})
    termos_out = []
    for l in termos:
        r = _g_resumo(_g_linha(l.get("metrics") or {}))
        termos_out.append({"termo": (l.get("searchTermView") or {}).get("searchTerm"), "custo": r["custo"],
                           "cliques": r["cliques"], "conversoes": r["conversoes"], "cpa": r["cpa"]})
    return {
        "plataforma": "google", "conta": c["id"], "moeda": c.get("moeda") or "BRL",
        "periodo": {"ini": i.isoformat(), "fim": f.isoformat(), "dias": (f - i).days + 1, "agrupamento": agrupamento(i, f)},
        "anterior": {"ini": ia.isoformat(), "fim": fa.isoformat()},
        "total": total, "total_anterior": anterior,
        "variacao": {k: _var(total[k], anterior[k]) for k in total if isinstance(total[k], (int, float))},
        "serie": serie, "campanhas": campanhas[:60],
        "quebras": {"dispositivo": sorted(dispositivos, key=lambda x: -x["custo"])},
        "termos": termos_out, "gerado_em": time.time()}

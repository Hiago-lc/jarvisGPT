"""Ferramentas do Meta Ads para o gestor de tráfego, pela Marketing API com o token do usuário
do sistema (o que não vence). Substitui o conector oficial da Meta, que exige um login no
navegador de cada computador e cai de tempos em tempos.

Os nomes seguem os do conector oficial (ads_get_ad_entities, ads_update_entity...) para o gestor
trabalhar do mesmo jeito. Leitura e escrita ficam separadas: na análise o Jarvis só libera as de
leitura; as de escrita só entram depois que você aprova a ação.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

try:                                      # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP  # noqa: E402
except ImportError:                       # mcp 1.x
    from mcp.server.fastmcp import FastMCP  # noqa: E402

from haizen.trafego import envio  # noqa: E402

mcp = FastMCP("meta", instructions=(
    "Meta Ads da HAIZEN pela Marketing API (token do usuário do sistema). Valores de orçamento e lance "
    "em CENTAVOS da moeda da conta (R$ 50,00 = 5000). Datas AAAA-MM-DD."))

_INSIGHTS = ("spend,impressions,reach,frequency,clicks,inline_link_clicks,ctr,cpc,cpm,actions,action_values,"
             "cost_per_action_type,purchase_roas")
_CAMPOS = {
    "campaign": "id,name,status,effective_status,objective,daily_budget,lifetime_budget,bid_strategy,"
                "special_ad_categories,buying_type,start_time,stop_time,created_time,updated_time",
    "adset": "id,name,status,effective_status,campaign_id,daily_budget,lifetime_budget,bid_strategy,bid_amount,"
             "billing_event,optimization_goal,destination_type,promoted_object,targeting,start_time,end_time,"
             "learning_stage_info,created_time,updated_time",
    "ad": "id,name,status,effective_status,campaign_id,adset_id,creative{id,name,thumbnail_url,body,title},"
          "issues_info,created_time,updated_time",
}
_ARESTA = {"campaign": "campaigns", "adset": "adsets", "ad": "ads"}


def _get(caminho: str, **params) -> dict:
    tk = envio.token()
    if not tk:
        raise RuntimeError("SEM_CONEXAO_META: cadastre o token do Meta Ads em Tráfego → Configurar")
    params = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items() if v not in (None, "")}
    params["access_token"] = tk
    return envio._http("GET", f"{envio.GRAPH}/{caminho}?{urllib.parse.urlencode(params)}", timeout=120)


def _todos(caminho: str, limite: int = 500, **params) -> list[dict]:
    r = _get(caminho, limit=min(limite, 200), **params)
    linhas = list(r.get("data") or [])
    nxt = (r.get("paging") or {}).get("next")
    while nxt and len(linhas) < limite:
        r = envio._http("GET", nxt, timeout=120)
        linhas += r.get("data") or []
        nxt = (r.get("paging") or {}).get("next")
    return linhas[:limite]


def _post(caminho: str, **params) -> dict:
    tk = envio.token()
    if not tk:
        raise RuntimeError("SEM_CONEXAO_META: cadastre o token do Meta Ads em Tráfego → Configurar")
    params = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v)) for k, v in params.items()
              if v not in (None, "")}
    params["access_token"] = tk
    return envio._http("POST", f"{envio.GRAPH}/{caminho}", urllib.parse.urlencode(params).encode(),
                       {"Content-Type": "application/x-www-form-urlencoded"}, timeout=120)


def _periodo(since: str, until: str, date_preset: str) -> dict:
    if since and until:
        return {"time_range": {"since": since, "until": until}}
    return {"date_preset": date_preset or "last_7d"}


def _insights_campo(since: str, until: str, date_preset: str) -> str:
    p = _periodo(since, until, date_preset)
    if "time_range" in p:
        tr = p["time_range"]
        return f"insights.time_range({{'since':'{tr['since']}','until':'{tr['until']}'}}){{{_INSIGHTS}}}"
    return f"insights.date_preset({p['date_preset']}){{{_INSIGHTS}}}"


# ── leitura ─────────────────────────────────────────────────────────────────
@mcp.tool()
def ads_get_ad_accounts() -> list[dict]:
    """Contas de anúncio que o token acessa: id, nome, gerenciador de negócios, moeda, status."""
    return _todos("me/adaccounts", fields="id,name,currency,account_status,business{name},amount_spent,timezone_name")


@mcp.tool()
def ads_get_ad_entities(account_id: str, level: str = "campaign", ids: list[str] | None = None,
                        since: str = "", until: str = "", date_preset: str = "last_7d",
                        only_active: bool = False, limit: int = 200) -> list[dict]:
    """Campanhas, conjuntos ou anúncios (level = campaign | adset | ad) com os números do período
    (gasto, impressões, cliques, CTR, CPC, CPM, ações e valores). `ids` filtra itens específicos.
    Período: since/until (AAAA-MM-DD) ou date_preset (today, yesterday, last_7d, last_14d, last_30d,
    this_month, last_month)."""
    level = level if level in _CAMPOS else "campaign"
    campos = _CAMPOS[level] + "," + _insights_campo(since, until, date_preset)
    if ids:
        r = _get("", ids=",".join(ids), fields=campos)
        return list(r.values()) if isinstance(r, dict) else r
    filtro = [{"field": "effective_status", "operator": "IN", "value": ["ACTIVE"]}] if only_active else None
    return _todos(f"{envio._act(account_id)}/{_ARESTA[level]}", limite=limit, fields=campos, filtering=filtro)


@mcp.tool()
def ads_insights_performance_trend(object_id: str, since: str = "", until: str = "", date_preset: str = "last_30d",
                                   level: str = "", time_increment: str = "1", breakdowns: str = "") -> list[dict]:
    """Números por dia (time_increment=1), semana (7) ou mês (monthly) de uma conta (act_...), campanha,
    conjunto ou anúncio. level = account|campaign|adset|ad para quebrar por item. breakdowns opcional
    (age, gender, publisher_platform, platform_position, region, device_platform)."""
    return _todos(f"{object_id}/insights", limite=1000, fields=_INSIGHTS + ",campaign_name,adset_name,ad_name",
                  level=level or None, time_increment=time_increment or None, breakdowns=breakdowns or None,
                  **_periodo(since, until, date_preset))


@mcp.tool()
def ads_get_creatives(account_id: str = "", ad_id: str = "", limit: int = 50) -> list[dict]:
    """Criativos (texto, título, imagem/vídeo, link, CTA) da conta ou de um anúncio."""
    campos = ("id,name,status,title,body,image_url,image_hash,thumbnail_url,video_id,call_to_action_type,"
              "object_story_spec,asset_feed_spec,effective_object_story_id")
    if ad_id:
        return [(_get(ad_id, fields=f"creative{{{campos}}}") or {}).get("creative") or {}]
    return _todos(f"{envio._act(account_id)}/adcreatives", limite=limit, fields=campos)


@mcp.tool()
def ads_get_ad_preview(ad_id: str, ad_format: str = "MOBILE_FEED_STANDARD") -> dict:
    """Link de pré-visualização de um anúncio (formatos: MOBILE_FEED_STANDARD, INSTAGRAM_STANDARD,
    INSTAGRAM_STORY, INSTAGRAM_REELS, DESKTOP_FEED_STANDARD)."""
    r = _get(f"{ad_id}/previews", ad_format=ad_format)
    corpo = ((r.get("data") or [{}])[0]).get("body", "")
    import re
    m = re.search(r'src="([^"]+)"', corpo)
    return {"formato": ad_format, "url": (m.group(1).replace("&amp;", "&") if m else "")}


@mcp.tool()
def ads_get_ad_account_pages(account_id: str) -> list[dict]:
    """Páginas do Facebook (e Instagram ligado) que a conta pode usar nos anúncios."""
    try:
        paginas = _todos(f"{envio._act(account_id)}/promote_pages", fields="id,name,instagram_business_account{id,username}")
    except envio.ErroEnvio:
        paginas = []
    return paginas or _todos("me/accounts", fields="id,name,instagram_business_account{id,username}")


@mcp.tool()
def ads_get_ad_account_custom_audiences(account_id: str) -> list[dict]:
    """Públicos personalizados e semelhantes da conta (id, nome, tipo, tamanho aproximado)."""
    return _todos(f"{envio._act(account_id)}/customaudiences", limite=300,
                  fields="id,name,subtype,approximate_count_lower_bound,approximate_count_upper_bound,"
                         "delivery_status,operation_status,time_updated")


@mcp.tool()
def ads_get_activity_log(account_id: str, since: str = "", until: str = "", limit: int = 100) -> list[dict]:
    """Histórico de alterações da conta (quem mudou orçamento, status etc. e quando)."""
    return _todos(f"{envio._act(account_id)}/activities", limite=limit, since=since or None, until=until or None,
                  fields="event_time,event_type,object_name,object_id,extra_data,actor_name")


@mcp.tool()
def ads_graph_get(object_id: str, fields: str = "", edge: str = "", params_json: str = "") -> dict:
    """Leitura livre (só GET) de um objeto da Marketing API, para o que as outras ferramentas não cobrem.
    Ex.: object_id='123', edge='adsets', fields='id,name'."""
    params = json.loads(params_json) if params_json else {}
    caminho = f"{object_id}/{edge}" if edge else object_id
    return _get(caminho, fields=fields or None, **params)


# ── escrita (só depois da sua aprovação) ────────────────────────────────────
@mcp.tool()
def ads_update_entity(entity_id: str, status: str = "", daily_budget: int = 0, lifetime_budget: int = 0,
                      name: str = "", bid_amount: int = 0, end_time: str = "", targeting_json: str = "") -> dict:
    """Altera campanha, conjunto ou anúncio: status (ACTIVE | PAUSED), daily_budget / lifetime_budget /
    bid_amount em CENTAVOS, nome, fim (ISO) ou público (targeting completo em JSON). Só o que vier preenchido."""
    campos = {"status": status or None, "daily_budget": daily_budget or None,
              "lifetime_budget": lifetime_budget or None, "name": name or None, "bid_amount": bid_amount or None,
              "end_time": end_time or None, "targeting": json.loads(targeting_json) if targeting_json else None}
    if not any(v is not None for v in campos.values()):
        raise ValueError("nada para alterar")
    r = _post(entity_id, **campos)
    return {"ok": bool(r.get("success", True)), "id": entity_id, "alterado": {k: v for k, v in campos.items() if v is not None}}


@mcp.tool()
def ads_activate_entity(entity_id: str) -> dict:
    """Ativa (publica) uma campanha, conjunto ou anúncio."""
    r = _post(entity_id, status="ACTIVE")
    return {"ok": bool(r.get("success", True)), "id": entity_id, "status": "ACTIVE"}


@mcp.tool()
def ads_create_campaign(account_id: str, name: str, objective: str, status: str = "PAUSED",
                        daily_budget: int = 0, bid_strategy: str = "", special_ad_categories: list[str] | None = None) -> dict:
    """Cria uma campanha. objective: OUTCOME_SALES | OUTCOME_LEADS | OUTCOME_ENGAGEMENT | OUTCOME_TRAFFIC |
    OUTCOME_AWARENESS | OUTCOME_APP_PROMOTION. daily_budget (centavos) só para orçamento na campanha (CBO)."""
    return _post(f"{envio._act(account_id)}/campaigns", name=name, objective=objective, status=status,
                 special_ad_categories=special_ad_categories or [], daily_budget=daily_budget or None,
                 bid_strategy=bid_strategy or None)


@mcp.tool()
def ads_create_ad_set(account_id: str, campaign_id: str, name: str, optimization_goal: str, billing_event: str,
                      targeting_json: str, status: str = "PAUSED", daily_budget: int = 0, start_time: str = "",
                      end_time: str = "", promoted_object_json: str = "", destination_type: str = "",
                      bid_strategy: str = "", bid_amount: int = 0) -> dict:
    """Cria um conjunto de anúncios. targeting_json: público completo (geo_locations, age_min, age_max,
    genders, flexible_spec, custom_audiences, publisher_platforms...). promoted_object_json para
    conversões/mensagens (pixel_id + custom_event_type, ou page_id). destination_type ex.: WHATSAPP,
    MESSENGER, WEBSITE. Orçamento em centavos (omitir se a campanha usa CBO)."""
    return _post(f"{envio._act(account_id)}/adsets", campaign_id=campaign_id, name=name, status=status,
                 optimization_goal=optimization_goal, billing_event=billing_event,
                 targeting=json.loads(targeting_json), daily_budget=daily_budget or None,
                 start_time=start_time or None, end_time=end_time or None,
                 promoted_object=json.loads(promoted_object_json) if promoted_object_json else None,
                 destination_type=destination_type or None, bid_strategy=bid_strategy or None,
                 bid_amount=bid_amount or None)


@mcp.tool()
def ads_create_creative(account_id: str, name: str, page_id: str, message: str, link: str = "",
                        headline: str = "", description: str = "", call_to_action: str = "LEARN_MORE",
                        image_hash: str = "", image_url: str = "", video_id: str = "", thumbnail_url: str = "",
                        instagram_user_id: str = "", whatsapp_number: str = "") -> dict:
    """Cria um criativo de imagem (image_hash ou image_url) ou de vídeo (video_id + thumbnail_url), com
    o texto principal (message), título, descrição, link e botão (SHOP_NOW, LEARN_MORE, SIGN_UP,
    CONTACT_US, WHATSAPP_MESSAGE, MESSAGE_PAGE, BUY_NOW...). Use os image_hash/video_id que o Jarvis
    já enviou para a conta."""
    cta = {"type": call_to_action}
    if link:
        cta["value"] = {"link": link}
    if whatsapp_number:
        cta.setdefault("value", {})["whatsapp_number"] = whatsapp_number
    if video_id:
        dados = {"video_id": video_id, "message": message, "title": headline or None, "link_description": description or None,
                 "call_to_action": cta}
        if thumbnail_url:
            dados["image_url"] = thumbnail_url
        spec = {"page_id": page_id, "video_data": {k: v for k, v in dados.items() if v}}
    else:
        if not (image_hash or image_url):
            raise ValueError("informe image_hash, image_url ou video_id")
        dados = {"message": message, "link": link or None, "name": headline or None, "description": description or None,
                 "call_to_action": cta, "image_hash": image_hash or None, "picture": image_url if not image_hash else None}
        spec = {"page_id": page_id, "link_data": {k: v for k, v in dados.items() if v}}
    if instagram_user_id:
        spec["instagram_user_id"] = instagram_user_id
    return _post(f"{envio._act(account_id)}/adcreatives", name=name, object_story_spec=spec)


@mcp.tool()
def ads_create_ad(account_id: str, adset_id: str, name: str, creative_id: str, status: str = "PAUSED") -> dict:
    """Cria um anúncio no conjunto com um criativo existente."""
    return _post(f"{envio._act(account_id)}/ads", adset_id=adset_id, name=name, status=status,
                 creative={"creative_id": creative_id})


LEITURA = ("ads_get_ad_accounts", "ads_get_ad_entities", "ads_insights_performance_trend", "ads_get_creatives",
           "ads_get_ad_preview", "ads_get_ad_account_pages", "ads_get_ad_account_custom_audiences",
           "ads_get_activity_log", "ads_graph_get")
ESCRITA = ("ads_update_entity", "ads_activate_entity", "ads_create_campaign", "ads_create_ad_set",
           "ads_create_creative", "ads_create_ad")

if __name__ == "__main__":
    mcp.run()

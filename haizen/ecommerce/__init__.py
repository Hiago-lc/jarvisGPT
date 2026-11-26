"""Gestor de e-commerce: as lojas Shopify e Tray dos clientes.

Todo dia o Jarvis lê pedidos, produtos e cupons de cada loja, calcula as
métricas aqui mesmo (sem gastar o Claude) e pede ao Claude uma análise com
propostas: cupom, promoção, preço, SEO, pausar produto. Nada muda na loja sem
você aprovar; ao aprovar, quem aplica é este código, do jeito exato que estava
na proposta (o Claude não mexe na loja).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

from haizen import store
from haizen.ecommerce import cofre

PLATAFORMAS = {"shopify": "Shopify", "tray": "Tray"}
TIPOS = {"cupom": "Cupom de desconto", "desconto_automatico": "Desconto automático", "preco_promocional": "Promoção (de/por)",
         "preco": "Mudar preço", "descricao_seo": "Descrição e SEO", "pausar_produto": "Pausar produto",
         "ativar_produto": "Ativar produto", "desativar_cupom": "Desativar cupom", "alerta": "Aviso"}
PLAYBOOK = Path(__file__).resolve().parent / "playbook.md"
TIMEOUT = 900

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ecom_lojas (
    id TEXT PRIMARY KEY,
    plataforma TEXT NOT NULL,
    nome TEXT NOT NULL,
    dominio TEXT NOT NULL,
    cliente_id INTEGER,
    ativo INTEGER NOT NULL DEFAULT 1,
    objetivo TEXT NOT NULL DEFAULT '',
    criado_em REAL NOT NULL,
    conectado_em REAL,
    ultima_analise REAL,
    erro TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ecom_analises (
    id INTEGER PRIMARY KEY,
    loja_id TEXT NOT NULL,
    criado_em REAL NOT NULL,
    metricas TEXT NOT NULL DEFAULT '{}',
    resumo TEXT NOT NULL DEFAULT '',
    saude INTEGER,
    alertas TEXT NOT NULL DEFAULT '[]',
    erro TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ecom_acoes (
    id INTEGER PRIMARY KEY,
    loja_id TEXT NOT NULL,
    analise_id INTEGER,
    tipo TEXT NOT NULL,
    titulo TEXT NOT NULL,
    motivo TEXT NOT NULL DEFAULT '',
    impacto TEXT NOT NULL DEFAULT '',
    detalhes TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'proposta',   -- proposta | aplicada | rejeitada | erro | revertida
    resultado TEXT NOT NULL DEFAULT '',
    origem TEXT NOT NULL DEFAULT 'analise',
    criado_em REAL NOT NULL,
    atualizado_em REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ecom_acoes_loja ON ecom_acoes(loja_id, status);
"""


def _garantir(con) -> None:
    con.executescript(_SCHEMA)


def _modulo(loja: dict):
    if loja["plataforma"] == "shopify":
        from haizen.ecommerce import shopify
        return shopify
    from haizen.ecommerce import tray
    return tray


# ── configuração ────────────────────────────────────────────────────────────
def _arq_config() -> Path:
    from core.data_paths import data_dir
    return Path(data_dir()) / "ecommerce.json"


PADRAO = {"horario": "07:40", "agenda_ativa": True, "ultima_rodada": ""}


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
    if "agenda_ativa" in mud:
        c["agenda_ativa"] = bool(mud["agenda_ativa"])
    if "ultima_rodada" in mud:
        c["ultima_rodada"] = str(mud["ultima_rodada"])
    if mud.get("tray_consumer_key") or mud.get("tray_consumer_secret"):
        from haizen.ecommerce import tray
        tray.salvar_app(str(mud.get("tray_consumer_key") or ""), str(mud.get("tray_consumer_secret") or ""))
    _arq_config().parent.mkdir(parents=True, exist_ok=True)
    _arq_config().write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return c


# ── lojas ───────────────────────────────────────────────────────────────────
def _slug(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:40] or "loja"


def lojas(so_ativas: bool = False) -> list[dict]:
    with store.conexao() as con:
        _garantir(con)
        rows = con.execute("SELECT l.*, c.nome cliente_nome FROM ecom_lojas l LEFT JOIN clientes c ON c.id=l.cliente_id "
                           + ("WHERE l.ativo=1 " if so_ativas else "") + "ORDER BY l.nome").fetchall()
    return [dict(r) for r in rows]


def loja(lid: str) -> dict:
    for x in lojas():
        if x["id"] == lid:
            return x
    raise KeyError("loja não encontrada")


def conectar_loja(d: dict) -> dict:
    """Cadastra (ou reconecta) uma loja e testa o acesso na hora."""
    plat = str(d.get("plataforma") or "").lower()
    if plat not in PLATAFORMAS:
        raise ValueError("plataforma: shopify ou tray")
    nome = str(d.get("nome") or "").strip()
    if plat == "shopify":
        from haizen.ecommerce import shopify
        dominio = shopify.dominio_limpo(str(d.get("dominio") or ""))
    else:
        from haizen.ecommerce import tray
        dominio = tray.api_limpa(str(d.get("dominio") or d.get("api") or ""))
    lid = str(d.get("id") or "") or f"{plat}-{_slug(nome or dominio)}"
    agora = time.time()
    with store.conexao() as con:
        _garantir(con)
        existe = con.execute("SELECT id FROM ecom_lojas WHERE id=?", (lid,)).fetchone()
        cliente = int(d["cliente_id"]) if str(d.get("cliente_id") or "").strip().isdigit() else None
        if existe:
            con.execute("UPDATE ecom_lojas SET nome=COALESCE(NULLIF(?,''),nome), dominio=?, cliente_id=COALESCE(?,cliente_id),"
                        " objetivo=COALESCE(NULLIF(?,''),objetivo), ativo=1 WHERE id=?",
                        (nome, dominio, cliente, str(d.get("objetivo") or ""), lid))
        else:
            con.execute("INSERT INTO ecom_lojas(id, plataforma, nome, dominio, cliente_id, objetivo, criado_em)"
                        " VALUES(?,?,?,?,?,?,?)", (lid, plat, nome or dominio, dominio, cliente,
                                                   str(d.get("objetivo") or ""), agora))
    lj = loja(lid)
    if plat == "shopify":
        acessos = {}
        if str(d.get("token") or "").strip():
            acessos["token"] = str(d["token"]).strip()
        elif str(d.get("client_id") or "").strip() and str(d.get("client_secret") or "").strip():
            acessos = {"client_id": str(d["client_id"]).strip(), "client_secret": str(d["client_secret"]).strip()}
        if acessos:
            cofre.gravar(lid, acessos)
    elif str(d.get("code") or "").strip():
        from haizen.ecommerce import tray
        try:
            tray.conectar(lj, str(d["code"]))
        except tray.ErroTray as e:
            _mudar_loja(lid, erro=str(e)[:400])
            raise ValueError(str(e)) from None
    try:
        info = _modulo(lj).info(lj)
    except Exception as e:  # noqa: BLE001
        _mudar_loja(lid, erro=str(e)[:400], conectado_em=None)
        raise ValueError(f"cadastrei a loja, mas o acesso não funcionou: {e}") from None
    _mudar_loja(lid, erro="", conectado_em=time.time(), nome=nome or info.get("nome") or lj["nome"])
    return loja(lid)


def _mudar_loja(lid: str, **campos) -> None:
    with store.conexao() as con:
        con.execute(f"UPDATE ecom_lojas SET {', '.join(k + '=?' for k in campos)} WHERE id=?", (*campos.values(), lid))


def editar_loja(lid: str, d: dict) -> dict:
    campos = {}
    for k in ("nome", "objetivo"):
        if k in d:
            campos[k] = str(d[k] or "").strip()
    if "cliente_id" in d:
        campos["cliente_id"] = int(d["cliente_id"]) if str(d["cliente_id"] or "").isdigit() else None
    if "ativo" in d:
        campos["ativo"] = 1 if d["ativo"] else 0
    if campos:
        _mudar_loja(lid, **campos)
    return loja(lid)


def remover_loja(lid: str) -> None:
    loja(lid)
    cofre.apagar(lid)
    with store.conexao() as con:
        con.execute("DELETE FROM ecom_acoes WHERE loja_id=? AND status='proposta'", (lid,))
        con.execute("DELETE FROM ecom_lojas WHERE id=?", (lid,))


# ── métricas (sem Claude) ───────────────────────────────────────────────────
def _janela(peds: list[dict], ini: dt.date, fim: dt.date) -> dict:
    sel = [p for p in peds if not p["cancelado"] and p["data"] and ini.isoformat() <= p["data"] <= fim.isoformat()]
    fat = sum(p["total"] for p in sel)
    return {"faturamento": round(fat, 2), "pedidos": len(sel), "ticket": round(fat / len(sel), 2) if sel else 0,
            "desconto": round(sum(p["desconto"] for p in sel), 2)}


def _var(a: float, b: float) -> float | None:
    return round((a - b) / b * 100, 1) if b else None


def metricas(peds: list[dict], prods: list[dict], cups: list[dict], visitas: dict | None = None,
             hoje: dt.date | None = None) -> dict:
    hoje = hoje or dt.date.today()
    d = lambda n: hoje - dt.timedelta(days=n)  # noqa: E731
    j7, p7, j30, p30 = _janela(peds, d(6), hoje), _janela(peds, d(13), d(7)), _janela(peds, d(29), hoje), \
        _janela(peds, d(59), d(30))
    ontem = _janela(peds, d(1), d(1))
    validos = [p for p in peds if not p["cancelado"] and p["data"]]
    por_dia = defaultdict(lambda: [0.0, 0])
    for p in validos:
        if p["data"] >= d(29).isoformat():
            por_dia[p["data"]][0] += p["total"]
            por_dia[p["data"]][1] += 1
    nomes = {str(x["id"]): x["nome"] for x in prods}
    vend = defaultdict(lambda: {"qtd30": 0, "receita30": 0.0, "qtd7": 0, "qtdp7": 0, "ultima": ""})
    for p in validos:
        for i in p["itens"]:
            chave = str(i["produto_id"] or i["nome"])
            v = vend[chave]
            nomes.setdefault(chave, i["nome"])
            v["ultima"] = max(v["ultima"], p["data"])
            if p["data"] >= d(29).isoformat():
                v["qtd30"] += i["qtd"]
                v["receita30"] += i["valor"]
            if p["data"] >= d(6).isoformat():
                v["qtd7"] += i["qtd"]
            elif p["data"] >= d(13).isoformat():
                v["qtdp7"] += i["qtd"]
    por_id = {str(x["id"]): x for x in prods}
    top = sorted(({"id": k, "nome": nomes.get(k, k), "qtd30": v["qtd30"], "receita30": round(v["receita30"], 2),
                   "qtd7": v["qtd7"], "qtd7_antes": v["qtdp7"], "estoque": (por_id.get(k) or {}).get("estoque"),
                   "preco": (por_id.get(k) or {}).get("preco")}
                  for k, v in vend.items() if v["qtd30"]), key=lambda x: -x["receita30"])
    receita_total = sum(x["receita30"] for x in top) or 1
    acumulado, campeoes = 0.0, []
    for x in top:
        if acumulado / receita_total >= 0.8 and len(campeoes) >= 3:
            break
        campeoes.append(x["id"])
        acumulado += x["receita30"]
    queda = [x for x in top if x["qtd7_antes"] >= 3 and x["qtd7"] < x["qtd7_antes"] * 0.5]
    estoque_baixo = []
    for x in top:
        est = x["estoque"]
        if est is None:
            continue
        media = x["qtd30"] / 30
        cobertura = round(est / media, 1) if media else None
        if cobertura is not None and cobertura < 10:
            estoque_baixo.append({**x, "dias_de_estoque": cobertura})
    vendidos = set(vend)
    parados = [{"id": str(p["id"]), "nome": p["nome"], "estoque": p["estoque"], "preco": p["preco"],
                "criado": p["criado"], "ultima_venda": vend[str(p["id"])]["ultima"] if str(p["id"]) in vend else ""}
               for p in prods if p["ativo"] and (p["estoque"] is None or p["estoque"] > 0)
               and str(p["id"]) not in {k for k, v in vend.items() if v["qtd30"]}
               and (not p["criado"] or p["criado"] <= d(30).isoformat())]
    parados.sort(key=lambda x: -(x["estoque"] or 0))
    sem_estoque = [{"id": str(p["id"]), "nome": p["nome"]} for p in prods if p["ativo"] and p["estoque"] == 0]
    seo_fraco = [{"id": str(p["id"]), "nome": p["nome"], "seo_titulo": p["seo_titulo"], "seo_descricao": p["seo_descricao"]}
                 for p in prods if str(p["id"]) in vendidos and (not p["seo_titulo"] or not p["seo_descricao"])][:10]
    cupons_uso = defaultdict(lambda: {"pedidos": 0, "desconto": 0.0, "receita": 0.0})
    for p in validos:
        if p["data"] >= d(29).isoformat():
            for c in p["cupons"]:
                cupons_uso[c]["pedidos"] += 1
                cupons_uso[c]["desconto"] += p["desconto"]
                cupons_uso[c]["receita"] += p["total"]
    return {
        "dia": hoje.isoformat(), "ontem": ontem, "ult7": j7, "ant7": p7, "ult30": j30, "ant30": p30,
        "var7": {k: _var(j7[k], p7[k]) for k in ("faturamento", "pedidos", "ticket")},
        "var30": {k: _var(j30[k], p30[k]) for k in ("faturamento", "pedidos", "ticket")},
        "por_dia": [{"dia": (d(29 - i)).isoformat(), "faturamento": round(por_dia[(d(29 - i)).isoformat()][0], 2),
                     "pedidos": por_dia[(d(29 - i)).isoformat()][1]} for i in range(30)],
        "visitas": visitas or {}, "produtos_ativos": sum(1 for p in prods if p["ativo"]), "produtos_total": len(prods),
        "top": top[:15], "campeoes": campeoes, "em_queda": queda[:10], "estoque_baixo": estoque_baixo[:10],
        "parados": parados[:25], "parados_total": len(parados), "sem_estoque": sem_estoque[:15],
        "sem_estoque_total": len(sem_estoque), "seo_fraco": seo_fraco,
        "cupons_usados": sorted(({"codigo": k, **{a: round(b, 2) for a, b in v.items()}} for k, v in cupons_uso.items()),
                                key=lambda x: -x["pedidos"])[:10],
        "cupons_ativos": [c for c in cups if c.get("status") == "active"][:15],
    }


def coletar(lj: dict, hoje: dt.date | None = None) -> dict:
    hoje = hoje or dt.date.today()
    m = _modulo(lj)
    peds = m.pedidos(lj, hoje - dt.timedelta(days=59))
    prods = m.produtos(lj)
    cups = m.cupons(lj)
    vis = m.visitas(lj, 30)
    return metricas(peds, prods, cups, vis, hoje)


# ── datas do varejo ─────────────────────────────────────────────────────────
def _n_domingo(ano: int, mes: int, n: int) -> dt.date:
    d = dt.date(ano, mes, 1)
    d += dt.timedelta(days=(6 - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def _black_friday(ano: int) -> dt.date:
    d = dt.date(ano, 11, 1)
    d += dt.timedelta(days=(4 - d.weekday()) % 7)
    return d + dt.timedelta(weeks=3)


def datas_comerciais(hoje: dt.date, dias: int = 45) -> list[dict]:
    out = []
    for ano in (hoje.year, hoje.year + 1):
        bf = _black_friday(ano)
        for nome, data in (("Dia do Consumidor", dt.date(ano, 3, 15)), ("Dia das Mães", _n_domingo(ano, 5, 2)),
                           ("Dia dos Namorados", dt.date(ano, 6, 12)), ("Dia dos Pais", _n_domingo(ano, 8, 2)),
                           ("Dia do Cliente", dt.date(ano, 9, 15)), ("Dia das Crianças", dt.date(ano, 10, 12)),
                           ("Black Friday", bf), ("Cyber Monday", bf + dt.timedelta(days=3)),
                           ("Natal", dt.date(ano, 12, 25))):
            if hoje <= data <= hoje + dt.timedelta(days=dias):
                out.append({"data": data.isoformat(), "nome": nome, "faltam_dias": (data - hoje).days})
    return sorted(out, key=lambda x: x["data"])


# ── análise com o Claude ────────────────────────────────────────────────────
def _pasta() -> Path:
    from core.data_paths import data_dir
    p = Path(data_dir()) / "ecommerce"
    p.mkdir(parents=True, exist_ok=True)
    return p


def prompt_analise(lj: dict, m: dict, hoje: dt.date) -> str:
    leve = {k: v for k, v in m.items() if k != "por_dia"}
    leve["por_dia_ultimos_14"] = m["por_dia"][-14:]
    return f"""{PLAYBOOK.read_text(encoding='utf-8')}

---
Hoje é {hoje.isoformat()}. Loja: {lj['nome']} ({PLATAFORMAS[lj['plataforma']]}), cliente da agência: {lj.get('cliente_nome') or '—'}.
Objetivo/observações do dono: {lj.get('objetivo') or 'não informado'}.
Datas comerciais nos próximos 45 dias: {json.dumps(datas_comerciais(hoje), ensure_ascii=False)}
{'' if lj['plataforma'] == 'shopify' else 'Esta loja é Tray: não existe desconto_automatico (use cupom) nem dados de visitas/conversão.'}

Números da loja (calculados dos pedidos e do catálogo; valores em reais):
{json.dumps(leve, ensure_ascii=False)}

Use os ids EXATOS que aparecem acima em produto_id/produtos/cupom_id. Responda SÓ com JSON:
{{"resumo": "3 a 5 frases diretas para o dono da agência: como a loja está e o que mais importa agora",
  "saude": 0-100,
  "alertas": ["avisos curtos que não mudam a loja (ex.: repor estoque do X)"],
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
    modelo = uso.modelo("ecommerce")
    args = ["-p", "Analise a loja descrita na entrada e responda só com o JSON pedido.", "--output-format", "json",
            "--permission-mode", "dontAsk", *(["--model", modelo] if modelo else [])]
    return executor._rodar_claude(args, prompt, _pasta(), TIMEOUT, origem="ecommerce", referencia=referencia)


def _data_ok(x) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(x or "")))


def validar(lj: dict, tipo: str, det: dict, ids_produtos: set[str] | None = None,
            ids_cupons: set[str] | None = None) -> dict:
    """Confere e normaliza uma ação antes de virar proposta (ou antes de aplicar)."""
    if tipo not in TIPOS:
        raise ValueError(f"tipo de ação desconhecido: {tipo}")
    det = dict(det or {})
    if tipo == "desconto_automatico" and lj["plataforma"] != "shopify":
        raise ValueError("desconto automático só existe na Shopify: use cupom")
    if tipo in ("cupom", "desconto_automatico"):
        det["tipo"] = "valor" if det.get("tipo") == "valor" else "percentual"
        det["valor"] = float(det.get("valor") or 0)
        if det["valor"] <= 0 or (det["tipo"] == "percentual" and det["valor"] > 80):
            raise ValueError("valor do desconto fora do razoável")
        if tipo == "cupom":
            det["codigo"] = re.sub(r"[^A-Z0-9_-]", "", str(det.get("codigo") or "").upper())
            if len(det["codigo"]) < 3:
                raise ValueError("código do cupom inválido")
        det["produtos"] = [str(p) for p in det.get("produtos") or []]
        if ids_produtos is not None and any(p not in ids_produtos for p in det["produtos"]):
            raise ValueError("produto do cupom não existe na loja")
    if tipo in ("preco_promocional", "preco", "descricao_seo", "pausar_produto", "ativar_produto"):
        det["produto_id"] = str(det.get("produto_id") or "")
        if not det["produto_id"] or (ids_produtos is not None and det["produto_id"] not in ids_produtos):
            raise ValueError("produto não encontrado na loja")
    if tipo == "preco_promocional":
        det["preco_promocional"] = float(det.get("preco_promocional") or 0)
        if det["preco_promocional"] <= 0:
            raise ValueError("preço promocional inválido")
    if tipo == "preco":
        det["preco_novo"] = float(det.get("preco_novo") or 0)
        if det["preco_novo"] <= 0:
            raise ValueError("preço inválido")
    if tipo == "descricao_seo" and not any(det.get(k) for k in ("seo_titulo", "seo_descricao", "descricao_html")):
        raise ValueError("faltou o texto novo")
    if tipo == "desativar_cupom":
        det["cupom_id"] = str(det.get("cupom_id") or "")
        if not det["cupom_id"] or (ids_cupons is not None and det["cupom_id"] not in ids_cupons):
            raise ValueError("cupom não encontrado")
    for k in ("inicio", "fim"):
        if det.get(k) and not _data_ok(det[k]):
            raise ValueError(f"data '{k}' fora do formato AAAA-MM-DD")
    return det


def analisar(lid: str, hoje: dt.date | None = None) -> dict:
    hoje = hoje or dt.date.today()
    lj = loja(lid)
    try:
        m = coletar(lj, hoje)
    except Exception as e:  # noqa: BLE001
        _mudar_loja(lid, erro=str(e)[:400])
        raise
    texto = _claude(prompt_analise(lj, m, hoje), f"{lj['nome']} {hoje.isoformat()}")
    r = _json(texto)
    ids_p = {str(x["id"]) for x in m["top"] + m["parados"] + m["estoque_baixo"] + m["em_queda"] + m["seo_fraco"]
             + m["sem_estoque"]}
    ids_c = {str(c["id"]) for c in m["cupons_ativos"]}
    nomes = {str(x["id"]): x["nome"] for x in m["top"] + m["parados"] + m["estoque_baixo"] + m["em_queda"]
             + m["seo_fraco"] + m["sem_estoque"]}
    agora = time.time()
    with store.conexao() as con:
        _garantir(con)
        cur = con.execute("INSERT INTO ecom_analises(loja_id, criado_em, metricas, resumo, saude, alertas) VALUES(?,?,?,?,?,?)",
                          (lid, agora, json.dumps(m, ensure_ascii=False), str(r.get("resumo") or ""),
                           int(r["saude"]) if str(r.get("saude", "")).isdigit() else None,
                           json.dumps([str(a) for a in r.get("alertas") or []][:12], ensure_ascii=False)))
        aid = cur.lastrowid
        # As propostas antigas que você não aprovou dão lugar às novas.
        con.execute("UPDATE ecom_acoes SET status='rejeitada', resultado='substituída pela análise nova', atualizado_em=? "
                    "WHERE loja_id=? AND status='proposta' AND origem='analise'", (agora, lid))
        for a in (r.get("acoes") or [])[:8]:
            tipo = str(a.get("tipo") or "")
            try:
                det = validar(lj, tipo, a.get("detalhes") or {}, ids_p, ids_c) if tipo != "alerta" else {}
                if det.get("produto_id") in nomes:
                    det["produto_nome"] = nomes[det["produto_id"]]
            except (ValueError, TypeError) as e:
                print(f"[E-commerce] proposta descartada ({tipo}): {e}")
                continue
            con.execute("INSERT INTO ecom_acoes(loja_id, analise_id, tipo, titulo, motivo, impacto, detalhes, criado_em,"
                        " atualizado_em) VALUES(?,?,?,?,?,?,?,?,?)",
                        (lid, aid, tipo, str(a.get("titulo") or TIPOS[tipo])[:160], str(a.get("motivo") or "")[:600],
                         str(a.get("impacto") or "")[:300], json.dumps(det, ensure_ascii=False), agora, agora))
    _mudar_loja(lid, ultima_analise=agora, erro="")
    return ultima_analise(lid)


def ultima_analise(lid: str) -> dict | None:
    with store.conexao() as con:
        _garantir(con)
        r = con.execute("SELECT * FROM ecom_analises WHERE loja_id=? ORDER BY id DESC LIMIT 1", (lid,)).fetchone()
    if r is None:
        return None
    return {**dict(r), "metricas": json.loads(r["metricas"] or "{}"), "alertas": json.loads(r["alertas"] or "[]")}


# ── propostas e aplicação ───────────────────────────────────────────────────
def acoes(lid: str | None = None, status: tuple = ("proposta",), limite: int = 100) -> list[dict]:
    with store.conexao() as con:
        _garantir(con)
        sql = (f"SELECT a.*, l.nome loja_nome, l.plataforma FROM ecom_acoes a JOIN ecom_lojas l ON l.id=a.loja_id "
               f"WHERE a.status IN ({','.join('?' * len(status))})")
        args: list = list(status)
        if lid:
            sql += " AND a.loja_id=?"
            args.append(lid)
        rows = con.execute(sql + " ORDER BY a.id DESC LIMIT ?", (*args, limite)).fetchall()
    return [{**dict(r), "detalhes": json.loads(r["detalhes"] or "{}"), "tipo_nome": TIPOS.get(r["tipo"], r["tipo"])}
            for r in rows]


def acao(aid: int) -> dict:
    with store.conexao() as con:
        _garantir(con)
        r = con.execute("SELECT a.*, l.nome loja_nome, l.plataforma FROM ecom_acoes a JOIN ecom_lojas l ON l.id=a.loja_id "
                        "WHERE a.id=?", (int(aid),)).fetchone()
    if r is None:
        raise KeyError("ação não encontrada")
    return {**dict(r), "detalhes": json.loads(r["detalhes"] or "{}"), "tipo_nome": TIPOS.get(r["tipo"], r["tipo"])}


def _mudar_acao(aid: int, **campos) -> dict:
    campos["atualizado_em"] = time.time()
    if "detalhes" in campos and not isinstance(campos["detalhes"], str):
        campos["detalhes"] = json.dumps(campos["detalhes"], ensure_ascii=False)
    with store.conexao() as con:
        con.execute(f"UPDATE ecom_acoes SET {', '.join(k + '=?' for k in campos)} WHERE id=?", (*campos.values(), int(aid)))
    return acao(aid)


def propor(lid: str, tipo: str, titulo: str, motivo: str = "", detalhes: dict | None = None, origem: str = "pedido") -> dict:
    """Uma proposta feita por você ou pelo Jarvis na conversa. Fica esperando a aprovação."""
    lj = loja(lid)
    det = validar(lj, tipo, detalhes or {}) if tipo != "alerta" else {}
    if det.get("produto_id") and not det.get("produto_nome"):
        try:
            det["produto_nome"] = next((p["nome"] for p in _modulo(lj).produtos(lj) if str(p["id"]) == det["produto_id"]), "")
        except Exception:  # noqa: BLE001
            pass
    agora = time.time()
    with store.conexao() as con:
        _garantir(con)
        cur = con.execute("INSERT INTO ecom_acoes(loja_id, tipo, titulo, motivo, detalhes, origem, criado_em, atualizado_em)"
                          " VALUES(?,?,?,?,?,?,?,?)", (lid, tipo, (titulo or TIPOS[tipo])[:160], (motivo or "")[:600],
                                                      json.dumps(det, ensure_ascii=False), origem, agora, agora))
    return acao(cur.lastrowid)


def rejeitar(aid: int, nota: str = "") -> dict:
    a = acao(aid)
    if a["status"] not in ("proposta", "erro"):
        raise ValueError("esta proposta não está mais esperando aprovação (a tela foi atualizada)")
    return _mudar_acao(aid, status="rejeitada", resultado=nota[:300])


def aprovar(aid: int, detalhes: dict | None = None) -> dict:
    """Aplica na loja exatamente o que está na proposta (com os ajustes que você fez)."""
    a = acao(aid)
    if a["status"] not in ("proposta", "erro"):
        if a["status"] == "rejeitada" and str(a.get("resultado") or "").startswith("substituída"):
            raise ValueError("esta proposta foi trocada por uma análise mais nova: a tela foi atualizada com as propostas atuais")
        raise ValueError("esta ação já foi aplicada ou rejeitada (a tela foi atualizada)")
    lj = loja(a["loja_id"])
    det = validar(lj, a["tipo"], detalhes if detalhes is not None else a["detalhes"]) if a["tipo"] != "alerta" else {}
    try:
        res = _aplicar(lj, a["tipo"], det)
    except Exception as e:  # noqa: BLE001
        return _mudar_acao(aid, status="erro", detalhes=det, resultado=str(e)[:600])
    return _mudar_acao(aid, status="aplicada", detalhes={**det, "_aplicado": res}, resultado=_descrever(a["tipo"], det))


def _aplicar(lj: dict, tipo: str, det: dict) -> dict:
    m = _modulo(lj)
    if tipo == "alerta":
        return {"ok": True}
    if tipo == "cupom":
        return m.criar_cupom(lj, det)
    if tipo == "desconto_automatico":
        return m.criar_desconto_automatico(lj, det)
    if tipo == "preco_promocional":
        return m.preco_promocional(lj, det)
    if tipo == "preco":
        return m.preco(lj, det)
    if tipo == "descricao_seo":
        return m.atualizar_produto(lj, det["produto_id"], det)
    if tipo == "pausar_produto":
        return m.atualizar_produto(lj, det["produto_id"], {"status": "DRAFT" if lj["plataforma"] == "shopify" else "INACTIVE"})
    if tipo == "ativar_produto":
        return m.atualizar_produto(lj, det["produto_id"], {"status": "ACTIVE"})
    if tipo == "desativar_cupom":
        return m.desativar_cupom(lj, det["cupom_id"], bool(det.get("automatico")))
    raise ValueError(f"tipo desconhecido: {tipo}")


def _brl(v) -> str:
    return "R$ " + f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _descrever(tipo: str, d: dict) -> str:
    if tipo == "cupom":
        v = f"{d['valor']:g}%" if d["tipo"] == "percentual" else _brl(d["valor"])
        return f"Cupom {d['codigo']} criado ({v}{', até ' + d['fim'] if d.get('fim') else ''})."
    if tipo == "desconto_automatico":
        return "Desconto automático criado."
    if tipo == "preco_promocional":
        return f"Promoção ativa: {_brl(d['preco_promocional'])}{' até ' + d['fim'] if d.get('fim') else ''}."
    if tipo == "preco":
        return f"Preço alterado para {_brl(d['preco_novo'])}."
    return {"descricao_seo": "Descrição/SEO atualizados.", "pausar_produto": "Produto pausado.",
            "ativar_produto": "Produto ativado.", "desativar_cupom": "Cupom desativado.", "alerta": "Ciente."}.get(tipo, "Feito.")


def reverter_promocoes(hoje: dt.date | None = None) -> int:
    """Shopify não encerra promoção de preço sozinha: no dia seguinte ao fim, os preços voltam."""
    hoje = hoje or dt.date.today()
    feitas = 0
    for a in acoes(status=("aplicada",), limite=300):
        ap = a["detalhes"].get("_aplicado") or {}
        if a["tipo"] != "preco_promocional" or not ap.get("reverter") or not ap.get("reverter_em"):
            continue
        if ap["reverter_em"] >= hoje.isoformat():
            continue
        try:
            lj = loja(a["loja_id"])
            _modulo(lj).reverter_precos(lj, a["detalhes"]["produto_id"], ap["reverter"])
            _mudar_acao(a["id"], status="revertida", resultado=f"Promoção encerrada em {hoje.isoformat()}: preços de volta.")
            feitas += 1
        except Exception as e:  # noqa: BLE001
            print(f"[E-commerce] não reverti a promoção {a['id']}: {e}")
    return feitas


def buscar_produtos(lid: str, busca: str = "", limite: int = 20) -> list[dict]:
    """Produtos da loja pelo nome (para o Jarvis montar uma proposta com o id certo)."""
    lj = loja(lid)
    b = _slug(busca)
    out = []
    for p in _modulo(lj).produtos(lj):
        if not b or b in _slug(p["nome"]):
            out.append({k: p.get(k) for k in ("id", "nome", "preco", "preco_de", "estoque", "ativo", "link")})
            if len(out) >= limite:
                break
    return out


def listar_cupons(lid: str) -> list[dict]:
    lj = loja(lid)
    return _modulo(lj).cupons(lj)


# ── agenda diária ───────────────────────────────────────────────────────────
ESTADO = {"fazendo": "", "erro": ""}
# Uma análise por vez: duas ao mesmo tempo geravam duas levas de propostas e a primeira
# (ainda na tela) virava "substituída" — o clique dava "já foi aplicada ou rejeitada".
_UMA_POR_VEZ = threading.Lock()


def rodada(hoje: dt.date | None = None) -> dict:
    hoje = hoje or dt.date.today()
    feitas, erros = [], []
    for lj in lojas(so_ativas=True):
        if not lj.get("conectado_em"):
            continue
        ESTADO["fazendo"] = lj["nome"]
        try:
            analisar(lj["id"], hoje)
            feitas.append(lj["nome"])
        except Exception as e:  # noqa: BLE001
            erros.append(f"{lj['nome']}: {e}")
    ESTADO["fazendo"] = ""
    ESTADO["erro"] = "; ".join(erros)[:600]
    n = len(acoes())
    if feitas or erros:
        try:
            from haizen import notificar
            notificar.avisar("E-commerce analisado", f"{len(feitas)} loja(s) analisada(s); {n} proposta(s) para aprovar."
                             + (f" Erros: {len(erros)}" if erros else ""), "info" if not erros else "erro", "#/ecommerce")
        except Exception:  # noqa: BLE001
            pass
    return {"feitas": feitas, "erros": erros}


def _hora_ok(agora: dt.datetime, hhmm: str) -> bool:
    h, m = map(int, hhmm.split(":"))
    return (agora.hour, agora.minute) >= (h, m)


_AGENDA = {"thread": None}


def iniciar_agenda() -> None:
    if os.environ.get("HAIZEN_ECOMMERCE_AGENDA", "1") == "0":
        return
    if _AGENDA["thread"] and _AGENDA["thread"].is_alive():
        return

    def _laco():
        time.sleep(45)
        while True:
            try:
                agora = dt.datetime.now()
                c = config()
                reverter_promocoes(agora.date())
                if c["agenda_ativa"] and c["ultima_rodada"] != agora.date().isoformat() and _hora_ok(agora, c["horario"]):
                    salvar_config({"ultima_rodada": agora.date().isoformat()})
                    from haizen import executor
                    if executor.claude_disponivel() and lojas(so_ativas=True):
                        with _UMA_POR_VEZ:
                            rodada(agora.date())
            except Exception as e:  # noqa: BLE001
                print(f"[E-commerce] {e}")
            time.sleep(120)
    _AGENDA["thread"] = threading.Thread(target=_laco, daemon=True, name="ecommerce-agenda")
    _AGENDA["thread"].start()


def analisar_em_segundo_plano(lid: str | None = None) -> bool:
    """Começa a análise; False se já tem uma rodando."""
    if not _UMA_POR_VEZ.acquire(blocking=False):
        return False

    def _fazer():
        try:
            if lid:
                ESTADO["fazendo"] = loja(lid)["nome"]
                analisar(lid)
                ESTADO["erro"] = ""
            else:
                rodada()
        except Exception as e:  # noqa: BLE001
            ESTADO["erro"] = str(e)[:400]
        finally:
            ESTADO["fazendo"] = ""
            _UMA_POR_VEZ.release()
    threading.Thread(target=_fazer, daemon=True, name="ecommerce-analise").start()
    return True


# ── painel e resumo ─────────────────────────────────────────────────────────
def painel() -> dict:
    from haizen.ecommerce import tray
    out = []
    for lj in lojas():
        an = ultima_analise(lj["id"])
        m = (an or {}).get("metricas") or {}
        out.append({**lj, "analise": {k: (an or {}).get(k) for k in ("id", "criado_em", "resumo", "saude", "alertas")}
                    if an else None,
                    "metricas": {k: m.get(k) for k in ("ontem", "ult7", "ant7", "ult30", "var7", "var30", "visitas",
                                                        "por_dia", "top", "estoque_baixo", "parados_total",
                                                        "sem_estoque_total", "cupons_usados", "campeoes")} if m else None,
                    "propostas": acoes(lj["id"]),
                    "historico": acoes(lj["id"], ("aplicada", "erro", "revertida"), 8)})
    return {"lojas": out, "estado": ESTADO, "config": {k: v for k, v in config().items()},
            "tray_app": tray.app_configurado(), "tipos": TIPOS, "plataformas": PLATAFORMAS}


def resumo_linhas() -> list[str]:
    linhas = []
    for lj in lojas(so_ativas=True):
        an = ultima_analise(lj["id"])
        if not an:
            continue
        m = an["metricas"]
        o = m.get("ontem") or {}
        v7 = (m.get("var7") or {}).get("faturamento")
        linhas.append(f"{lj['nome']}: ontem {_brl(o.get('faturamento'))} em {o.get('pedidos', 0)} pedido(s)"
                      + (f"; 7 dias {'+' if v7 > 0 else ''}{v7:.0f}%" if isinstance(v7, (int, float)) else ""))
        for e in (m.get("estoque_baixo") or [])[:2]:
            linhas.append(f"  ⚠️ {e['nome']}: estoque para ~{e['dias_de_estoque']:g} dias")
    n = len(acoes())
    if n:
        linhas.append(f"{n} proposta(s) das lojas para você aprovar")
    return linhas

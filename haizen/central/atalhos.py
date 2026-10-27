"""Pedidos objetivos que não precisam do modelo de linguagem.

Um modelo pequeno (4B) às vezes responde "registrado com sucesso" sem chamar
a ferramenta. Para "registre a receita de R$ 600 da Cliente X, descrição Y,
vencimento hoje", tudo o que importa está na frase: o código lê e grava, e o
modelo nem entra.

Se faltar algo (valor, descrição, cliente), a resposta diz o que falta.
Se a frase não parece um registro, devolve None e o modelo segue normalmente.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata

from haizen import store

_VERBO = re.compile(r"\b(registr|adicion|lan[cç]|inclu|insir|coloqu|cadastr|anot)\w*", re.I)
_TIPO = re.compile(r"\b(receitas?|faturamentos?|despesas?|gastos?|custos?)\b", re.I)
_VALOR = re.compile(r"(?:R\$\s*(\d[\d.]*(?:,\d{1,2})?)|(\d[\d.]*(?:,\d{1,2})?)\s*(?:reais|real)\b)", re.I)
_FIM = (r"(?=\s*[,;]|\.\s|\.$|\s+(?:com\s+)?venc|\s+(?:para\s+o\s+)?dia\s|\s+j[aá]\s+(?:foi\s+)?(?:recebid|pag)"
        r"|\s+n[aã]o\s+foi|\s+(?:foi\s+)?recebid|\s+(?:foi\s+)?pag[oa]\b|\s+a\s+receber|\s+categoria|$)")
_DESCRICAO = re.compile(r"(?:descri[cç][aã]o|referente\s+(?:a|ao|à)?|ref\.)\s*:?\s*[\"“]?(.+?)[\"”]?" + _FIM, re.I)
_CATEGORIA = re.compile(r"categoria\s*:?\s*(.+?)" + _FIM, re.I)
_DATA = re.compile(r"(?:vencimento|vence|venc\.?|para\s+o\s+dia|no\s+dia|dia|data)\s*(?:em|é|:)?\s*"
                   r"(hoje|amanh[ãa]|ontem|\d{1,2}/\d{1,2}(?:/\d{2,4})?)", re.I)
_NAO_RECEBIDO = re.compile(r"n[aã]o\s+(?:foi\s+)?(?:recebid|pag)|a\s+receber|pendente|em\s+aberto", re.I)
_RECEBIDO = re.compile(r"\b(?:j[aá]\s+)?(?:recebid[oa]|pag[oa]|quitad[oa])\b", re.I)


def _plano(texto: str) -> str:
    """Sem acento, sem caixa, sem pontuação: 'Kroguer Soluções.' -> 'kroguer solucoes'."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def _cliente_na_frase(texto: str) -> dict | None:
    frase = f" {_plano(texto)} "
    achados = [c for c in store.listar_clientes()
               if (n := _plano(c["nome"])) and f" {n} " in frase]
    return max(achados, key=lambda c: len(c["nome"])) if achados else None


def _data(texto: str) -> str:
    m = _DATA.search(texto)
    hoje = dt.date.today()
    if not m:
        return hoje.isoformat()
    v = _plano(m.group(1))
    if v == "hoje":
        return hoje.isoformat()
    if v.startswith("amanh"):
        return (hoje + dt.timedelta(days=1)).isoformat()
    if v == "ontem":
        return (hoje - dt.timedelta(days=1)).isoformat()
    return m.group(1)          # DD/MM[/AAAA]: dados._data converte


def _brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _br(data: str) -> str:
    try:
        return dt.date.fromisoformat(data).strftime("%d/%m/%Y")
    except ValueError:
        return data


def registro_direto(texto: str) -> tuple[str, bool] | None:
    """(resposta, gravou) para um pedido de registro claro; None se não for um."""
    if "?" in texto or not _VERBO.search(texto):
        return None
    tipo_m, valor_m = _TIPO.search(texto), _VALOR.search(texto)
    if not tipo_m or not valor_m:
        return None
    despesa = _plano(tipo_m.group(1)).rstrip("s") in ("despesa", "gasto", "custo")
    valor = valor_m.group(1) or valor_m.group(2)
    desc_m = _DESCRICAO.search(texto)
    descricao = desc_m.group(1).strip(" \"”'") if desc_m else ""
    exemplo = ("Exemplo: \"registre a despesa de R$ 80, descrição Adobe, vencimento hoje, já paga\"."
               if despesa else
               "Exemplo: \"registre a receita de R$ 600 da Cliente X, descrição 2/2 Site, "
               "vencimento 10/11, a receber\".")
    if not descricao:
        return (f"Não registrei ainda: falta a descrição. Diga \"descrição ...\" no pedido. {exemplo}",
                False)

    from haizen.central.cerebro import _central
    args = {"acao": "registrar", "tipo": "despesas" if despesa else "receitas",
            "descricao": descricao, "valor": valor, "vencimento": _data(texto)}
    cliente = None
    if despesa:
        cat = _CATEGORIA.search(texto)
        if cat:
            args["categoria"] = cat.group(1).strip()
        args["pago"] = bool(_RECEBIDO.search(texto)) and not _NAO_RECEBIDO.search(texto)
    else:
        cliente = _cliente_na_frase(texto)
        if cliente is None:
            return ("Não registrei ainda: não reconheci o cliente. Diga o nome como está "
                    f"na tela Clientes. {exemplo}", False)
        args["cliente"] = cliente["nome"]
        args["recebido"] = bool(_RECEBIDO.search(texto)) and not _NAO_RECEBIDO.search(texto)

    resultado = _central(args)
    if not resultado.startswith("Registrado com sucesso"):
        return resultado, False
    r = json.loads(resultado.split(":", 1)[1])
    feito = r.get("pago") if despesa else r.get("recebido")
    situacao = ("paga" if feito else "a pagar") if despesa else ("recebida" if feito else "a receber")
    quem = f" de {cliente['nome']}" if cliente else ""
    return (f"Registrei a {'despesa' if despesa else 'receita'}{quem}: {r.get('descricao')}, "
            f"{_brl(float(r.get('valor') or 0))}, vencimento {_br(r.get('vencimento', ''))}, "
            f"{situacao}. Já aparece no Financeiro.", True)


# ── Google Agenda: consultar é objetivo, não precisa do modelo ──────────────
_AGENDA = re.compile(r"\b(agenda|compromissos?|reuni[oõ]es|reuni[aã]o|eventos?|calend[aá]rio|demandas)\b", re.I)
_AGENDA_MUDAR = re.compile(r"\b(marc|cri|agend[ae]\s+(?:uma|um|para|pra)|adicion|coloc|inclu|registr|desmarc|"
                           r"cancel|remarc|mud[ae]|apag)\w*", re.I)
_DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _periodo(texto: str) -> tuple[dt.date, dt.date, str]:
    """(início, fim exclusivo, nome do período) pedido na frase; hoje se nada."""
    t = _plano(texto)
    hoje = dt.date.today()
    if "proxima semana" in t or "semana que vem" in t:
        ini = hoje + dt.timedelta(days=7 - hoje.weekday())
        return ini, ini + dt.timedelta(days=7), "na próxima semana"
    if "semana" in t:
        return hoje, hoje + dt.timedelta(days=7 - hoje.weekday()), "nesta semana"
    if "depois de amanha" in t:
        d = hoje + dt.timedelta(days=2)
        return d, d + dt.timedelta(days=1), "depois de amanhã"
    if "amanha" in t:
        d = hoje + dt.timedelta(days=1)
        return d, d + dt.timedelta(days=1), "amanhã"
    return hoje, hoje + dt.timedelta(days=1), "hoje"


def _hora(inicio: dict) -> str:
    if "dateTime" in (inicio or {}):
        return dt.datetime.fromisoformat(inicio["dateTime"].replace("Z", "+00:00")).strftime("%H:%M")
    return "dia todo"


def agenda_direta(texto: str) -> str | None:
    """Resposta para "o que tenho na agenda hoje?"; None se não for consulta."""
    if not _AGENDA.search(texto) or _AGENDA_MUDAR.search(texto):
        return None
    if "demandas" in texto.lower() and not re.search(r"agenda|calend", texto, re.I):
        return None                      # "demandas" sozinho é da central, não da agenda
    ini, fim, nome = _periodo(texto)
    from zoneinfo import ZoneInfo
    fuso = ZoneInfo("America/Sao_Paulo")
    comeco = dt.datetime.combine(ini, dt.time(), fuso)
    final = dt.datetime.combine(fim, dt.time(), fuso)
    try:
        from core.google_calendar import service
        itens = service().events().list(
            calendarId="primary", timeMin=comeco.isoformat(), timeMax=final.isoformat(),
            singleEvents=True, orderBy="startTime", maxResults=30).execute(num_retries=1).get("items", [])
    except Exception as e:  # noqa: BLE001
        from core.google_calendar_errors import CalendarSetupError, diagnose
        motivo = str(e) if isinstance(e, CalendarSetupError) else diagnose(e)[1]
        return f"Não consegui ler o Google Agenda: {motivo}"
    if not itens:
        return f"Você não tem nada no Google Agenda {nome}."
    varios_dias = (fim - ini).days > 1
    linhas = []
    for ev in itens:
        inicio = ev.get("start") or {}
        quando = _hora(inicio)
        if varios_dias:
            dia = dt.date.fromisoformat((inicio.get("dateTime") or inicio.get("date"))[:10])
            quando = f"{_DIAS[dia.weekday()]} {dia.strftime('%d/%m')}, {quando}"
        linhas.append(f"{quando}: {ev.get('summary') or '(sem título)'}")
    n = len(itens)
    return (f"Você tem {n} compromisso{'s' if n > 1 else ''} {nome} no Google Agenda:\n"
            + "\n".join(linhas))


def responder_direto(texto: str) -> tuple[str, list[str]] | None:
    """Pedidos que o código resolve sozinho: (resposta, ferramentas usadas)."""
    r = registro_direto(texto)
    if r is not None:
        return r[0], (["central"] if r[1] else [])
    a = agenda_direta(texto)
    if a is not None:
        return a, ["google_agenda"]
    return None

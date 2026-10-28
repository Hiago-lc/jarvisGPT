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
_TIPO = re.compile(r"\b(receitas?|faturamentos?|despesas?|gastos?|custos?|pagamentos?|parcelas?|entradas?|"
                   r"recebimentos?|contas?|boletos?)\b", re.I)
_TIPO_DESPESA = ("despesa", "gasto", "custo", "conta", "boleto")
_VALOR = re.compile(r"(?:R\$\s*(\d[\d.]*(?:,\d{1,2})?)|(\d[\d.]*(?:,\d{1,2})?)\s*(?:reais|real)\b)", re.I)
_FIM = (r"(?=\s*[,;]|\.\s|\.$|\s+(?:com\s+)?venc|\s+(?:para\s+o\s+)?dia\s|\s+j[aá]\s+(?:foi\s+)?(?:recebid|pag)"
        r"|\s+como\s+(?:j[aá]\s+)?(?:recebid|pag|quitad)|\s+(?:a|para)\s+(?:receber|pagar)\b"
        r"|\s+n[aã]o\s+foi|\s+(?:foi\s+)?recebid|\s+(?:foi\s+)?pag[oa]\b|\s+a\s+receber|\s+categoria|$)")
_DESCRICAO = re.compile(r"(?:descri[cç][aã]o(?:\s+de(?=\s))?|referente\s+(?:a|ao|à)?|ref\.)\s*:?\s*[\"“]?(.+?)[\"”]?" + _FIM, re.I)
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


_GENERICOS = {"solucoes", "solucao", "ltda", "eireli", "digital", "comercio", "servicos", "studio", "agencia",
              "grupo", "loja", "empresa", "brasil", "store", "company", "cia", "me", "epp", "sa", "do", "da", "de"}


def _cliente_na_frase(texto: str) -> dict | None:
    """O cliente citado: pelo nome exato, ou, se nenhum bater, pelo nome
    parecido ("Khoguer Soluções" é a KROGUER SOLUÇÕES; voz e digitação erram)."""
    frase = f" {_plano(texto)} "
    clientes = store.listar_clientes()
    achados = [c for c in clientes if (n := _plano(c["nome"])) and f" {n} " in frase]
    if achados:
        return max(achados, key=lambda c: len(c["nome"]))
    from difflib import SequenceMatcher
    palavras = [w for w in frase.split() if len(w) >= 4]
    notas = []
    for c in clientes:
        nucleo = [w for w in _plano(c["nome"]).split() if w not in _GENERICOS and len(w) >= 4]
        if not nucleo:
            continue
        melhor = max((SequenceMatcher(None, nucleo[0], w).ratio() for w in palavras), default=0)
        if melhor >= 0.8:
            notas.append((melhor, c))
    notas.sort(key=lambda n: -n[0])
    if not notas or (len(notas) > 1 and notas[1][0] == notas[0][0]):
        return None
    return notas[0][1]


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
    despesa = _plano(tipo_m.group(1)).rstrip("s") in _TIPO_DESPESA
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


# ── Financeiro: dar baixa (marcar como recebida/paga o que já existe) ───────
_BAIXA_VERBO = re.compile(r"\b(coloc|coloqu|marc|marqu|mud|deix|alter|atualiz|baix|confirm|registr|p[oõ]e|ponha|"
                          r"recebi|recebemos|pagou|pagaram|paguei|quit)\w*", re.I)
_CRIAR_NOVO = re.compile(r"\b(outr[oa]s?|nov[oa]s?|mais\s+um[a]?|adicion|lan[cç]|cadastr|cri[ae])\w*", re.I)
_PARCELA = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})\b|\b(\d{1,2})[ªao°]?\s*parcela|parcela\s+(\d{1,2})\b", re.I)
_PALAVRAS_VAZIAS = {"coloque", "coloca", "como", "recebido", "recebida", "pago", "paga", "pagamento", "parcela", "marca",
                    "marque", "que", "foi", "para", "pra", "receita", "despesa", "conta", "valor", "reais", "esta", "isso"}


def baixa_direta(texto: str) -> str | None:
    """"Coloca como recebido o pagamento 2/2 da Kroguer": acha a receita que
    já existe e marca como recebida (ou a despesa, como paga). Nunca cria."""
    if "?" in texto or not _RECEBIDO.search(texto) and not re.search(r"\b(recebi|pagou|paguei|quitou)\b", texto, re.I):
        return None
    if not _BAIXA_VERBO.search(texto) or _CRIAR_NOVO.search(texto) or _NAO_RECEBIDO.search(texto):
        return None
    from haizen.central import dados
    cliente = _cliente_na_frase(texto)
    despesa = bool(re.search(r"\b(despesa|conta|boleto|gasto|custo)s?\b", texto, re.I)) and cliente is None
    if not despesa and cliente is None:
        return None
    ent = "despesas" if despesa else "receitas"
    campo = "pago" if despesa else "recebido"
    itens = dados.listar(ent, **({} if despesa else {"cliente_id": cliente["id"]}))
    if not itens:
        return None if despesa else f"Não achei nenhuma receita de {cliente['nome']} no Financeiro."
    parcela = _PARCELA.search(texto)
    valor_m = _VALOR.search(texto)
    valor = dados.reais(dados.centavos(valor_m.group(1) or valor_m.group(2))) if valor_m else None
    palavras = [w for w in _plano(texto).split() if len(w) >= 4 and w not in _PALAVRAS_VAZIAS
                and (not cliente or w not in _plano(cliente["nome"]))]

    def nota(r):
        d = _plano(r.get("descricao", ""))
        n = 0.0
        if parcela:
            num = parcela.group(1) or parcela.group(3) or parcela.group(4)
            tot = parcela.group(2)
            alvo = f"{num}/{tot}" if tot else None
            desc = (r.get("descricao") or "").replace(" ", "")
            if alvo and alvo in desc:
                n += 3
            elif re.search(rf"(?:^|\D){num}\s*/", desc) or re.search(rf"parcela\s*{num}\b|{num}\s*a\s*parcela", d):
                n += 2
            else:
                n -= 2
        if valor is not None:
            n += 1.5 if abs(float(r.get("valor") or 0) - valor) < 0.01 else -1
        n += sum(0.5 for w in palavras if w in d)
        return n
    candidatos = sorted(((nota(r), r) for r in itens), key=lambda x: -x[0])
    melhor = candidatos[0][0]
    if (parcela or valor is not None or palavras) and melhor <= 0:
        quem = f" de {cliente['nome']}" if cliente else ""
        return f"Não achei essa {'despesa' if despesa else 'receita'}{quem}. Confira a descrição ou o valor na tela Financeiro."
    topo = [r for n, r in candidatos if n == melhor]
    pendentes = [r for r in topo if not r.get(campo)]
    rotulo = lambda r: f"\"{r.get('descricao') or 'sem descrição'}\", {_brl(float(r.get('valor') or 0))}, vencimento {_br(r.get('vencimento', ''))}"
    if not pendentes:
        r = topo[0]
        quando = r.get("data_recebimento") or r.get("data_pagamento") or ""
        return (f"Essa já estava {'paga' if despesa else 'recebida'}{f' em {_br(quando)}' if quando else ''}: "
                f"{rotulo(r)}. Não mudei nada.")
    if len(pendentes) > 1:
        lista = "; ".join(rotulo(r) for r in pendentes[:4])
        return f"Achei mais de uma em aberto: {lista}. Qual delas? Diga a parcela (ex.: 2/2) ou o valor."
    r = pendentes[0]
    feito = dados.atualizar(ent, r["id"], {campo: True})
    quem = f" de {cliente['nome']}" if cliente else ""
    quando = feito.get("data_recebimento") or feito.get("data_pagamento") or dados.hoje()
    return (f"Marquei como {'paga' if despesa else 'recebida'} a {'despesa' if despesa else 'receita'}{quem}: "
            f"{rotulo(feito)}, {'paga' if despesa else 'recebida'} em {_br(quando)}. Não criei nenhum registro novo.")


# ── Google Agenda: consultar é objetivo, não precisa do modelo ──────────────
_AGENDA = re.compile(r"\b(agenda|compromissos?|reuni[oõ]es|reuni[aã]o|eventos?|calend[aá]rio|demandas)\b", re.I)
_AGENDA_MUDAR = re.compile(r"\b(marc|cri|agend[ae]\s+(?:uma|um|para|pra)|adicion|coloc|inclu|registr|desmarc|"
                           r"cancel|remarc|mud[ae]|apag|ajust|alter|exclu|remov)\w*", re.I)
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
    if ("demandas" in texto.lower() and not re.search(r"agenda|calend", texto, re.I)
            and not _dia_citado(texto)):
        return None                      # "demandas" sem dia é da central; "demandas de amanhã", da agenda
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
    from actions.google_agenda import lembrar_listados
    lembrar_listados(itens)
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


# ── Google Agenda: criar eventos com horário ────────────────────────────────
# "agenda" sozinho é o substantivo ("da agenda", "na agenda"); só é o verbo
# no começo da frase ou depois de "Jarvis,", "por favor", "me" ("agenda uma call...").
_CRIAR = re.compile(r"\b(?:colo[cq]u?|adicion|mar[cq]u?|agend(?!a\b)|cri[ae]|bot[ae]|inclu|anot|p[oõ]e|ponha|lan[cç]|lanqu)\w*"
                    r"|(?:^|[,.!;:]|\bjarvis|\bfavor|\bme|\bvoc[eê])\s*agenda\b", re.I)
# Pedido de mudar algo que já existe: nunca vira compromisso novo.
_JA_EXISTE = re.compile(r"\b(?:ajust|alter|mud|remar[cq]|corri[gj]|modific|reagend|troc|renome|reprogram|acert|exclu|apag|remov|cancel)\w*", re.I)
_HORA = r"(\d{1,2})(?:[:h](\d{2}))?\s*(?:h(?:oras?)?\b)?"
_FAIXA = re.compile(r"(?:\b(?:d[ae]s?|das)\s+)?" + _HORA + r"\s*(?:[àáa]s?|at[ée]|-|–|a)\s+" + _HORA, re.I)
_UMA = re.compile(r"\b(?:[àáa]s|ao meio[- ]dia)\s*" + _HORA, re.I)
_SEMANA = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
_ULTIMO_DIA: list = []          # [(data, quando)]: o dia citado há pouco na conversa


def _dia_citado(texto: str) -> dt.date | None:
    t = _plano(texto)
    hoje = dt.date.today()
    if "depois de amanha" in t:
        return hoje + dt.timedelta(days=2)
    if "amanha" in t:
        return hoje + dt.timedelta(days=1)
    if re.search(r"\bhoje\b", t):
        return hoje
    # "2/2 E-commerce" é parcela, não data: só vale com "dia", "em", "para"... antes.
    m = re.search(r"\b(?:dia|em|para|no|na|pro)\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", texto, re.I)
    if m:
        d, mes, ano = m.groups()
        ano = int(ano) + 2000 if ano and len(ano) == 2 else int(ano or hoje.year)
        try:
            data = dt.date(ano, int(mes), int(d))
            return data if m.group(3) or data >= hoje else data.replace(year=ano + 1)
        except ValueError:
            return None
    for i, nome in enumerate(_SEMANA):
        if re.search(rf"\b{nome}(?:-feira)?\b", t):
            return hoje + dt.timedelta(days=(i - hoje.weekday()) % 7 or 7)
    return None


def _lembrar_dia(texto: str) -> dt.date | None:
    """O dia deste pedido; sem dia, o citado na conversa nos últimos 15 min."""
    import time as _t
    dia = _dia_citado(texto)
    if dia is not None:
        _ULTIMO_DIA[:] = [(dia, _t.monotonic())]
        return dia
    if _ULTIMO_DIA and _t.monotonic() - _ULTIMO_DIA[0][1] < 900:
        return _ULTIMO_DIA[0][0]
    return None


_SOBRAS = re.compile(
    r"\b(?:depois de amanh[ãa]|amanh[ãa]|hoje|(?:na |no |nesta |neste |pr[oó]xim[ao] )?"
    r"(?:segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo)(?:-feira)?|"
    r"(?:dia|em|para|no|na|pro)\s+\d{1,2}/\d{1,2}(?:/\d{2,4})?|para|pra|"
    r"(?:no|na|ao)\s+(?:meu\s+)?(?:google\s+)?(?:agenda|calend[aá]rio))\b", re.I)


def _limpar_titulo(t: str) -> str:
    t = _SOBRAS.sub(" ", t)
    t = re.sub(r"^\s*(?:por favor,?|um|uma|o|a)\s+", "", " ".join(t.split()), flags=re.I)
    t = re.sub(r"^\s*(?:[-–:,;.]|\be\b)\s*", "", t.strip())
    t = re.sub(r"\s*(?:[-–:,;.]|\be\b)?\s*$", "", t)
    t = re.sub(r"\s+(?:no|na)\s+(?:google\s+)?(?:agenda|calend[aá]rio)\b.*$", "", t, flags=re.I)
    # Sobras de ligação: "de implementação" vira "implementação"; "reunião com" perde o "com".
    t = re.sub(r"^(?:(?:de|do|da|dos|das|para|pra)\s+)+", "", t.strip(), flags=re.I)
    t = re.sub(r"(?:\s+(?:de|do|da|para|pra|com|e|o|a))+$", "", t, flags=re.I)
    t = re.sub(r"^(?:o|a|os|as|um|uma)\s+", "", t, flags=re.I)
    return t.strip(" \"'“”")


def _maiuscula(t: str) -> str:
    return t[:1].upper() + t[1:] if t[:1].islower() else t


def _eventos_da_frase(texto: str) -> list[tuple[int, int, int, int, str]]:
    """[(h_ini, m_ini, h_fim, m_fim, título)]; título é o texto até o próximo horário."""
    faixas = list(_FAIXA.finditer(texto))
    saida = []
    if faixas:
        # Com um horário só, o nome pode vir antes ("agenda uma call das 14 às 15
        # com o cliente"): junta o que vem antes (sem o verbo) e o que vem depois.
        # Só o que vem DEPOIS do verbo: "vamos para a agenda, preciso que inclua..."
        # não entra no nome do compromisso.
        verbo = _CRIAR.search(texto[:faixas[0].start()])
        antes = (_limpar_titulo(texto[verbo.end() if verbo else 0:faixas[0].start()])
                 if len(faixas) == 1 else "")
        for i, m in enumerate(faixas):
            fim_titulo = faixas[i + 1].start() if i + 1 < len(faixas) else len(texto)
            h1, m1, h2, m2 = m.group(1), m.group(2), m.group(3), m.group(4)
            depois = _limpar_titulo(texto[m.end():fim_titulo])
            saida.append((int(h1), int(m1 or 0), int(h2), int(m2 or 0),
                          _maiuscula(_limpar_titulo(f"{antes} {depois}") if antes else depois)))
        return saida
    m = _UMA.search(texto)
    if m:
        h, mi = (12, 0) if "meio" in m.group(0).lower() else (int(m.group(1)), int(m.group(2) or 0))
        verbo = _CRIAR.search(texto[:m.start()])
        antes = _limpar_titulo(texto[verbo.end() if verbo else 0:m.start()])
        depois = _limpar_titulo(texto[m.end():])
        titulo = _maiuscula(_limpar_titulo(f"{antes} {depois}"))
        fim = h * 60 + mi + 60
        saida.append((h, mi, fim // 60, fim % 60, titulo))
    return saida


def criar_evento_direto(texto: str) -> tuple[str, bool] | None:
    """Cria no Google Agenda o que a frase pede; None se não for esse pedido."""
    menciona_agenda = re.search(r"agenda|calend[aá]rio|compromisso|reuni[aã]o|evento", texto, re.I)
    eventos = _eventos_da_frase(texto)
    # Só conversas de agenda ensinam "o dia de que estamos falando".
    dia = _lembrar_dia(texto) if (menciona_agenda or eventos) else _dia_citado(texto)
    if "?" in texto or not _CRIAR.search(texto) or _JA_EXISTE.search(texto):
        return None
    if not eventos or not (menciona_agenda or _dia_citado(texto) or dia):
        return None
    dia = dia or dt.date.today()
    from zoneinfo import ZoneInfo
    fuso = ZoneInfo("America/Sao_Paulo")
    from actions.google_agenda import google_agenda
    feitos, problemas = [], []
    for h1, m1, h2, m2, titulo in eventos:
        if not titulo:
            problemas.append(f"faltou o nome do compromisso das {h1:02d}:{m1:02d}")
            continue
        try:
            ini = dt.datetime.combine(dia, dt.time(h1, m1), fuso)
            fim = dt.datetime.combine(dia, dt.time(h2 % 24, m2), fuso)
        except ValueError:
            problemas.append(f"horário inválido em \"{titulo}\"")
            continue
        if fim <= ini:
            problemas.append(f"o término de \"{titulo}\" precisa ser depois do início")
            continue
        r = google_agenda({"action": "create", "title": titulo, "start": ini.isoformat(),
                           "end": fim.isoformat(), "timezone": "America/Sao_Paulo"})
        if str(r).startswith("status=done"):
            feitos.append(f"{h1:02d}:{m1:02d} às {h2:02d}:{m2:02d}: {titulo}")
        else:
            motivo = re.search(r"(?:reason|question)=(\"[^\"]*\"|\S+)", str(r))
            problemas.append(f"\"{titulo}\" não entrou ({(motivo.group(1).strip('\"') if motivo else r)[:160]})")
    quando = ("hoje" if dia == dt.date.today() else "amanhã" if dia == dt.date.today() + dt.timedelta(days=1)
              else f"{_DIAS[dia.weekday()]}, {dia.strftime('%d/%m')}")
    partes = []
    if feitos:
        partes.append(f"Coloquei no Google Agenda de {quando}:\n" + "\n".join(feitos))
    if problemas:
        partes.append("Não coloquei: " + "; ".join(problemas) + ".")
    return "\n\n".join(partes), bool(feitos)


# ── Google Agenda: remarcar e excluir ───────────────────────────────────────
_EXCLUIR = re.compile(r"\b(exclu|apag|cancel|desmar[cq]|remov|tir[ae])\w*", re.I)
_MOVER = re.compile(r"\b(mov|mud|remar[cq]|pass[ae]|adi[ae]|transf[ei]r|tro[cq]|reagend|empurr|jog[ua]|ajust|alter|modific|reprogram|acert)\w*", re.I)
_DESTINO = re.compile(r"\s(?:para|pra|pro)\s", re.I)
_CONTEXTO_AGENDA = re.compile(r"agenda|calend[aá]rio|compromisso|reuni[aã]o|evento|call", re.I)
_VAZIAS = {"o", "a", "os", "as", "de", "do", "da", "dos", "das", "meu", "minha", "um", "uma", "com",
           "evento", "compromisso", "na", "no", "e", "que", "ta", "esta", "esse", "essa", "aquele", "aquela",
           "eventos", "compromissos", "por", "favor", "todos", "todas", "tambem", "agora",
           "horario", "inicio", "hora", "agenda", "calendario", "google", "demanda", "demandas", "tarefa",
           "tarefas", "dessa", "desse", "desta", "deste", "isso", "disso", "ela", "ele", "ser", "preciso", "quero"}


def _termos(texto: str) -> list[str]:
    return [t for t in _plano(texto).split() if len(t) > 1 and t not in _VAZIAS]


def _eventos_entre(ini: dt.date, fim: dt.date) -> list[dict]:
    from zoneinfo import ZoneInfo
    from core.google_calendar import service
    fuso = ZoneInfo("America/Sao_Paulo")
    return service().events().list(
        calendarId="primary", timeMin=dt.datetime.combine(ini, dt.time(), fuso).isoformat(),
        timeMax=dt.datetime.combine(fim, dt.time(), fuso).isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=100).execute(num_retries=1).get("items", [])


def _quando_evento(ev: dict) -> str:
    ini = (ev.get("start") or {})
    if "dateTime" in ini:
        d = dt.datetime.fromisoformat(ini["dateTime"].replace("Z", "+00:00"))
        return f"{_DIAS[d.weekday()]} {d.strftime('%d/%m, %H:%M')}"
    d = dt.date.fromisoformat(ini.get("date", "")[:10])
    return f"{_DIAS[d.weekday()]} {d.strftime('%d/%m')}, dia todo"


_ULTIMO_EVENTO: dict = {}        # o compromisso de que se falou por último
_REFERENCIA = re.compile(r"\b(?:dess[ae]|dest[ae]|ess[ae]|est[ae]|del[ae]|nel[ae]|ela|ele|isso|disso)\b", re.I)


def _lembrar_evento(ev: dict) -> dict:
    import time as _t
    _ULTIMO_EVENTO.update(ev=ev, quando=_t.monotonic())
    return ev


_HORA_ALVO_ACHAR = re.compile(r"\b(?:d[ae]s?|[àáa]s?)\s+(\d{1,2})(?:[:h](\d{2}))?\s*(?:h(?:oras?)?\b)?", re.I)


def _achar_evento(alvo: str) -> tuple[dict | None, str]:
    """(evento, "") ou (None, resposta explicando o que faltou)."""
    dia = _dia_citado(alvo)
    hora = _HORA_ALVO_ACHAR.search(alvo)
    termos = _termos(_SOBRAS.sub(" ", _HORA_ALVO_ACHAR.sub(" ", alvo)))
    import time as _t
    if (not termos and not hora and _REFERENCIA.search(alvo) and _ULTIMO_EVENTO
            and _t.monotonic() - _ULTIMO_EVENTO["quando"] < 900):
        return _ULTIMO_EVENTO["ev"], ""      # "dessa tarefa": a de que acabamos de falar
    if not termos and hora:
        termos = ["*"]               # só pelo horário: "a reunião das 15h"
    if not termos:
        return None, "Qual compromisso? Diga o nome, por exemplo: \"remarca o Estudos de amanhã para 14h\"."
    hoje = dt.date.today()
    ini, fim = (dia, dia + dt.timedelta(days=1)) if dia else (hoje, hoje + dt.timedelta(days=30))
    try:
        itens = _eventos_entre(ini, fim)
    except Exception as e:  # noqa: BLE001
        from core.google_calendar_errors import CalendarSetupError, diagnose
        return None, f"Não consegui ler o Google Agenda: {e if isinstance(e, CalendarSetupError) else diagnose(e)[1]}"
    if hora:
        h, m = int(hora.group(1)), int(hora.group(2) or 0)
        no_horario = [ev for ev in itens if (ev.get("start") or {}).get("dateTime", "")[11:16] == f"{h:02d}:{m:02d}"]
        if no_horario:
            itens = no_horario
            if termos == ["*"] and len(itens) == 1:
                return _lembrar_evento(itens[0]), ""
    notas = []
    for ev in itens:
        titulo = set(_termos(ev.get("summary", "")))
        acertos = len(termos) if termos == ["*"] else sum(1 for t in termos if t in titulo)
        if acertos:
            notas.append((acertos / len(termos), ev))
    onde = "nesse dia" if dia else "nos próximos 30 dias"
    if not notas or max(n for n, _ in notas) < 0.6:
        oque = ' '.join(t for t in termos if t != "*") or f"compromisso às {hora.group(0).split()[-1]}"
        return None, f"Não achei \"{oque}\" na agenda {onde}."
    melhor = max(n for n, _ in notas)
    empatados = [ev for n, ev in notas if n == melhor]
    if len(empatados) > 1:
        from actions.google_agenda import lembrar_listados
        lembrar_listados(empatados)
        lista = "; ".join(f"{ev.get('summary', '(sem título)')} ({_quando_evento(ev)})" for ev in empatados[:5])
        return None, f"Achei mais de um: {lista}. Qual deles? Diga o dia para eu saber."
    return _lembrar_evento(empatados[0]), ""


_PRONOME = re.compile(r"\b(elas?|eles?|ess[ae]s?|est[ae]s?|tod[ao]s|isso|aquel[ae]s?|ambas?|ambos)\b", re.I)
_HORA_ALVO = re.compile(r"\b(?:d[ae]s?|[àáa]s?)\s+(\d{1,2})(?:[:h](\d{2}))?\s*(?:h(?:oras?)?\b)?", re.I)


def _alvos_sem_nome(texto: str) -> list[dict] | None:
    """Compromissos a excluir quando a frase não diz o nome: "remove elas"
    (os que acabaram de ser listados) ou "os das 14h de amanhã" (pelo horário)."""
    from actions.google_agenda import recentes
    hora = _HORA_ALVO.search(texto)
    dia = _dia_citado(texto)
    candidatos = recentes()
    if hora:
        h, m = int(hora.group(1)), int(hora.group(2) or 0)
        if not candidatos or dia:
            d = dia or dt.date.today()
            try:
                candidatos = _eventos_entre(d, d + dt.timedelta(days=1))
            except Exception:  # noqa: BLE001
                return None
        no_horario = []
        for ev in candidatos:
            ini = (ev.get("start") or {}).get("dateTime")
            if ini:
                t = dt.datetime.fromisoformat(ini.replace("Z", "+00:00"))
                if (t.hour, t.minute) == (h, m) and (not dia or t.date() == dia):
                    no_horario.append(ev)
        return no_horario
    if _PRONOME.search(texto) and candidatos:
        return candidatos
    return None


def _excluir_varios(eventos: list[dict]) -> tuple[str, bool]:
    """Exclui na hora (o usuário pediu); diz o que saiu e o que falhou."""
    from core.google_calendar import service
    api = service().events()
    feitos, falhas = [], []
    for e in eventos:
        nome = f"{e.get('summary', '(sem título)')} ({_quando_evento(e)})"
        try:
            api.delete(calendarId="primary", eventId=e["id"], sendUpdates="none").execute(num_retries=0)
            feitos.append(nome)
        except Exception as erro:  # noqa: BLE001
            from core.google_calendar_errors import diagnose
            falhas.append(f"{nome}: {diagnose(erro)[1]}")
    from actions.google_agenda import ULTIMOS
    ids = {e["id"] for e in eventos}
    ULTIMOS["itens"] = [e for e in ULTIMOS["itens"] if e.get("id") not in ids]
    partes = []
    if feitos:
        partes.append(("Excluí do Google Agenda: " if len(feitos) > 1 else "Excluí do Google Agenda ") + "; ".join(feitos) + ".")
    if falhas:
        partes.append("Não consegui excluir: " + "; ".join(falhas) + ".")
    return " ".join(partes), bool(feitos)


# ── Google Agenda: editar (nome, horário, duração, descrição, local) ────────
_VERBO_EDITAR = r"(?:mud|troc|alter|atualiz|coloc|adicion|bot|p[oõ]e|ponha|defin|edit|corri[gj]|acrescent|inclu|ajust|acert|modific|reprogram)\w*"
_CAMPOS = {
    "nome": r"nome|t[ií]tulo",
    "local": r"local|endere[çc]o|lugar",
    "descricao": r"descri[çc][ãa]o|observa[çc][ãa]o|anota[çc][ãa]o|nota|detalhes",
    "fim": r"t[ée]rmino|fim|final|hor[aá]rio\s+(?:final|de\s+t[ée]rmino|de\s+sa[ií]da)",
    "duracao": r"dura[çc][ãa]o",
    "inicio": r"in[ií]cio|hor[aá]rio(?:\s+de\s+in[ií]cio)?",
}
_SEP = r"(?:\s+(?:para|pra|por|como)\s+|\s*:\s*|\s*,\s*|\s+(?:dizendo|que\s+diz)\s+)"
_EDITAR = re.compile(
    r"\b" + _VERBO_EDITAR + r"\s+(?:(?:o|a|os|as|um|uma)\s+)?(?:(?:no|na|nos|nas)\s+)?(?P<campo>"
    + "|".join(f"(?P<{k}>{v})" for k, v in _CAMPOS.items()) + r")\s+(?P<alvo>(?:d[oae]s?|n[oae]s?|em|de|dess[ae]|dest[ae]|del[ae]|ness[ae])(?:\s+.+?)?)"
    + _SEP + r"(?P<novo>.+)$", re.I | re.S)
_RENOMEAR = re.compile(r"\brenome\w*\s+(?P<alvo>.+?)\s+(?:para|pra|como)\s+(?P<novo>.+)$", re.I | re.S)
_ESTENDER = re.compile(r"\b(?:estend|prorrog|aument|estic|encurt|diminu|reduz)\w*\s+(?P<alvo>.+?)\s+(?:at[ée]|para|pra)\s+"
                       r"(?:[àáa]s?\s+)?(?P<novo>\d.*)$", re.I | re.S)
_NUM_PALAVRA = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5}


def _minutos(texto: str) -> int | None:
    """'2 horas' -> 120; '1h30' -> 90; 'meia hora' -> 30; 'hora e meia' -> 90; '45 min' -> 45."""
    t = _plano(texto)
    for palavra, n in _NUM_PALAVRA.items():
        t = re.sub(rf"\b{palavra}\b", str(n), t)
    if re.search(r"\bmeia hora\b", t) and not re.search(r"\d", t):
        return 30
    m = re.search(r"(\d+)\s*h(?:oras?)?\s*(?:e\s*)?(\d{1,2})\s*(?:min\w*)?\b", t)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.search(r"(\d+)\s*(?:h|hora|horas)\b(\s*e\s*meia)?", t)
    if m:
        return int(m.group(1)) * 60 + (30 if m.group(2) else 0)
    if re.search(r"\bhora e meia\b", t):
        return 90
    m = re.search(r"(\d+)\s*(?:min|minutos?)\b", t)
    return int(m.group(1)) if m else None


def _hora_em(texto: str) -> tuple[int, int] | None:
    sem_data = re.sub(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", " ", texto)
    m = (re.search(r"\b(?:[àáa]s?|at[ée]|para|pra)\s+" + _HORA, sem_data, re.I)
         or re.search(r"\b" + _HORA, sem_data, re.I))
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def _novo_texto(novo: str) -> str:
    t = novo.strip().strip(" .\"'“”")
    return (t[:1].upper() + t[1:]) if t == t.lower() else t


def editar_evento_direto(texto: str) -> tuple[str, bool] | None:
    """Muda nome, horário de início/fim, duração, descrição ou local de um compromisso."""
    if "?" in texto:
        return None
    m = _RENOMEAR.search(texto)
    campo = "nome" if m else None
    if not m:
        m = _EDITAR.search(texto)
        if m:
            campo = next(k for k in _CAMPOS if m.group(k))
    if not m:
        m = _ESTENDER.search(texto)
        campo = "fim" if m else None
    if not m:
        return None
    alvo, novo = m.group("alvo"), m.group("novo")
    tem_contexto = bool(_CONTEXTO_AGENDA.search(texto) or _dia_citado(alvo))
    ev, problema = _achar_evento(alvo)
    if ev is None:
        return (problema, False) if tem_contexto else None
    return _aplicar_edicao(ev, campo, novo, alvo)


# "ajusta o horário dessa tarefa de amanhã" (sem dizer o novo): pergunta e guarda.
_PENDENTE: dict = {}
_EDITAR_SEM_VALOR = re.compile(
    r"\b" + _VERBO_EDITAR + r"\s+(?:(?:o|a|os|as)\s+)?(?P<campo>"
    + "|".join(f"(?P<{k}>{v})" for k, v in _CAMPOS.items()) + r")\s+(?P<alvo>(?:d[oae]s?|de|dess[ae]|dest[ae]|del[ae])(?:\s+.+?)?)\s*[.!]?$", re.I | re.S)
_PERGUNTA = {"nome": "Qual é o nome novo de", "local": "Qual é o local de", "descricao": "O que coloco na descrição de",
             "fim": "Para que horário fica o término de", "duracao": "Quanto tempo deve durar",
             "inicio": "Para que horário mudo"}


def _pedir_valor(texto: str) -> tuple[str, bool] | None:
    m = _EDITAR_SEM_VALOR.search(texto)
    if not m:
        return None
    campo = next(k for k in _CAMPOS if m.group(k))
    ev, problema = _achar_evento(m.group("alvo"))
    if ev is None:
        return (problema, False) if (_CONTEXTO_AGENDA.search(texto) or _dia_citado(texto)) else None
    import time as _t
    _PENDENTE.update(ev=ev, campo=campo, quando=_t.monotonic())
    return f"{_PERGUNTA[campo]} \"{ev.get('summary', '(sem título)')}\" ({_quando_evento(ev)})?", False


def _completar_pendente(texto: str) -> tuple[str, bool] | None:
    """A resposta à pergunta acima: "de 14 às 15", "para as 16h", "Revisão final"."""
    import time as _t
    if not _PENDENTE or _t.monotonic() - _PENDENTE["quando"] > 300:
        return None
    campo, ev = _PENDENTE["campo"], _PENDENTE["ev"]
    if campo in ("inicio", "fim"):
        if not (_FAIXA.search(texto) or _hora_em(texto)):
            return None
    elif campo == "duracao":
        if not _minutos(texto):
            return None
    elif "?" in texto or len(texto) > 160 or _JA_EXISTE.search(texto) or _CRIAR.search(texto):
        return None
    _PENDENTE.clear()
    novo = re.sub(r"^\s*(?:para|pra|ser|fica|que seja|seja|:)\s+", "", texto.strip(), flags=re.I)
    return _aplicar_edicao(ev, campo, novo, "")


def _aplicar_edicao(ev: dict, campo: str, novo: str, alvo: str) -> tuple[str, bool]:
    from zoneinfo import ZoneInfo
    fuso = ZoneInfo("America/Sao_Paulo")
    nome = ev.get("summary", "(sem título)")
    params = {"action": "update", "event_id": ev["id"], "timezone": "America/Sao_Paulo"}
    ini_s = (ev.get("start") or {}).get("dateTime")
    ini = dt.datetime.fromisoformat(ini_s.replace("Z", "+00:00")).astimezone(fuso) if ini_s else None
    if campo == "nome":
        params["title"] = _novo_texto(novo)
        if not params["title"]:
            return "Qual é o nome novo?", False
    elif campo == "local":
        params["location"] = _novo_texto(novo)
    elif campo == "descricao":
        params["description"] = novo.strip().strip("\"'“”")
    else:
        if ini is None and campo != "inicio":
            return f"\"{nome}\" é de dia inteiro; diga o horário de início e de fim.", False
        if campo == "duracao":
            minutos = _minutos(novo)
            if not minutos:
                return "Quanto tempo deve durar? Por exemplo: \"muda a duração do Estudos para 2 horas\".", False
            params["end"] = (ini + dt.timedelta(minutes=minutos)).isoformat()
        else:
            hora = _hora_em(novo)
            if not hora:
                return "Para que horário? Por exemplo: \"para as 15h\".", False
            dia = _dia_citado(novo) or (ini.date() if ini else _dia_citado(alvo) or dt.date.today())
            quando = dt.datetime.combine(dia, dt.time(*hora), fuso)
            if campo == "fim":
                params["end"] = quando.isoformat()
            else:
                params["start"] = quando.isoformat()
                faixa = _FAIXA.search(novo)
                if faixa:
                    params["start"] = dt.datetime.combine(dia, dt.time(int(faixa.group(1)), int(faixa.group(2) or 0)), fuso).isoformat()
                    params["end"] = dt.datetime.combine(dia, dt.time(int(faixa.group(3)) % 24, int(faixa.group(4) or 0)), fuso).isoformat()
    from actions.google_agenda import google_agenda
    r = str(google_agenda(params))
    if not r.startswith("status=done"):
        motivo = re.search(r"(?:reason|question)=(\"[^\"]*\"|\S+)", r)
        return f"Não alterei \"{nome}\": {(motivo.group(1).strip(chr(34)) if motivo else r)[:200]}", False
    if campo == "nome":
        return f"Renomeei \"{nome}\" para \"{params['title']}\".", True
    if campo == "local":
        return f"Coloquei o local de \"{nome}\": {params['location']}.", True
    if campo == "descricao":
        return f"Atualizei a descrição de \"{nome}\".", True
    from core.google_calendar import service
    novo_ev = service().events().get(calendarId="primary", eventId=ev["id"]).execute(num_retries=1)
    a = dt.datetime.fromisoformat(novo_ev["start"]["dateTime"].replace("Z", "+00:00")).astimezone(fuso)
    b = dt.datetime.fromisoformat(novo_ev["end"]["dateTime"].replace("Z", "+00:00")).astimezone(fuso)
    return f"Pronto: \"{nome}\" agora é {_DIAS[a.weekday()]} {a.strftime('%d/%m')}, das {a.strftime('%H:%M')} às {b.strftime('%H:%M')}.", True


# ── Google Agenda: ajuste de horário dito do jeito que se fala ──────────────
# "Demanda de amanhã, tem escrito Banners São Rafael, ajusta o horário dela para
# 2 às 15 e não de 2 às 17": o nome vem distorcido pelo reconhecimento de voz,
# então o compromisso é achado pelo nome aproximado E pelo horário atual citado.
_VERBO_AJUSTE = re.compile(r"\b(?:ajust|alter|mud|remar[cq]|troc|corri[gj]|modific|reagend|reprogram|acert|pass[ae]|mov[ae])\w*", re.I)


def _tarde(h1: int, h2: int | None = None) -> tuple[int, int | None]:
    """'2 às 15' é 14h às 15h; '2 às 5' (sem contexto) é 14h às 17h: agenda de trabalho."""
    if h2 is not None and h1 <= 7 and h1 + 12 <= h2:
        return h1 + 12, h2
    if h1 <= 7 and (h2 is None or h2 <= 7):
        return h1 + 12, (h2 + 12 if h2 is not None else None)
    return h1, h2


def _faixas(texto: str) -> list[dict]:
    """Cada faixa de horário citada, marcando as negadas ("e não de 2 às 17")."""
    saida = []
    for m in _FAIXA.finditer(texto):
        h1, h2 = _tarde(int(m.group(1)), int(m.group(3)))
        antes = texto[max(0, m.start() - 14):m.start()].lower()
        atual = bool(re.search(r"\b(?:n[ãa]o|est[áa]|t[áa]|era|que (?:é|e))\b[^\d]*$", antes))
        if h1 > 23 or h2 > 23:
            continue
        saida.append({"ini": (h1, int(m.group(2) or 0)), "fim": (h2, int(m.group(4) or 0)), "atual": atual})
    return saida


def _parecido(a: str, b: str) -> bool:
    from difflib import SequenceMatcher
    if a == b:
        return True
    if min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)):
        return True
    return len(a) >= 4 and len(b) >= 4 and SequenceMatcher(None, a, b).ratio() >= 0.72


def _nota_titulo(titulo: str, palavras: list[str]) -> float:
    termos = _termos(titulo)
    if not termos:
        return 0.0
    return sum(1 for t in termos if any(_parecido(t, p) for p in palavras)) / len(termos)


def ajuste_falado(texto: str) -> tuple[str, bool] | None:
    if "?" in texto or not _VERBO_AJUSTE.search(texto) or _EXCLUIR.search(texto[:_VERBO_AJUSTE.search(texto).start()]):
        return None
    faixas = _faixas(texto)
    novas = [f for f in faixas if not f["atual"]]
    if not novas:
        return None
    nova, atuais = novas[0], [f for f in faixas if f["atual"]]
    corte = _DESTINO.search(texto)
    if corte and _dia_citado(texto[corte.end():]):
        return None                  # "muda X para sexta das 10 às 11": troca de dia, fica com o remarcar
    dia = _dia_citado(texto)
    palavras = [p for p in _plano(texto).split() if len(p) >= 3]
    from zoneinfo import ZoneInfo
    fuso = ZoneInfo("America/Sao_Paulo")
    hoje = dt.date.today()
    try:
        itens = _eventos_entre(dia, dia + dt.timedelta(days=1)) if dia else _eventos_entre(hoje, hoje + dt.timedelta(days=14))
    except Exception as e:  # noqa: BLE001
        from core.google_calendar_errors import CalendarSetupError, diagnose
        return f"Não consegui ler o Google Agenda: {e if isinstance(e, CalendarSetupError) else diagnose(e)[1]}", False
    notas = []
    for ev in itens:
        ini_s, fim_s = (ev.get("start") or {}).get("dateTime"), (ev.get("end") or {}).get("dateTime")
        if not ini_s:
            continue
        a = dt.datetime.fromisoformat(ini_s.replace("Z", "+00:00")).astimezone(fuso)
        b = dt.datetime.fromisoformat(fim_s.replace("Z", "+00:00")).astimezone(fuso)
        nota = _nota_titulo(ev.get("summary", ""), palavras)
        if any(f["ini"] == (a.hour, a.minute) and f["fim"] == (b.hour, b.minute) for f in atuais):
            nota += 1.0
        elif any(f["ini"] == (a.hour, a.minute) for f in atuais):
            nota += 0.5
        if _ULTIMO_EVENTO.get("ev", {}).get("id") == ev.get("id") and _REFERENCIA.search(texto):
            nota += 0.5
        if nota >= 0.34:
            notas.append((nota, ev, a))
    tem_contexto = bool(_CONTEXTO_AGENDA.search(texto) or dia or re.search(r"\bdemanda|tarefa\b", texto, re.I))
    if not notas:
        if not tem_contexto:
            return None
        return ("Não achei esse compromisso" + (" nesse dia" if dia else " nos próximos 14 dias")
                + ". Diga o nome como está na agenda ou o horário atual dele."), False
    notas.sort(key=lambda n: -n[0])
    if len(notas) > 1 and notas[1][0] >= notas[0][0] - 0.15:
        lista = "; ".join(f"{ev.get('summary', '(sem título)')} ({_quando_evento(ev)})" for _, ev, _ in notas[:4])
        lembrar = [ev for _, ev, _ in notas[:4]]
        from actions.google_agenda import lembrar_listados
        lembrar_listados(lembrar)
        return f"Fiquei em dúvida entre: {lista}. Qual deles?", False
    _, ev, atual = notas[0]
    _lembrar_evento(ev)
    d = atual.date()
    params = {"action": "update", "event_id": ev["id"], "timezone": "America/Sao_Paulo",
              "start": dt.datetime.combine(d, dt.time(*nova["ini"]), fuso).isoformat(),
              "end": dt.datetime.combine(d, dt.time(*nova["fim"]), fuso).isoformat()}
    from actions.google_agenda import google_agenda
    r = str(google_agenda(params))
    nome = ev.get("summary", "(sem título)")
    if not r.startswith("status=done"):
        motivo = re.search(r"(?:reason|question)=(\"[^\"]*\"|\S+)", r)
        return f"Não alterei \"{nome}\": {(motivo.group(1).strip(chr(34)) if motivo else r)[:200]}", False
    return (f"Pronto: \"{nome}\" de {_DIAS[d.weekday()]} {d.strftime('%d/%m')} agora é das "
            f"{nova['ini'][0]:02d}:{nova['ini'][1]:02d} às {nova['fim'][0]:02d}:{nova['fim'][1]:02d}."), True


def mudar_evento_direto(texto: str) -> tuple[str, bool] | None:
    """Remarca ou exclui um compromisso; None se a frase não for esse pedido."""
    if "?" in texto:
        return None
    excluir = _EXCLUIR.search(texto)
    mover = _MOVER.search(texto)
    pede_excluir = bool(excluir and (not mover or excluir.start() < mover.start()))
    if not pede_excluir:
        for etapa in (_completar_pendente, ajuste_falado, editar_evento_direto, _pedir_valor):
            feito = etapa(texto)
            if feito is not None:
                return feito
    from actions.google_agenda import recentes
    listados = recentes()
    tem_contexto = bool(_CONTEXTO_AGENDA.search(texto) or _dia_citado(texto) or listados)
    if pede_excluir:
        alvo = texto[excluir.end():]
        # Colou a linha da lista ("14:00: Café da Tarde"): o título inteiro está no pedido.
        citados = [e for e in listados if len(_plano(e.get("summary", ""))) >= 4
                   and _plano(e.get("summary", "")) in _plano(alvo)]
        if citados:
            hora = re.search(r"\b(\d{1,2}):(\d{2})\b", alvo)
            if hora and len(citados) > 1:
                no_horario = [e for e in citados if (e.get("start") or {}).get("dateTime", "")[11:16]
                              == f"{int(hora.group(1)):02d}:{hora.group(2)}"]
                citados = no_horario or citados
            maior = max(len(_plano(e.get("summary", ""))) for e in citados)
            return _excluir_varios([e for e in citados if len(_plano(e.get("summary", ""))) == maior])
        if not _termos(_SOBRAS.sub(" ", _PRONOME.sub(" ", _HORA_ALVO.sub(" ", alvo)))) or not tem_contexto:
            alvos = _alvos_sem_nome(alvo)
            if alvos:
                return _excluir_varios(alvos)
            if alvos == [] and tem_contexto:
                return "Não achei compromisso nesse horário.", False
        if not tem_contexto:
            return None
        ev, problema = _achar_evento(alvo)
        if ev is None:
            # "apaga o arquivo de amanhã" não é agenda: sem palavra de agenda, segue para o modelo.
            return (problema, False) if _CONTEXTO_AGENDA.search(texto) else None
        return _excluir_varios([ev])
    if not mover or not tem_contexto:
        return None
    resto = texto[mover.end():]
    corte = _DESTINO.search(" " + resto)
    if not corte:
        return None
    alvo, destino = (" " + resto)[:corte.start()], (" " + resto)[corte.end():]
    novos = _eventos_da_frase(destino)
    novo_dia = _dia_citado(destino) or _dia_citado(" ".join(destino.split()[:3]))
    if not novos and not novo_dia:
        return None                  # "muda o título para X": fica com o modelo
    ev, problema = _achar_evento(alvo)
    if ev is None:
        return (problema, False) if _CONTEXTO_AGENDA.search(texto) else None
    ini_atual = (ev.get("start") or {}).get("dateTime")
    from zoneinfo import ZoneInfo
    fuso = ZoneInfo("America/Sao_Paulo")
    if not ini_atual:
        dia_atual = dt.date.fromisoformat((ev.get("start") or {}).get("date", "")[:10])
        dia = novo_dia or dia_atual
        params = {"action": "update", "event_id": ev["id"], "timezone": "America/Sao_Paulo"}
        if novos:
            h1, m1, h2, m2, _ = novos[0]
            params["start"] = dt.datetime.combine(dia, dt.time(h1, m1), fuso).isoformat()
            params["end"] = dt.datetime.combine(dia, dt.time(h2 % 24, m2), fuso).isoformat()
        else:
            params["date"] = dia.isoformat()
        from actions.google_agenda import google_agenda
        r = str(google_agenda(params))
        nome = ev.get("summary", "(sem título)")
        if r.startswith("status=done"):
            return f"Remarquei \"{nome}\" para {_DIAS[dia.weekday()]} {dia.strftime('%d/%m')}.", True
        motivo = re.search(r"(?:reason|question)=(\"[^\"]*\"|\S+)", r)
        return f"Não remarquei \"{nome}\": {(motivo.group(1).strip(chr(34)) if motivo else r)[:200]}", False
    atual = dt.datetime.fromisoformat(ini_atual.replace("Z", "+00:00")).astimezone(fuso)
    dia = novo_dia or atual.date()
    params = {"action": "update", "event_id": ev["id"], "timezone": "America/Sao_Paulo"}
    if novos:
        h1, m1, h2, m2, _ = novos[0]
        params["start"] = dt.datetime.combine(dia, dt.time(h1, m1), fuso).isoformat()
        if re.search(r"\d\s*(?:h\w*\s*)?(?:[àáa]s?|at[ée]|-|–|a)\s+\d", destino):
            params["end"] = dt.datetime.combine(dia, dt.time(h2 % 24, m2), fuso).isoformat()
    else:
        params["start"] = dt.datetime.combine(dia, atual.timetz().replace(tzinfo=None), fuso).isoformat()
    from actions.google_agenda import google_agenda
    r = str(google_agenda(params))
    nome = ev.get("summary", "(sem título)")
    if r.startswith("status=done"):
        quando = re.search(r"start=(\S+)", r)
        novo = dt.datetime.fromisoformat(quando.group(1).strip('"')) if quando else None
        texto_quando = f"{_DIAS[novo.weekday()]} {novo.strftime('%d/%m, %H:%M')}" if novo else "o novo horário"
        return f"Remarquei \"{nome}\" para {texto_quando}.", True
    motivo = re.search(r"(?:reason|question)=(\"[^\"]*\"|\S+)", r)
    return f"Não remarquei \"{nome}\": {(motivo.group(1).strip(chr(34)) if motivo else r)[:200]}", False


# ── Google Agenda: horários livres ──────────────────────────────────────────
_LIVRE = re.compile(r"\b(livres?|disponib\w*|dispon[ií]ve\w*|vagos?|vagas?|folgas?|encaix\w*|brecha)\b", re.I)
EXPEDIENTE = (8, 19)          # das 8h às 19h


def horarios_livres(dia: dt.date, inicio: int = EXPEDIENTE[0], fim: int = EXPEDIENTE[1],
                    minimo: int = 30) -> dict:
    """{'livres': [(ini, fim)], 'ocupados': [{'titulo', 'ini', 'fim'}]} em HH:MM.

    Eventos de dia inteiro aparecem em ocupados, mas não bloqueiam horários.
    Hoje, o que já passou não conta como livre."""
    from zoneinfo import ZoneInfo
    fuso = ZoneInfo("America/Sao_Paulo")
    agora = dt.datetime.now(fuso)
    comeco = dt.datetime.combine(dia, dt.time(inicio), fuso)
    final = dt.datetime.combine(dia, dt.time(fim), fuso)
    if dia == agora.date():
        minuto = (agora.minute // 30 + 1) * 30
        comeco = max(comeco, agora.replace(minute=0, second=0, microsecond=0) + dt.timedelta(minutes=minuto))
    ocupados, blocos = [], []
    for ev in _eventos_entre(dia, dia + dt.timedelta(days=1)):
        ini_s, fim_s = (ev.get("start") or {}), (ev.get("end") or {})
        titulo = ev.get("summary") or "(sem título)"
        if "dateTime" not in ini_s:
            ocupados.append({"titulo": titulo, "ini": "", "fim": "", "dia_todo": True})
            continue
        a = dt.datetime.fromisoformat(ini_s["dateTime"].replace("Z", "+00:00")).astimezone(fuso)
        b = dt.datetime.fromisoformat(fim_s["dateTime"].replace("Z", "+00:00")).astimezone(fuso)
        ocupados.append({"titulo": titulo, "ini": a.strftime("%H:%M"), "fim": b.strftime("%H:%M"), "dia_todo": False})
        blocos.append((a, b))
    livres, cursor = [], comeco
    for a, b in sorted(blocos):
        if a > cursor and (min(a, final) - cursor).total_seconds() >= minimo * 60:
            livres.append((cursor.strftime("%H:%M"), min(a, final).strftime("%H:%M")))
        cursor = max(cursor, b)
        if cursor >= final:
            break
    if (final - cursor).total_seconds() >= minimo * 60:
        livres.append((cursor.strftime("%H:%M"), final.strftime("%H:%M")))
    return {"dia": dia.isoformat(), "livres": livres, "ocupados": ocupados}


def disponibilidade_direta(texto: str) -> str | None:
    if _CRIAR.search(texto) and _eventos_da_frase(texto):
        return None                       # "coloca na agenda das 9 às 10 um encaixe": é criar
    if not _LIVRE.search(texto) or not (_CONTEXTO_AGENDA.search(texto) or _dia_citado(texto)
                                        or re.search(r"hor[aá]rio", texto, re.I)):
        return None
    dia = _dia_citado(texto) or dt.date.today()
    try:
        r = horarios_livres(dia)
    except Exception as e:  # noqa: BLE001
        from core.google_calendar_errors import CalendarSetupError, diagnose
        return f"Não consegui ler o Google Agenda: {e if isinstance(e, CalendarSetupError) else diagnose(e)[1]}"
    nome = ("hoje" if dia == dt.date.today() else "amanhã" if dia == dt.date.today() + dt.timedelta(days=1)
            else f"{_DIAS[dia.weekday()]}, {dia.strftime('%d/%m')}")
    if not r["livres"]:
        return f"{nome.capitalize()} não tem horário livre entre {EXPEDIENTE[0]}h e {EXPEDIENTE[1]}h."
    faixas = ", ".join(f"{a} às {b}" for a, b in r["livres"])
    return f"{nome.capitalize()} você tem livre: {faixas}."


# ── WhatsApp: o que chegou ──────────────────────────────────────────────────
_WHATS = re.compile(r"whats|\bzap\b", re.I)
_LER_WHATS = re.compile(r"\b(l[eê]|ler|leia|mostr\w*|quais|que|tem|ver|veja|confer\w*|cheg\w*|novas?|n[aã]o lidas?)\b", re.I)


def whatsapp_direto(texto: str) -> str | None:
    """'Quais mensagens chegaram no WhatsApp?' -> a lista das não lidas."""
    if not _WHATS.search(texto) or not re.search(r"mensage|conversa|n[aã]o lid|cheg", texto, re.I):
        return None
    if not _LER_WHATS.search(texto) or re.search(r"\b(respond|envi|mand|escrev|digit)\w*", texto, re.I):
        return None                      # responder/enviar fica com o modelo e a confirmação
    from actions.whatsapp import resumo_nao_lidas
    from core import whatsapp_web
    ok, _code, r = whatsapp_web.run_op({"op": "unread"}, timeout=90)
    return resumo_nao_lidas(r) if ok else f"Não consegui ler o WhatsApp: {r}"


_MEU_NOME = re.compile(r"(?:\bmeu\s+nome\s+(?:é|e|eh)|\bme\s+chamo|\b(?:pode\s+)?me\s+cham(?:a|e|ar)\s+de)\s+"
                       r"(?P<nome>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'-]{1,30})", re.I)


def nome_direto(texto: str) -> str | None:
    """"Meu nome é Hiago": guarda o nome (vale para as próximas conversas também)."""
    m = _MEU_NOME.search(texto)
    if not m or "?" in texto[m.start():]:
        return None
    nome = m.group("nome").capitalize()
    if _plano(nome) in {"nao", "sim", "voce", "jarvis", "o", "a"}:
        return None
    try:
        from memory.config_manager import get_assistant_name, save_assistant_config
        save_assistant_config(get_assistant_name(), nome)
    except Exception as erro:  # noqa: BLE001
        return f"Entendi, {nome}, mas não consegui guardar o nome: {erro}"
    return f"Anotado, {nome}. Vou te chamar assim daqui para frente."


_ITEM = re.compile(r"(?:^|\n)\s*(?:\d{1,2}\s*[).:\-–]?|[-•*])\s+(?=\S)")


def _itens(texto: str) -> tuple[str, list[str]]:
    """'Preciso de duas coisas:\n1 X\n2 Y' -> ('Preciso de duas coisas:', ['X', 'Y'])."""
    marcas = list(_ITEM.finditer(texto))
    if len(marcas) < 2:
        return texto, []
    intro = texto[:marcas[0].start()].strip()
    itens = [texto[m.end():(marcas[i + 1].start() if i + 1 < len(marcas) else len(texto))].strip()
             for i, m in enumerate(marcas)]
    return intro, [i for i in itens if i]


def responder_direto(texto: str) -> tuple[str, list[str]] | None:
    """Pedidos que o código resolve sozinho: (resposta, ferramentas usadas).

    Uma lista numerada vira um pedido por item, com uma resposta por item.
    Se nenhum item for resolvido aqui, o modelo recebe a mensagem inteira."""
    intro, itens = _itens(texto)
    if len(itens) >= 2:
        contexto = " na agenda" if re.search(r"agenda|calend", intro, re.I) else ""
        respostas, usadas, pendentes = [], [], []
        for n, item in enumerate(itens, start=1):
            r = _responder_um(item if not contexto or re.search(r"agenda|calend", item, re.I) else item + contexto)
            if r is None:
                pendentes.append((n, item))
                respostas.append(f"{n}. Não fiz este pelo atalho: \"{item[:80]}\". Mande ele sozinho que eu faço.")
            else:
                respostas.append(f"{n}. {r[0]}")
                usadas += r[1]
        if len(pendentes) == len(itens):
            return None
        return "\n".join(respostas), sorted(set(usadas))
    return _responder_um(texto)


_DESLIGAR = re.compile(r"^\W*(?:jarvis\W+)?(?:pode\s+)?(?:desliga|desligar|desligue|encerra|encerrar|encerre)"
                       r"(?:\s+(?:o\s+)?(?:jarvis|sistema|tudo|voc[eê]))?(?:\s+(?:por\s+favor|a[ií]|agora))?\W*$", re.I)


def desligar_direto(texto: str) -> str | None:
    """"Jarvis, desliga" / "desliga o Jarvis": fala a despedida e encerra tudo."""
    if not _DESLIGAR.search(texto or ""):
        return None
    import threading
    from haizen.central import servidor
    threading.Thread(target=servidor.desligar, kwargs={"espera": 3.5}, daemon=True).start()
    return "Desligando o Jarvis. Até mais!"


def _responder_um(texto: str) -> tuple[str, list[str]] | None:
    d = desligar_direto(texto)
    if d is not None:
        return d, ["sistema"]
    n = nome_direto(texto)
    if n is not None:
        return n, ["central"]
    b = baixa_direta(texto)
    if b is not None:
        return b, ["central"]
    r = registro_direto(texto)
    if r is not None:
        return r[0], (["central"] if r[1] else [])
    w = whatsapp_direto(texto)
    if w is not None:
        return w, ["whatsapp"]
    d = disponibilidade_direta(texto)
    if d is not None:
        return d, ["google_agenda"]
    m = mudar_evento_direto(texto)
    if m is not None:
        return m[0], (["google_agenda"] if m[1] else [])
    e = criar_evento_direto(texto)
    if e is not None:
        return e[0], (["google_agenda"] if e[1] else [])
    a = agenda_direta(texto)
    if a is not None:
        return a, ["google_agenda"]
    return None

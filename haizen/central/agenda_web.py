"""A tela Agenda da central: os eventos do Google Agenda para desenhar e editar.

Fala direto com a API (a mesma conexão do Jarvis). Horários chegam da página
como "AAAA-MM-DDTHH:MM" no fuso de São Paulo; dia inteiro como "AAAA-MM-DD".
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")
FERIADOS = "pt-br.brazilian#holiday@group.v.calendar.google.com"
# As 11 cores de evento do Google Agenda (colorId 1 a 11).
CORES = {"1": "#7986CB", "2": "#33B679", "3": "#8E24AA", "4": "#E67C73", "5": "#F6BF26", "6": "#F4511E",
         "7": "#039BE5", "8": "#616161", "9": "#3F51B5", "10": "#0B8043", "11": "#D50000"}
COR_PADRAO = "#039BE5"


def _erro(e: Exception) -> ValueError:
    from core.google_calendar_errors import CalendarSetupError, diagnose
    return ValueError(str(e) if isinstance(e, CalendarSetupError) else diagnose(e)[1])


def _api():
    from core.google_calendar import service
    try:
        return service().events()
    except Exception as e:  # noqa: BLE001
        raise _erro(e) from None


def _hora(v: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(v)
    return d if d.tzinfo else d.replace(tzinfo=FUSO)


def _evento(ev: dict, calendario: str) -> dict:
    ini, fim = ev.get("start") or {}, ev.get("end") or {}
    dia_todo = "date" in ini and "dateTime" not in ini
    return {"id": ev.get("id"), "titulo": ev.get("summary") or "(sem título)",
            "inicio": ini.get("date") if dia_todo else _hora(ini["dateTime"]).astimezone(FUSO).isoformat(),
            "fim": fim.get("date") if dia_todo else _hora(fim["dateTime"]).astimezone(FUSO).isoformat(),
            "dia_todo": dia_todo, "descricao": ev.get("description") or "", "local": ev.get("location") or "",
            "cor": "#0B8043" if calendario == "feriados" else CORES.get(str(ev.get("colorId") or ""), COR_PADRAO),
            "cor_id": str(ev.get("colorId") or ""),
            "link": ev.get("htmlLink") or "", "calendario": calendario,
            "editavel": calendario == "primary", "recorrente": bool(ev.get("recurringEventId"))}


def listar(de: str, ate: str) -> dict:
    """Eventos de [de, ate) da agenda principal, mais os feriados do Brasil."""
    ini = dt.datetime.combine(dt.date.fromisoformat(de), dt.time(), FUSO)
    fim = dt.datetime.combine(dt.date.fromisoformat(ate), dt.time(), FUSO)
    if not ini < fim <= ini + dt.timedelta(days=62):
        raise ValueError("Intervalo inválido (até 62 dias).")
    api = _api()
    saida, aviso = [], ""
    for cal, nome in (("primary", "primary"), (FERIADOS, "feriados")):
        token = None
        try:
            while True:
                r = api.list(calendarId=cal, timeMin=ini.isoformat(), timeMax=fim.isoformat(), singleEvents=True,
                             orderBy="startTime", maxResults=250, pageToken=token).execute(num_retries=1)
                saida += [_evento(e, nome) for e in r.get("items", []) if e.get("status") != "cancelled"]
                token = r.get("nextPageToken")
                if not token:
                    break
        except Exception as e:  # noqa: BLE001
            if nome == "primary":
                raise _erro(e) from None
            aviso = ""       # sem feriados: segue só com a agenda principal
    return {"eventos": saida, "aviso": aviso}


def _corpo(c: dict, atual: dict | None = None) -> dict:
    body: dict = {}
    if "titulo" in c:
        titulo = str(c.get("titulo") or "").strip()
        if not titulo:
            raise ValueError("Dê um nome ao evento.")
        body["summary"] = titulo[:200]
    for chave, campo, limite in (("descricao", "description", 8000), ("local", "location", 1000)):
        if chave in c:
            body[campo] = str(c.get(chave) or "")[:limite]
    if "cor_id" in c:
        body["colorId"] = str(c["cor_id"]) if str(c.get("cor_id") or "") in CORES else None
    if "inicio" in c or "fim" in c:
        dia_todo = bool(c.get("dia_todo")) if "dia_todo" in c else bool(atual and "date" in (atual.get("start") or {}))
        if dia_todo:
            a = dt.date.fromisoformat(str(c.get("inicio"))[:10])
            b = dt.date.fromisoformat(str(c.get("fim") or c.get("inicio"))[:10])
            if b <= a:
                b = a + dt.timedelta(days=1)
            body["start"] = {"date": a.isoformat(), "dateTime": None}
            body["end"] = {"date": b.isoformat(), "dateTime": None}
        else:
            a, b = _hora(str(c.get("inicio"))), _hora(str(c.get("fim")))
            if b <= a:
                raise ValueError("O fim precisa ser depois do início.")
            body["start"] = {"dateTime": a.isoformat(), "timeZone": "America/Sao_Paulo", "date": None}
            body["end"] = {"dateTime": b.isoformat(), "timeZone": "America/Sao_Paulo", "date": None}
    return body


def criar(c: dict) -> dict:
    body = _corpo({"titulo": c.get("titulo", ""), **c})
    if "start" not in body:
        raise ValueError("Diga quando é o evento.")
    for lado in ("start", "end"):
        body[lado] = {k: v for k, v in body[lado].items() if v is not None}
    try:
        ev = _api().insert(calendarId="primary", body=body, sendUpdates="none").execute(num_retries=0)
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001
        raise _erro(e) from None
    return _evento(ev, "primary")


def editar(eid: str, c: dict) -> dict:
    api = _api()
    try:
        atual = api.get(calendarId="primary", eventId=eid).execute(num_retries=1)
        ev = api.patch(calendarId="primary", eventId=eid, body=_corpo(c, atual),
                       sendUpdates="none").execute(num_retries=0)
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001
        raise _erro(e) from None
    return _evento(ev, "primary")


def excluir(eid: str) -> dict:
    try:
        _api().delete(calendarId="primary", eventId=eid, sendUpdates="none").execute(num_retries=0)
    except Exception as e:  # noqa: BLE001
        raise _erro(e) from None
    return {"ok": True}

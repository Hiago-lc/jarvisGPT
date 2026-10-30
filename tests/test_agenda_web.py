"""A tela Agenda: eventos do Google Agenda para desenhar, criar, editar e excluir."""
import datetime as dt
import unittest
from unittest.mock import patch


class _R:
    def __init__(self, v):
        self.v = v

    def execute(self, **k):
        return self.v


class _Api:
    def __init__(self):
        self.ev = {"a": {"id": "a", "summary": "Reunião", "colorId": "11",
                         "start": {"dateTime": "2026-10-28T11:00:00-03:00"}, "end": {"dateTime": "2026-10-28T12:00:00-03:00"}},
                   "b": {"id": "b", "summary": "Casa", "start": {"date": "2026-10-27"}, "end": {"date": "2026-10-28"}}}
        self.chamadas = []

    def events(self):
        return self

    def list(self, calendarId, **k):
        self.chamadas.append(calendarId)
        if "holiday" in calendarId:
            return _R({"items": [{"id": "f", "summary": "Dia do Servidor Público",
                                  "start": {"date": "2026-10-28"}, "end": {"date": "2026-10-29"}}]})
        return _R({"items": list(self.ev.values())})

    def get(self, calendarId, eventId):
        return _R(dict(self.ev[eventId]))

    def patch(self, calendarId, eventId, body, sendUpdates):
        self.corpo = body
        for k, v in body.items():
            self.ev[eventId][k] = {a: b for a, b in v.items() if b is not None} if isinstance(v, dict) else v
        return _R(dict(self.ev[eventId]))

    def insert(self, calendarId, body, sendUpdates):
        self.inserido = body
        return _R({**body, "id": "novo"})

    def delete(self, calendarId, eventId, sendUpdates):
        self.apagado = eventId
        return _R(None)


class AgendaWebTests(unittest.TestCase):
    def setUp(self):
        self.api = _Api()
        self.p = patch("core.google_calendar.service", return_value=self.api)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_list_merges_holidays_with_colors(self):
        from haizen.central import agenda_web
        r = agenda_web.listar("2026-10-25", "2026-11-01")
        por = {e["titulo"]: e for e in r["eventos"]}
        self.assertEqual(por["Reunião"]["cor"], "#D50000")
        self.assertTrue(por["Casa"]["dia_todo"])
        self.assertFalse(por["Dia do Servidor Público"]["editavel"])
        self.assertTrue(por["Reunião"]["inicio"].startswith("2026-10-28T11:00"))

    def test_move_and_resize(self):
        from haizen.central import agenda_web
        e = agenda_web.editar("a", {"inicio": "2026-10-29T15:00", "fim": "2026-10-29T16:30", "dia_todo": False})
        self.assertEqual((e["inicio"][:16], e["fim"][:16]), ("2026-10-29T15:00", "2026-10-29T16:30"))
        with self.assertRaises(ValueError):
            agenda_web.editar("a", {"inicio": "2026-10-29T15:00", "fim": "2026-10-29T14:00"})

    def test_all_day_and_timed_switch(self):
        from haizen.central import agenda_web
        e = agenda_web.editar("a", {"dia_todo": True, "inicio": "2026-10-30", "fim": "2026-10-31"})
        self.assertTrue(e["dia_todo"])
        self.assertIsNone(self.api.corpo["start"]["dateTime"])     # o Google apaga o horário

    def test_create_and_delete(self):
        from haizen.central import agenda_web
        e = agenda_web.criar({"titulo": "Gravação", "inicio": "2026-10-28T18:00", "fim": "2026-10-28T19:00", "cor_id": "3"})
        self.assertEqual(self.api.inserido["colorId"], "3")
        self.assertNotIn("date", self.api.inserido["start"])
        self.assertEqual(e["titulo"], "Gravação")
        agenda_web.excluir("a")
        self.assertEqual(self.api.apagado, "a")
        with self.assertRaises(ValueError):
            agenda_web.criar({"titulo": " ", "inicio": "2026-10-28T18:00", "fim": "2026-10-28T19:00"})


if __name__ == "__main__":
    unittest.main()

"""WhatsApp Web: ler não lidas sem abrir, ler conversa, enviar só depois do OK."""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from core import whatsapp_web as web


def _el(title=None, aria=None, text="", count=1):
    e = MagicMock()
    e.get_attribute.side_effect = lambda a: {"title": title, "aria-label": aria}.get(a)
    e.inner_text.return_value = text
    e.count.return_value = count
    e.first = e
    return e


class LerTests(unittest.TestCase):
    def setUp(self):
        self.stop = threading.Event()
        self.page = MagicMock(url="https://web.whatsapp.com/")

    def _linha(self, nome, previa, badge):
        row = MagicMock()
        spans = MagicMock()
        spans.all.return_value = [_el(nome), _el(previa)]
        b = _el(aria=badge, count=1 if badge else 0)

        def loc(sel):
            return spans if sel == "span[title]" else b
        row.locator.side_effect = loc
        return row

    def test_unread_list_reads_only_the_sidebar(self):
        rows = MagicMock()
        rows.count.return_value = 3
        rows.all.return_value = [self._linha("Padaria Sol", "Consegue até sexta?", "3 mensagens não lidas"),
                                 self._linha("Ana", "ok", None),
                                 self._linha("Marcos", "Vi o orçamento", "1 mensagem não lida")]
        side = MagicMock()
        side.first = side
        self.page.locator.side_effect = lambda sel: {"#pane-side": side,
                                                     '#pane-side [role="listitem"]': rows}[sel]
        r = web.unread_chats(self.page, self.stop)
        self.assertEqual(r, [{"contato": "Padaria Sol", "nao_lidas": 3, "previa": "Consegue até sexta?"},
                             {"contato": "Marcos", "nao_lidas": 1, "previa": "Vi o orçamento"}])
        self.page.keyboard.press.assert_not_called()

    def test_meta_line_is_parsed(self):
        self.assertEqual(web.parse_meta("[10:32, 27/10/2026] João da Silva: "),
                         {"hora": "10:32", "data": "27/10/2026", "autor": "João da Silva"})

    def test_read_chat_marks_direction(self):
        def msg(meta, texto, minha):
            m = MagicMock()
            m.get_attribute.side_effect = lambda a: meta
            m.inner_text.return_value = texto
            anc = MagicMock()
            anc.count.return_value = 1 if minha else 0
            m.locator.return_value = anc
            return m
        itens = MagicMock()
        itens.all.return_value = [msg("[09:12, 27/10/2026] Padaria Sol: ", "Oi!", False),
                                  msg("[09:40, 27/10/2026] Hiago: ", "Consigo sim", True)]
        self.page.locator.side_effect = lambda sel: itens
        with patch.object(web, "_open_chat"):
            r = web.read_chat(self.page, "Padaria Sol", self.stop)
        self.assertEqual([(m["hora"], m["de"], m["texto"]) for m in r],
                         [("09:12", "contato", "Oi!"), ("09:40", "eu", "Consigo sim")])


class EnviarTests(unittest.TestCase):
    def setUp(self):
        self.stop = threading.Event()
        self.texto = ""
        self.page = MagicMock(url="https://web.whatsapp.com/")
        self.composer = MagicMock()
        self.composer.first = self.composer
        self.composer.count.return_value = 1
        self.composer.inner_text.side_effect = lambda **k: self.texto
        self.composer.fill.side_effect = lambda v, **k: setattr(self, "texto", v)
        self.composer.press.side_effect = lambda key, **k: setattr(self, "texto", "")
        self.page.locator.side_effect = lambda sel: self.composer

    def test_send_fills_checks_and_presses_enter_once(self):
        with patch.object(web, "_open_chat"), patch.object(web, "_header_matches", return_value=True):
            self.assertEqual(web.send_message(self.page, "Padaria Sol", "Oi, tudo certo!", self.stop), "Oi, tudo certo!")
        self.composer.fill.assert_called_once_with("Oi, tudo certo!", timeout=3000)
        self.composer.press.assert_called_once_with("Enter", timeout=3000)

    def test_existing_different_draft_blocks_sending(self):
        self.texto = "rascunho antigo"
        with patch.object(web, "_open_chat"), patch.object(web, "_header_matches", return_value=True):
            with self.assertRaises(web.DraftError) as e:
                web.send_message(self.page, "Padaria Sol", "Oi", self.stop)
        self.assertEqual(e.exception.code, "existing_draft")
        self.composer.press.assert_not_called()

    def test_chat_changed_before_enter_sends_nothing(self):
        with patch.object(web, "_open_chat"), patch.object(web, "_header_matches", return_value=False):
            with self.assertRaises(web.DraftError):
                web.send_message(self.page, "Padaria Sol", "Oi", self.stop)
        self.composer.press.assert_not_called()

    def test_draft_editor_still_never_presses_enter(self):
        fonte = Path(web.__file__).read_text(encoding="utf-8")
        corpo = fonte[fonte.index("def edit_draft"):fonte.index("# ── reading")]
        self.assertNotIn("press(", corpo)


class FerramentaTests(unittest.TestCase):
    def test_reply_waits_for_the_on_screen_ok(self):
        from actions import whatsapp as wa
        from core import confirm
        pedidos = []
        with patch.object(confirm, "pending_title", return_value=""), \
             patch.object(confirm, "request", side_effect=lambda **kw: (pedidos.append(kw), "[CONFIRMATION_PENDING]")[1]), \
             patch.object(web, "run_op", return_value=(True, "ok", "Oi")) as run:
            r = wa.whatsapp({"acao": "responder", "contato": "Padaria Sol", "texto": "Oi"})
            self.assertIn("CONFIRMATION_PENDING", r)
            run.assert_not_called()                    # nada sai antes do OK
            self.assertIn("Padaria Sol", pedidos[0]["title"])
            self.assertEqual(pedidos[0]["run"](), "Enviei para Padaria Sol.")
            run.assert_called_once_with({"op": "send", "recipient": "Padaria Sol", "text": "Oi"}, timeout=45)

    def test_unread_summary(self):
        from actions import whatsapp as wa
        with patch.object(web, "run_op", return_value=(True, "ok", [{"contato": "Ana", "nao_lidas": 2, "previa": "Oi"}])):
            r = wa.whatsapp({"acao": "nao_lidas"})
        self.assertIn("Ana (2): Oi", r)

    def test_whatsapp_requests_drop_the_unconfirmed_sender(self):
        from haizen.central.cerebro import escolher_acoes
        e = escolher_acoes("responde a Padaria Sol no whatsapp dizendo que amanhã às 10h está ótimo")
        self.assertIn("whatsapp", e)
        self.assertNotIn("send_message", e)


class AtalhosTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"HAIZEN_DB": str(Path(self.tmp.name) / "h.db")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_free_slots_between_events(self):
        import datetime as dt
        from haizen.central import atalhos
        dia = dt.date.today() + dt.timedelta(days=1)
        ev = lambda a, b, t: {"summary": t, "start": {"dateTime": f"{dia}T{a}:00-03:00"}, "end": {"dateTime": f"{dia}T{b}:00-03:00"}}
        with patch.object(atalhos, "_eventos_entre", return_value=[ev("09:00", "10:00", "Café"), ev("11:00", "12:00", "Estudos"),
                                                                   {"summary": "Feriado", "start": {"date": str(dia)}}]):
            r = atalhos.horarios_livres(dia)
            self.assertEqual(r["livres"], [("08:00", "09:00"), ("10:00", "11:00"), ("12:00", "19:00")])
            self.assertTrue(any(o["dia_todo"] for o in r["ocupados"]))
            frase = atalhos.disponibilidade_direta("tenho horário livre amanhã?")
        self.assertEqual(frase, "Amanhã você tem livre: 08:00 às 09:00, 10:00 às 11:00, 12:00 às 19:00.")

    def test_creating_with_a_free_word_is_still_creating(self):
        from haizen.central import atalhos
        self.assertIsNone(atalhos.disponibilidade_direta("coloca na agenda amanhã das 9 às 10 um encaixe"))

    def test_what_arrived_on_whatsapp(self):
        from haizen.central import atalhos
        with patch.object(web, "run_op", return_value=(True, "ok", [{"contato": "Ana", "nao_lidas": 1, "previa": "Oi"}])):
            self.assertIn("Ana (1): Oi", atalhos.whatsapp_direto("quais mensagens chegaram no whatsapp?"))
        self.assertIsNone(atalhos.whatsapp_direto("responde a Ana no whatsapp dizendo oi"))

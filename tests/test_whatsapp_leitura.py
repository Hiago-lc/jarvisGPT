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
        side.count.return_value = 1
        side.is_visible.return_value = True
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
        with patch.object(web, "_open_chat"), patch.object(web, "_require_login"):
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


class ReaberturaTests(unittest.TestCase):
    """Fechar a janela do WhatsApp Web não quebra: o Jarvis reabre sozinho."""

    def _rodar(self, op, falhas_em_do):
        import queue as q
        chamadas = {"do": 0, "launch": 0}

        def do(page, payload, stop):
            chamadas["do"] += 1
            if chamadas["do"] <= falhas_em_do:
                raise RuntimeError("Target page, context or browser has been closed")
            return "ok"

        def launch(driver, stop):
            chamadas["launch"] += 1
            ctx = MagicMock()
            pagina = MagicMock(url="https://web.whatsapp.com/")
            pagina.is_closed.return_value = False
            ctx.pages = [pagina]
            return ctx
        fake_pw = MagicMock()
        with patch.object(web, "_do", side_effect=do), patch.object(web, "_launch", side_effect=launch), \
             patch.dict("sys.modules", {"playwright": MagicMock(), "playwright.sync_api": MagicMock(sync_playwright=lambda: fake_pw)}), \
             patch.object(web, "_JOBS", q.Queue()), patch.object(web, "_worker", None):
            r = web.run_op({"op": op, "recipient": "Ana", "text": "Oi", "action": "read"}, timeout=10)
        return r, chamadas

    def test_closed_window_is_reopened_and_reading_works(self):
        r, ch = self._rodar("unread", 1)
        self.assertTrue(r[0])
        self.assertEqual((ch["do"], ch["launch"]), (2, 2))

    def test_a_send_that_already_started_is_never_repeated(self):
        r, ch = self._rodar("send", 1)
        self.assertFalse(r[0])
        self.assertEqual(ch["do"], 1)
        self.assertIn("Veja na conversa se a mensagem saiu", r[2])


class FraseIncompletaTests(unittest.TestCase):
    def _motor(self, falas):
        import asyncio
        from providers.engine_pipeline import PipelineEngine

        class LLM:
            caps = {"tools": True, "tool_format": "openai"}

        class STT:
            async def transcribe(self, pcm, rate):
                return falas.pop(0)
        motor = PipelineEngine(LLM(), STT(), None, log=lambda m: None)
        enviados = []

        async def emit(m):
            pass

        async def enviar(**kw):
            enviados.append(kw["turns"]["parts"][0]["text"])
        motor._emit = emit
        motor.send_client_content = enviar
        return motor, enviados, asyncio

    def test_half_sentence_waits_and_joins_the_rest(self):
        motor, enviados, asyncio = self._motor(["Coloca na agenda de amanhã uma reunião com", "a Padaria Sol às 10h"])

        async def cena():
            motor._mic, motor._mic_bytes = [b"\0\0" * 800], 1600
            await motor.flush_microphone(by_pause=True)
            self.assertEqual(enviados, [])                 # esperou o resto
            motor._vad_started = True                      # voltou a falar
            motor._partial_task.cancel()
            motor._vad_started = False
            motor._mic, motor._mic_bytes = [b"\0\0" * 800], 1600
            await motor.flush_microphone(by_pause=True)
        asyncio.run(cena())
        self.assertEqual(enviados, ["Coloca na agenda de amanhã uma reunião com a Padaria Sol às 10h"])

    def test_half_sentence_is_answered_if_nothing_follows(self):
        import providers.engine_pipeline as ep
        motor, enviados, asyncio = self._motor(["Abre o WhatsApp e"])

        async def cena():
            with patch.object(ep, "_UNFINISHED_WAIT_S", 0.05):
                motor._mic, motor._mic_bytes = [b"\0\0" * 800], 1600
                await motor.flush_microphone(by_pause=True)
                await asyncio.sleep(0.2)
        asyncio.run(cena())
        self.assertEqual(enviados, ["Abre o WhatsApp e"])

    def test_complete_sentence_goes_at_once(self):
        motor, enviados, asyncio = self._motor(["Abre o WhatsApp"])

        async def cena():
            motor._mic, motor._mic_bytes = [b"\0\0" * 800], 1600
            await motor.flush_microphone(by_pause=True)
        asyncio.run(cena())
        self.assertEqual(enviados, ["Abre o WhatsApp"])

    def test_pause_default_is_longer(self):
        import providers.engine_pipeline as ep
        self.assertGreaterEqual(ep._VAD_SILENCE_MS, 1200)


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.stop = threading.Event()
        self.page = MagicMock(url="https://web.whatsapp.com/")
        self.estado = "qr"

        def loc(sel):
            el = MagicMock()
            el.first = el
            visivel = (sel == "#pane-side" and self.estado == "ok") or (sel in ("[data-ref]", web._QR) and self.estado == "qr")
            el.count.return_value = 1 if visivel else 0
            el.is_visible.return_value = visivel
            el.screenshot.return_value = b"\x89PNGqr"
            return el
        self.page.locator.side_effect = loc

    def test_qr_is_returned_as_an_image_for_the_jarvis_screen(self):
        r = web.login_info(self.page, self.stop, wait=0)
        self.assertEqual(r["estado"], "qr")
        import base64
        self.assertEqual(base64.b64decode(r["imagem"]), b"\x89PNGqr")

    def test_connected_and_still_loading(self):
        self.estado = "ok"
        self.assertEqual(web.login_info(self.page, self.stop, wait=0), {"estado": "ok", "imagem": ""})
        self.estado = "nada"
        self.assertEqual(web.login_state(self.page, self.stop, wait=0), "carregando")

    def test_reading_while_asking_for_qr_says_so(self):
        with patch.object(web, "login_state", return_value="qr"):
            with self.assertRaises(web.DraftError) as e:
                web.recent_chats(self.page, self.stop)
        self.assertEqual(e.exception.code, "login_qr")

    def test_recent_list_includes_read_chats_with_zero(self):
        def linha(nome, previa, badge):
            row = MagicMock()
            spans = MagicMock()
            spans.all.return_value = [_el(nome), _el(previa)]
            b = _el(aria=badge, count=1 if badge else 0)
            row.locator.side_effect = lambda sel: spans if sel == "span[title]" else b
            return row
        rows = MagicMock()
        rows.count.return_value = 2
        rows.all.return_value = [linha("Ana", "Obrigada!", None), linha("Padaria Sol", "Até sexta?", "2 mensagens não lidas")]
        with patch.object(web, "_require_login"), patch.object(web, "_chat_rows", return_value=rows):
            r = web.recent_chats(self.page, self.stop)
        self.assertEqual([(c["contato"], c["nao_lidas"]) for c in r], [("Ana", 0), ("Padaria Sol", 2)])

    def test_window_is_minimized_or_shown_through_the_browser(self):
        cdp = MagicMock()
        cdp.send.side_effect = lambda m, p=None: {"windowId": 7} if m == "Browser.getWindowForTarget" else {}
        self.page.context.new_cdp_session.return_value = cdp
        self.assertTrue(web.show_window(self.page, False))
        cdp.send.assert_called_with("Browser.setWindowBounds", {"windowId": 7, "bounds": {"windowState": "minimized"}})
        web.show_window(self.page, True)
        self.page.bring_to_front.assert_called_once()

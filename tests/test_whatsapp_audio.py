"""Mensagens de voz do WhatsApp: achar na conversa, baixar sem tocar, transcrever, lembrar."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PAGINA = """<!doctype html><html><body><div id="main">
<div role="row"><div data-id="false_5511@c.us_TXT1" class="message-in"><div data-pre-plain-text="[09:10, 28/10/2026] Ana: "><span>Bom dia!</span></div></div></div>
<div role="row"><div data-id="false_5511@c.us_VOZ1" class="message-in">
  <button aria-label="Reproduzir mensagem de voz"><span data-icon="audio-play"></span></button><span>0:07</span><span>09:11</span></div></div>
<div role="row"><div data-id="true_5511@c.us_IMG1" class="message-out"><img alt=""><span>09:12</span></div></div>
</div>
<script>
  // Como o WhatsApp Web: o clique no play cria o player com o arquivo (blob) e chama play().
  document.querySelector('[data-icon="audio-play"]').closest('button').addEventListener('click', () => {
    const blob = new Blob([new Uint8Array([79, 103, 103, 83, 1, 2, 3])], { type: 'audio/ogg; codecs=opus' });
    const a = new Audio(URL.createObjectURL(blob));
    window.tocou = false;
    a.play().then(() => { window.tocou = !a.paused; });
  });
</script></body></html>"""


class CapturaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.pw = sync_playwright().start()
            cls.navegador = cls.pw.chromium.launch()
        except Exception as e:  # noqa: BLE001
            raise unittest.SkipTest(f"sem navegador: {e}")

    @classmethod
    def tearDownClass(cls):
        cls.navegador.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.navegador.new_page()
        self.page.set_content(PAGINA)
        from core import whatsapp_web as w
        self.w = w
        self.p = [patch.object(w, "_require_login"), patch.object(w, "_open_chat")]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()
        self.page.close()

    def test_read_lists_voice_and_media_in_order(self):
        import threading
        msgs = self.w.read_chat(self.page, "Ana", threading.Event())
        self.assertEqual([m["tipo"] for m in msgs], ["texto", "audio", "midia"])
        self.assertEqual(msgs[0]["texto"], "Bom dia!")
        self.assertEqual((msgs[1]["id"], msgs[1]["de"], msgs[1]["duracao"], msgs[1]["hora"]),
                         ("false_5511@c.us_VOZ1", "contato", "0:07", "09:11"))
        self.assertEqual(msgs[2]["de"], "eu")

    def test_download_gets_the_file_without_playing(self):
        import threading
        r = self.w.baixar_audio(self.page, "Ana", "false_5511@c.us_VOZ1", threading.Event())
        self.assertEqual(r["audio"], bytes([79, 103, 103, 83, 1, 2, 3]))
        self.assertIn("ogg", r["tipo"])
        self.assertFalse(self.page.evaluate("window.tocou"))

    def test_missing_message_is_explained(self):
        import threading
        with self.assertRaises(self.w.DraftError):
            self.w.baixar_audio(self.page, "Ana", "false_nao_existe", threading.Event())


class TranscricaoTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": self.dir.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_transcribes_once_and_remembers(self):
        from core import transcrever
        baixados = []

        def run_op(payload, timeout=0):
            baixados.append(payload["id"])
            return True, "verified", {"audio": b"OggS...", "tipo": "audio/ogg"}
        with patch("core.whatsapp_web.run_op", side_effect=run_op), \
             patch.object(transcrever, "transcrever", return_value="Oi, preciso de um orçamento para o site"):
            t1 = transcrever.transcrever_mensagem("Ana", "VOZ1")
            t2 = transcrever.transcrever_mensagem("Ana", "VOZ1")
        self.assertEqual(t1, t2)
        self.assertEqual(baixados, ["VOZ1"])
        msgs = transcrever.com_transcricoes([{"tipo": "audio", "id": "VOZ1", "texto": "[mensagem de voz]", "de": "contato"}])
        self.assertEqual(msgs[0]["texto"], "[áudio] Oi, preciso de um orçamento para o site")

    def test_voice_tool_reads_with_transcriptions(self):
        from actions import whatsapp as ferramenta
        from core import transcrever
        msgs = [{"hora": "09:10", "de": "contato", "texto": "Bom dia!", "tipo": "texto"},
                {"hora": "09:11", "de": "contato", "texto": "[mensagem de voz]", "tipo": "audio", "id": "VOZ9"}]

        def run_op(payload, timeout=0):
            if payload["op"] == "read":
                return True, "verified", msgs
            return True, "verified", {"audio": b"OggS", "tipo": "audio/ogg"}
        with patch("core.whatsapp_web.run_op", side_effect=run_op), \
             patch.object(transcrever, "transcrever", return_value="Quero agendar uma reunião amanhã"):
            r = str(ferramenta.whatsapp({"acao": "ler", "contato": "Ana"}))
        self.assertIn("[áudio] Quero agendar uma reunião amanhã", r)



class DesligarTests(unittest.TestCase):
    def test_shutdown_closes_whatsapp_window_and_process(self):
        from haizen.central import janela, servidor
        ordem = []

        class Ponte:
            def desligar(self):
                ordem.append("janela")
        with patch("core.whatsapp_web.fechar", side_effect=lambda: ordem.append("whatsapp")), \
             patch.object(janela, "ponte", return_value=Ponte()), \
             patch.object(servidor, "parar", side_effect=lambda: ordem.append("central")), \
             patch("time.sleep"), patch("os._exit", side_effect=lambda c: ordem.append(f"fim {c}")):
            servidor.desligar()
        self.assertEqual(ordem, ["whatsapp", "janela", "central", "fim 0"])

    def test_voice_command(self):
        from haizen.central import atalhos
        with patch("threading.Thread") as t:
            r = atalhos.responder_direto("Jarvis, desliga")
        self.assertEqual(r[0], "Desligando o Jarvis. Até mais!")
        self.assertTrue(t.return_value.start.called)
        self.assertIsNone(atalhos.desligar_direto("desliga o computador"))


if __name__ == "__main__":
    unittest.main()

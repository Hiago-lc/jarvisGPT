import os
import tempfile
import unittest
from unittest.mock import patch

from haizen.central import acesso


class AcessoTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": tempfile.mkdtemp(),
                                           "HAIZEN_URL_PUBLICA": "https://jarvis.exemplo.com.br",
                                           "HAIZEN_EMAILS": "eu@exemplo.com",
                                           "HAIZEN_GOOGLE_LOGIN_ID": "x.apps.googleusercontent.com",
                                           "HAIZEN_GOOGLE_LOGIN_SEGREDO": "s"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_sessao_so_para_email_autorizado_e_nao_guarda_o_token(self):
        t = acesso.criar_sessao("eu@exemplo.com")
        self.assertEqual(acesso.sessao(t)["email"], "eu@exemplo.com")
        self.assertNotIn(t, acesso._arq().read_text())
        self.assertIsNone(acesso.sessao(acesso.criar_sessao("outro@x.com")))
        acesso.encerrar(t)
        self.assertIsNone(acesso.sessao(t))

    def test_login_recusa_email_de_fora(self):
        url = acesso.url_login("/")
        state = url.split("state=")[1].split("&")[0]
        resp = [b'{"access_token": "a"}', b'{"email": "intruso@x.com", "email_verified": true}']

        class R:
            def __init__(self, b): self.b = b
            def read(self): return self.b
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with patch("urllib.request.urlopen", side_effect=lambda *a, **k: R(resp.pop(0))):
            with self.assertRaises(PermissionError):
                acesso.concluir(state, "code")

    def test_cookie_seguro(self):
        c = acesso.cookie("abc")
        for parte in ("HttpOnly", "Secure", "SameSite=Lax"):
            self.assertIn(parte, c)


if __name__ == "__main__":
    unittest.main()

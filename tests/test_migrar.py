import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import migrar
from haizen import segredo


def _falso_fechar(t):
    return "dpapi:" + t[::-1]


def _falso_abrir(g):
    if g.startswith("dpapi:"):
        return g[6:][::-1]
    return g[6:] if g.startswith("plain:") else g


class MigrarTests(unittest.TestCase):
    def test_ida_e_volta_com_senha_e_segredos(self):
        origem, destino, raiz_a, raiz_b, saida = (Path(tempfile.mkdtemp()) for _ in range(5))
        (origem / "jarvis-claude" / "anexos").mkdir(parents=True)
        (origem / "jarvis-claude" / "anexos" / "video.mp4").write_bytes(b"x" * 100)
        (origem / "instagram_token.json").write_text(json.dumps({"token": _falso_fechar("EAAsegredo"), "em": 1}))
        (origem / "trafego.json").write_text(json.dumps({"pasta": r"C:\Users\GAMER\Desktop"}))
        (origem / "x.log").write_text("log")
        con = sqlite3.connect(origem / "haizen.db")
        con.execute("CREATE TABLE t (id INTEGER, segredo TEXT, pasta TEXT)")
        con.execute("INSERT INTO t VALUES (1, ?, ?)", (_falso_fechar("senha-base44"), r"C:\Users\GAMER\Docs"))
        con.commit(); con.close()
        (raiz_a / "config").mkdir()
        (raiz_a / "config" / "api_keys.json").write_text('{"gemini_api_key": "k"}')
        with patch.object(segredo, "fechar", side_effect=_falso_fechar), patch.object(segredo, "abrir", side_effect=_falso_abrir):
            with patch.dict(os.environ, {"JARVIS_DATA_DIR": str(origem)}), patch.object(migrar, "RAIZ", raiz_a), \
                    patch.object(migrar.Path, "home", return_value=Path(r"C:\Users\GAMER")):
                pacote = migrar.exportar(saida, "senha-forte")
            self.assertNotIn(b"EAAsegredo", pacote.read_bytes())
            with self.assertRaises(ValueError):
                migrar.decifrar(pacote.read_bytes(), "errada")
            with patch.dict(os.environ, {"JARVIS_DATA_DIR": str(destino)}), patch.object(migrar, "RAIZ", raiz_b), \
                    patch.object(migrar, "_jarvis_aberto", return_value=False), \
                    patch.object(migrar.Path, "home", return_value=Path(r"C:\Users\Hiago")):
                migrar.importar(pacote, "senha-forte")
        self.assertFalse((destino / "jarvis-claude" / "anexos").exists())
        self.assertFalse((destino / "x.log").exists())
        tok = json.loads((destino / "instagram_token.json").read_text())["token"]
        self.assertTrue(tok.startswith("dpapi:"))
        self.assertEqual(_falso_abrir(tok), "EAAsegredo")
        self.assertIn(r"C:\Users\Hiago", json.loads((destino / "trafego.json").read_text())["pasta"])
        seg, pasta = sqlite3.connect(destino / "haizen.db").execute("SELECT segredo, pasta FROM t").fetchone()
        self.assertEqual(_falso_abrir(seg), "senha-base44")
        self.assertEqual(pasta, r"C:\Users\Hiago\Docs")
        self.assertEqual((raiz_b / "config" / "api_keys.json").read_text(), '{"gemini_api_key": "k"}')


if __name__ == "__main__":
    unittest.main()

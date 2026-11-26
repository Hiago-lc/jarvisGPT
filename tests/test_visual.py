"""Ferramentas de direção de arte: prancha, folha de contato, tratamento, referências e kit."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch

from PIL import Image


class VisualTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.p = Path(self.dir.name)
        from haizen.producao import visual
        self.v = visual
        for i, cor in enumerate(((200, 40, 40), (40, 200, 40), (40, 40, 200), (230, 230, 50))):
            Image.new("RGB", (400 + 50 * i, 500), cor).save(self.p / f"r{i}.jpg")

    def tearDown(self):
        self.dir.cleanup()

    def test_prancha(self):
        self.v.main(["prancha", str(self.p / "pr.jpg"), *[str(self.p / f"r{i}.jpg") for i in range(4)], "--colunas", "2",
                     "--legendas"])
        im = Image.open(self.p / "pr.jpg")
        self.assertGreater(im.height, 900)

    def test_tratar_estilos(self):
        for est in self.v.ESTILOS:
            self.v.main(["tratar", str(self.p / "r0.jpg"), str(self.p / f"t-{est}.jpg"), "--estilo", est,
                         "--vinheta", "0.2", "--granulado", "0.03"])
            self.assertTrue((self.p / f"t-{est}.jpg").is_file())
        r, g, b = Image.open(self.p / "t-pb.jpg").convert("RGB").getpixel((200, 250))
        self.assertLess(max(r, g, b) - min(r, g, b), 12)                # preto e branco de verdade

    def test_folha_de_contato(self):
        from haizen.producao.ferramentas import ffmpeg
        video = self.p / "v.mp4"
        subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=4:s=320x568:r=25",
                        "-pix_fmt", "yuv420p", str(video)], check=True)
        self.v.main(["contato", str(video), str(self.p / "c.jpg"), "--quadros", "8"])
        self.assertTrue((self.p / "c.jpg").is_file())

    def test_referencias_salva_capturas_e_falhas(self):
        def capt(page, url, saida, altura, rolar=3):
            if "dribbble" in url:
                raise RuntimeError("bloqueado")
            Image.new("RGB", (100, 100)).save(saida)
            return [url + "/img.jpg"]
        with patch.object(self.v, "_capturar", side_effect=capt):
            self.v.main(["referencias", "clinica", "estetica", "--pasta", str(self.p / "refs")])
        dados = json.loads((self.p / "refs" / "referencias-clinica-estetica.json").read_text(encoding="utf-8"))
        self.assertEqual({c["fonte"] for c in dados["capturas"]}, {"meta_ads", "behance", "pinterest"})
        self.assertIn("dribbble", dados["falhas"])
        self.assertIn("q=clinica%20estetica", dados["capturas"][0]["url"])


class KitTests(unittest.TestCase):
    def test_kit_copiado_e_modelos_descritos(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"HAIZEN_TRABALHO_PASTA": d}):
            from haizen.producao import mcp_producao
            txt = mcp_producao.kit_de_design()
            self.assertTrue((Path(d) / "fontes" / "kit" / "motion.js").is_file())
            self.assertIn("08-reels-kinetic.html", txt)
            self.assertIn("Quando usar", txt)
            self.assertEqual(len(list((Path(d) / "fontes" / "kit" / "modelos").glob("*.html"))), 8)

    def test_padrao_de_criacao_no_claude_md(self):
        from haizen import executor
        with tempfile.TemporaryDirectory() as d:
            txt = executor.instrucoes_da_pasta(Path(d), None, None, "criativos")
        for trecho in ("referencias(", "kit_de_design()", "prancha", "folha_de_contato", "Nota 1–10"):
            self.assertIn(trecho, txt)


if __name__ == "__main__":
    unittest.main()

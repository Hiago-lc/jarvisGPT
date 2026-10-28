"""Pedidos do jeito que se fala: listas numeradas, baixa de parcela, nomes aproximados."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FinanceiroFaladoTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"HAIZEN_DB": str(Path(self.dir.name) / "h.db")})
        self.env.start()
        from haizen import store
        from haizen.central import dados
        store.salvar_cliente("PRISMATIX SOLUÇÕES")
        store.salvar_cliente("Beta Studio")
        self.cli = {c["nome"]: c["id"] for c in store.listar_clientes()}
        dados.criar("receitas", {"cliente_id": self.cli["PRISMATIX SOLUÇÕES"], "descricao": "1/2 Loja virtual",
                                 "valor": "600", "vencimento": "2026-08-10", "recebido": True})
        dados.criar("receitas", {"cliente_id": self.cli["PRISMATIX SOLUÇÕES"], "descricao": "2/2 Loja virtual",
                                 "valor": "600", "vencimento": "2026-10-27", "recebido": False})

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def _receitas(self):
        from haizen.central import dados
        return {r["descricao"]: r for r in dados.listar("receitas")}

    def test_numbered_list_marks_existing_and_creates_new(self):
        from haizen.central.atalhos import responder_direto
        r, usadas = responder_direto("Preciso que faça duas coisas no financeiro:\n\n"
                                     "1 Coloque como recebido no pagamento 2/2 do Prismatix Soluções\n"
                                     "2 Coloque outro pagamento de R$ 300,00 do Prizmatix Soluções com descrição "
                                     "de serviços de tráfego como pago")
        rec = self._receitas()
        self.assertTrue(rec["2/2 Loja virtual"]["recebido"])
        self.assertEqual(len(rec), 3)                                # só um registro novo
        self.assertTrue(rec["serviços de tráfego"]["recebido"])
        self.assertEqual(rec["serviços de tráfego"]["valor"], 300)
        self.assertTrue(r.startswith("1. Marquei como recebida"))
        self.assertIn("\n2. Registrei a receita de PRISMATIX SOLUÇÕES", r)
        self.assertEqual(usadas, ["central"])

    def test_already_received_changes_nothing(self):
        from haizen.central.atalhos import responder_direto
        responder_direto("marca como recebido o 2/2 da Prismatix Soluções")
        r, _ = responder_direto("Coloque como recebido no pagamento 2/2 do Prismatix Soluções")
        self.assertIn("já estava recebida", r)

    def test_ambiguous_asks_which(self):
        from haizen.central import dados
        from haizen.central.atalhos import responder_direto
        dados.criar("receitas", {"cliente_id": self.cli["Beta Studio"], "descricao": "Mensalidade outubro",
                                 "valor": "900", "vencimento": "2026-10-10"})
        dados.criar("receitas", {"cliente_id": self.cli["Beta Studio"], "descricao": "Mensalidade novembro",
                                 "valor": "900", "vencimento": "2026-11-10"})
        r, _ = responder_direto("marca como recebido o pagamento da Beta Studio")
        self.assertIn("mais de uma", r)
        r, _ = responder_direto("marca como recebido o pagamento de novembro da Beta Studio")
        self.assertIn("Mensalidade novembro", r)
        self.assertTrue(self._receitas()["Mensalidade novembro"]["recebido"])
        self.assertFalse(self._receitas()["Mensalidade outubro"]["recebido"])

    def test_unhandled_items_go_to_the_model_untouched(self):
        from haizen.central.atalhos import responder_direto
        self.assertIsNone(responder_direto("Duas coisas:\n1 abre o Spotify\n2 toca uma música calma"))



class AgendaFaladaTests(unittest.TestCase):
    def test_title_ignores_the_preamble_and_acute_accent(self):
        from haizen.central.atalhos import _eventos_da_frase
        self.assertEqual(_eventos_da_frase("vamos agr para a agenda\npreciso de inclua na agenda de amanhã de 10 ás 11 "
                                           "a implementação do novo módulo no sistema do cliente"),
                         [(10, 0, 11, 0, "Implementação do novo módulo no sistema do cliente")])
        self.assertEqual(_eventos_da_frase("agenda uma call das 14 às 15 com o cliente")[0][4], "Call com o cliente")


if __name__ == "__main__":
    unittest.main()

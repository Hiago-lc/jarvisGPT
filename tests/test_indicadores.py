import datetime as dt
import os
import tempfile
import unittest
from unittest.mock import patch

from haizen import indicadores


class PeriodoTests(unittest.TestCase):
    def test_padrao_e_anterior_do_mesmo_tamanho(self):
        i, f, ia, fa = indicadores.periodo(hoje=dt.date(2026, 11, 14))
        self.assertEqual((i, f), (dt.date(2026, 10, 15), dt.date(2026, 11, 13)))
        self.assertEqual((f - i).days, (fa - ia).days)
        self.assertEqual(fa, i - dt.timedelta(days=1))

    def test_agrupa_periodos_longos(self):
        self.assertEqual(indicadores.agrupamento(dt.date(2026, 1, 1), dt.date(2026, 1, 31)), "dia")
        self.assertEqual(indicadores.agrupamento(dt.date(2026, 1, 1), dt.date(2026, 5, 1)), "semana")
        self.assertEqual(indicadores.agrupamento(dt.date(2025, 1, 1), dt.date(2026, 1, 1)), "mes")


def _linha(gasto, imp, link, conversas=0, compras=0, valor=0, **extra):
    acts = [{"action_type": "onsite_conversion.messaging_conversation_started_7d", "value": str(conversas)}] if conversas else []
    if compras:
        acts += [{"action_type": "omni_purchase", "value": str(compras)}, {"action_type": "purchase", "value": str(compras)}]
    return {"spend": str(gasto), "impressions": str(imp), "inline_link_clicks": str(link), "clicks": str(link),
            "reach": str(imp // 2), "frequency": "2", "actions": acts,
            "action_values": [{"action_type": "omni_purchase", "value": str(valor)}] if valor else [], **extra}


class MetaTests(unittest.TestCase):
    def setUp(self):
        indicadores.limpar_cache()

    def test_resultado_principal_custos_e_variacao(self):
        def falso(caminho, **p):
            if p.get("breakdowns") == "publisher_platform":
                return [_linha(60, 600, 6, 6, publisher_platform="instagram"), _linha(40, 400, 4, 4, publisher_platform="facebook")]
            if p.get("breakdowns"):
                return []
            if caminho.endswith("/campaigns"):
                return [{"id": "c1", "effective_status": "ACTIVE"}]
            if p.get("level") == "campaign":
                anterior = '"since": "2026-11-12"' not in p["time_range"]
                return [_linha(50 if anterior else 100, 1000, 10, 5 if anterior else 10, campaign_id="c1", campaign_name="Mensagens")]
            if p.get("time_increment"):
                return [_linha(50, 500, 5, 5, date_start="2026-11-12"), _linha(50, 500, 5, 5, date_start="2026-11-13")]
            if '"since": "2026-11-12"' in p["time_range"]:
                return [_linha(100, 1000, 10, 10)]
            return [_linha(80, 800, 8, 4)]
        with patch.object(indicadores, "_meta_get", side_effect=falso), \
                patch("haizen.trafego.envio._act", side_effect=lambda c: c):
            r = indicadores.meta("act_1", "2026-11-12", "2026-11-13")
        self.assertEqual(r["resultado"], "conversas")
        self.assertEqual(r["total"]["custo_resultado"], 10.0)
        self.assertEqual(r["total_anterior"]["custo_resultado"], 20.0)
        self.assertEqual(r["variacao"]["custo_resultado"], -50.0)
        self.assertEqual([d["dia"] for d in r["serie"]], ["2026-11-12", "2026-11-13"])
        self.assertEqual(r["campanhas"][0]["status"], "ACTIVE")
        self.assertEqual(r["quebras"]["plataforma"][0]["nome"], "Instagram")

    def test_compras_sem_contar_duas_vezes(self):
        x = indicadores.meta_linha(_linha(100, 1000, 10, compras=3, valor=450))
        self.assertEqual(x["compras"], 3)
        r = indicadores.meta_resumo(x, indicadores.escolher_resultado(x))
        self.assertEqual(r["roas"], 4.5)
        self.assertEqual(r["resultados"], 3)


class GoogleTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JARVIS_DATA_DIR": self.dir.name})
        self.env.start()
        indicadores.limpar_cache()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_serie_preenche_dias_e_compara(self):
        from haizen import googleads
        from haizen.googleads import api

        def gaql(c, q):
            m = lambda custo, conv: {"costMicros": str(int(custo * 1e6)), "conversions": conv, "clicks": "10",
                                     "impressions": "100", "conversionsValue": 0}
            if "segments.date, " in q:
                return [{"segments": {"date": "2026-11-01"}, "metrics": m(30, 3)}]
            if "FROM customer" in q and "device" in q:
                return [{"segments": {"device": "MOBILE"}, "metrics": m(30, 3)}]
            if "FROM customer" in q:
                return [{"metrics": m(60, 3)}]
            if "campaign.name" in q:
                return [{"campaign": {"id": 1, "name": "Pesquisa", "status": "ENABLED", "advertisingChannelType": "SEARCH"},
                         "campaignBudget": {"amountMicros": "20000000"}, "metrics": m(30, 3)}]
            if "FROM campaign" in q:
                return [{"campaign": {"id": 1}, "metrics": m(60, 3)}]
            return []
        with patch.object(googleads, "conta", return_value={"id": "123", "moeda": "BRL"}), \
                patch.object(api, "gaql", side_effect=gaql):
            r = indicadores.google("123", "2026-11-01", "2026-11-03")
        self.assertEqual(len(r["serie"]), 3)
        self.assertEqual(r["serie"][1]["custo"], 0)
        self.assertEqual(r["total"]["cpa"], 10.0)
        self.assertEqual(r["variacao"]["cpa"], -50.0)
        self.assertEqual(r["campanhas"][0]["tipo"], "Pesquisa")
        self.assertEqual(r["quebras"]["dispositivo"][0]["nome"], "Celular")


if __name__ == "__main__":
    unittest.main()

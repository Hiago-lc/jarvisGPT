"""Projetos: o gerente planeja, a equipe executa em etapas, você aprova."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent

PLANO = """Aqui está o plano.
```json
{"titulo": "Lançamento Padaria Sol",
 "etapas": [
  {"agente": "atendimento", "titulo": "Briefing", "tarefa": "Organize o pedido.", "depende_de": [], "aprovacao": false},
  {"agente": "designer", "titulo": "Conceito da marca", "tarefa": "Crie o conceito.", "depende_de": [1], "aprovacao": true},
  {"agente": "dev", "titulo": "Estrutura do site", "tarefa": "Planeje o site.", "depende_de": [1, 2], "aprovacao": false},
  {"agente": "inexistente", "titulo": "X", "tarefa": "Y", "depende_de": [], "aprovacao": false},
  {"agente": "revisor", "titulo": "Revisão final", "tarefa": "Revise tudo.", "depende_de": [3], "aprovacao": true}
 ]}
```"""


class ProjetoTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        shutil.copytree(RAIZ / "haizen" / "agentes", base / "agentes")
        self.env = patch.dict(os.environ, {
            "HAIZEN_DB": str(base / "haizen.db"),
            "HAIZEN_AGENTES_DIR": str(base / "agentes"),
            "HAIZEN_ENTREGAS_DIR": str(base / "entregas"),
        })
        self.env.start()
        self.prompts = []
        from haizen import executor

        def falso(prompt):
            self.prompts.append(prompt)
            if "## Equipe disponível" in prompt:
                return self.plano
            return f"Entrega feita. ({len(self.prompts)})"
        # Os testes rodam os agentes com o modelo falso no lugar do executor.
        self.p = [patch.object(executor, "executar_local", side_effect=falso),
                  patch.object(executor, "claude_disponivel", return_value=None),
                  patch.object(executor, "PERMITIR_LOCAL", True)]
        for x in self.p:
            x.start()
        self.plano = PLANO

    def tearDown(self):
        for x in self.p:
            x.stop()
        self.env.stop()
        self.dir.cleanup()

    def _rodar_fila(self):
        """O worker, sem thread: executa tudo o que estiver na fila."""
        from haizen import executor, servicos, store
        while True:
            t = store.pegar_proximo()
            if t is None:
                return
            executor.executar(t)
            servicos.apos_entrega(t)

    def _etapas(self, pid):
        from haizen import store
        return {t["titulo"]: t for t in store.trabalhos_do_projeto(pid)}

    def test_manager_plan_becomes_steps_and_flows_until_approval(self):
        from haizen import servicos, store
        with patch("haizen.worker.iniciar"):
            pid = servicos.criar_projeto("Site e marca nova", "Padaria Sol")["projeto"]["id"]
            self._rodar_fila()
            e = self._etapas(pid)
            self.assertEqual(store.projeto(pid)["titulo"], "Lançamento Padaria Sol")
            self.assertEqual(e["Plano do projeto"]["status"], "aprovado")
            self.assertEqual(e["Briefing"]["status"], "aprovado")            # seguiu sozinho
            self.assertEqual(e["Conceito da marca"]["status"], "aguardando_aprovacao")
            self.assertEqual(e["Estrutura do site"]["status"], "esperando")
            self.assertNotIn("X", e)                                         # agente inexistente descartado
            self.assertEqual(servicos.situacao_projeto(list(e.values())), "aguardando")

            servicos.aprovar(e["Conceito da marca"]["id"])
            self._rodar_fila()
            e = self._etapas(pid)
            self.assertEqual(e["Estrutura do site"]["status"], "aprovado")
            self.assertEqual(e["Revisão final"]["status"], "aguardando_aprovacao")
            # O dev leu o pedido do projeto e as entregas do briefing e do conceito.
            prompt_dev = next(p for p in self.prompts if "Planeje o site." in p)
            self.assertIn("## Pedido do projeto", prompt_dev)
            self.assertIn("Entrega anterior: Briefing", prompt_dev)
            self.assertIn("Entrega anterior: Conceito da marca", prompt_dev)

            servicos.aprovar(e["Revisão final"]["id"])
            self.assertEqual(servicos.situacao_projeto(store.trabalhos_do_projeto(pid)), "concluido")

    def test_redo_keeps_the_step_and_rewires_dependents(self):
        from haizen import servicos
        with patch("haizen.worker.iniciar"):
            pid = servicos.criar_projeto("Site e marca nova", "Padaria Sol")["projeto"]["id"]
            self._rodar_fila()
            conceito = self._etapas(pid)["Conceito da marca"]
            novo = servicos.refazer(conceito["id"], "mais cores quentes")
            self.assertEqual((novo["projeto_id"], novo["titulo"]), (pid, "Conceito da marca"))
            site = self._etapas(pid)["Estrutura do site"]
            self.assertIn(novo["id"], json.loads(site["depende_de"]))
            self._rodar_fila()
            servicos.aprovar(novo["id"])
            self._rodar_fila()
            self.assertEqual(self._etapas(pid)["Estrutura do site"]["status"], "aprovado")

    def test_unreadable_plan_falls_back_to_services_in_the_request(self):
        from haizen import servicos, store
        self.plano = "Desculpe, não consegui."
        with patch("haizen.worker.iniciar"):
            pid = servicos.criar_projeto("Quero uma proposta e uma campanha de tráfego no Instagram",
                                         "Loja X")["projeto"]["id"]
            self._rodar_fila()
        agentes_usados = [t["agente"] for t in store.trabalhos_do_projeto(pid)]
        for a in ("gerente", "atendimento", "comercial", "trafego", "social", "revisor"):
            self.assertIn(a, agentes_usados)
        self.assertIn("plano padrão", store.trabalhos_do_projeto(pid)[0]["observacao"])

    def test_delete_project_removes_steps(self):
        from haizen import servicos, store
        with patch("haizen.worker.iniciar"):
            pid = servicos.criar_projeto("Site", "Padaria Sol")["projeto"]["id"]
            self._rodar_fila()
        store.apagar_projeto(pid)
        self.assertIsNone(store.projeto(pid))
        self.assertEqual(store.trabalhos_do_projeto(pid), [])

    def test_voice_tool_opens_a_project(self):
        import importlib
        plugin = importlib.import_module("plugins.haizen")
        with patch("haizen.worker.iniciar"):
            r = plugin.run({"acao": "projeto", "pedido": "Site e campanha", "cliente": "Padaria Sol"})
        self.assertIn("Projeto 1 aberto", r)
        from haizen import servicos
        self.assertIn("Projetos: Site e campanha (gerente planejando)", servicos.resumo())

    def test_office_shows_who_is_doing_what(self):
        from haizen import servicos
        from haizen.central import servidor
        with patch("haizen.worker.iniciar"):
            servicos.criar_projeto("Site e marca nova", "Padaria Sol")
            self._rodar_fila()
        e = servidor.escritorio()
        por_nome = {a["nome"]: a for a in e["agentes"]}
        self.assertEqual(por_nome["designer"]["estado"], "esperando_voce")
        self.assertEqual(por_nome["dev"]["esperando"], 1)
        self.assertEqual(e["projetos"][0]["situacao"], "aguardando")
        self.assertEqual(e["projetos"][0]["progresso"], [1, 4])

    def test_claude_not_logged_in_stops_with_instructions_then_retry(self):
        from haizen import executor, servicos, store
        self.p[1].stop()                                   # o Claude Code "existe"
        executor._SEM_LOGIN["ate"] = 0.0
        with patch.object(executor, "PERMITIR_LOCAL", False), \
             patch.object(executor, "claude_disponivel", return_value="claude"), \
             patch.object(executor, "executar_claude",
                          side_effect=RuntimeError("o Claude Code falhou: Not logged in · Please run /login")), \
             patch("haizen.worker.iniciar"):
            t = servicos.delegar("comercial", "Proposta de site", "Padaria Sol")["trabalho"]
            self.assertEqual(t["executor"], "claude")
            alvo = store.pegar_proximo()
            with self.assertRaises(RuntimeError) as erro:
                executor.executar(alvo)
            self.assertIn("conectar-claude.bat", str(erro.exception))
            self.assertEqual(self.prompts, [])                     # o modelo local nem foi chamado
            store.atualizar(t["id"], status="erro", erro=str(erro.exception))
            novo = servicos.tentar_de_novo(t["id"])
        self.assertEqual((novo["status"], novo["executor"]), ("na_fila", "claude"))
        self.assertFalse(executor.claude_sem_login())              # tentar de novo testa o login outra vez
        executor._SEM_LOGIN["ate"] = 0.0
        self.p[1].start()

    def test_all_agents_run_on_claude(self):
        from haizen import agentes
        self.assertEqual({a.executor for a in agentes.listar()}, {"claude"})

    def test_reviewer_gets_trimmed_context_and_retries_once(self):
        from haizen import executor, servicos, store
        tamanhos = []
        longo = "Linha de entrega comprida.\n" * 2000          # ~54 mil caracteres por entrega

        def falso(prompt):
            if "## Equipe disponível" in prompt:
                return self.plano
            if "Revise tudo." in prompt:
                tamanhos.append(len(prompt))
                if len(tamanhos) == 1:
                    raise RuntimeError("o modelo local falhou: ReadTimeout")
            return longo
        with patch.object(executor, "executar_local", side_effect=falso), patch("haizen.worker.iniciar"):
            pid = servicos.criar_projeto("Site e marca nova", "Padaria Sol")["projeto"]["id"]
            self._rodar_fila()
            servicos.aprovar(self._etapas(pid)["Conceito da marca"]["id"])
            self._rodar_fila()
        revisao = self._etapas(pid)["Revisão final"]
        self.assertEqual(revisao["status"], "aguardando_aprovacao")
        self.assertEqual(len(tamanhos), 2)
        self.assertLess(tamanhos[0], executor.CONTEXTO_LOCAL + 4000)       # cabe no modelo local
        self.assertLess(tamanhos[1], tamanhos[0])                          # a 2ª tentativa é menor


if __name__ == "__main__":
    unittest.main()

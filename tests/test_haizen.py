import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch


class _Temp(unittest.TestCase):
    """Each test gets its own database, agents folder and deliveries folder."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        self.agentes_dir = base / 'agentes'
        self.env = patch.dict(os.environ, {
            'HAIZEN_DB': str(base / 'haizen.db'),
            'HAIZEN_AGENTES_DIR': str(self.agentes_dir),
            'HAIZEN_ENTREGAS_DIR': str(base / 'entregas'),
        })
        self.env.start()
        from haizen import agentes
        agentes.salvar('comercial', 'Comercial', 'Propostas', 'claude', 'Escreva a proposta.')
        agentes.salvar('criativos', 'Criativos', 'Legendas', 'local', 'Escreva legendas.')

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()


class AgentesTests(_Temp):
    def test_round_trip_keeps_every_field(self):
        from haizen import agentes
        a = agentes.carregar('comercial')
        self.assertEqual((a.titulo, a.descricao, a.executor), ('Comercial', 'Propostas', 'claude'))
        self.assertEqual(a.instrucoes, 'Escreva a proposta.')

    def test_invalid_executor_is_refused_before_writing(self):
        from haizen import agentes
        with self.assertRaises(ValueError):
            agentes.salvar('teste', 'T', 'd', 'gpt', 'x')
        self.assertFalse((self.agentes_dir / 'teste.md').exists())

    def test_invalid_name_is_refused(self):
        from haizen import agentes
        for nome in ('../fora', 'Com Espaco', ''):
            with self.assertRaises(ValueError):
                agentes.salvar(nome, 'T', 'd', 'local', 'x')

    def test_broken_file_does_not_hide_the_others(self):
        from haizen import agentes
        (self.agentes_dir / 'quebrado.md').write_text('---\nnome: quebrado\nexecutor: x\n---\n')
        self.assertEqual([a.nome for a in agentes.listar()], ['comercial', 'criativos'])

    def test_unknown_agent_lists_the_available_ones(self):
        from haizen import agentes
        with self.assertRaises(KeyError) as e:
            agentes.carregar('juridico')
        self.assertIn('comercial', str(e.exception))

    def test_shipped_agents_parse(self):
        from haizen import agentes
        pasta = Path(agentes.__file__).parent / 'agentes'
        for arq in pasta.glob('*.md'):
            a = agentes.parse(arq.read_text(encoding='utf-8'), arq.name)
            self.assertEqual(a.nome, arq.stem)


class StoreTests(_Temp):
    def test_client_lookup_ignores_accents_and_case(self):
        from haizen import store
        store.salvar_cliente('Padaria São João', {'segmento': 'padaria'})
        self.assertEqual(store.buscar_cliente('padaria sao joao')['nome'], 'Padaria São João')
        self.assertEqual(store.buscar_cliente('são joão')['dados']['segmento'], 'padaria')

    def test_updating_a_client_merges_data_and_appends_notes(self):
        from haizen import store
        store.salvar_cliente('Aurora', {'cores': 'azul'}, 'primeira')
        c = store.salvar_cliente('aurora', {'tom': 'leve'}, 'segunda')
        self.assertEqual(c['dados'], {'cores': 'azul', 'tom': 'leve'})
        self.assertEqual(c['notas'], 'primeira\nsegunda')
        self.assertEqual(len(store.listar_clientes()), 1)

    def test_ambiguous_partial_name_finds_nothing(self):
        from haizen import store
        store.salvar_cliente('Studio Alfa')
        store.salvar_cliente('Studio Beta')
        self.assertIsNone(store.buscar_cliente('studio'))

    def test_next_job_is_taken_once(self):
        from haizen import store
        store.criar_trabalho('criativos', 'legenda', 'local')
        self.assertEqual(store.pegar_proximo()['status'], 'executando')
        self.assertIsNone(store.pegar_proximo())

    def test_interrupted_jobs_return_to_the_queue(self):
        from haizen import store
        t = store.criar_trabalho('criativos', 'legenda', 'local')
        store.pegar_proximo()
        self.assertEqual(store.recuperar_interrompidos(), 1)
        self.assertEqual(store.trabalho(t['id'])['status'], 'na_fila')


class ServicosTests(_Temp):
    def test_delegate_creates_missing_client_and_says_so(self):
        from haizen import servicos
        with patch('haizen.executor.claude_disponivel', return_value='claude'):
            r = servicos.delegar('comercial', 'proposta de site', 'Aurora')
        self.assertEqual(r['trabalho']['executor'], 'claude')
        self.assertIn('Aurora', r['aviso'])

    def test_falls_back_to_local_without_claude_code(self):
        from haizen import servicos
        with patch('haizen.executor.claude_disponivel', return_value=None):
            r = servicos.delegar('comercial', 'proposta')
        self.assertEqual(r['trabalho']['executor'], 'local')
        self.assertIn('Claude Code', r['aviso'])

    def test_only_waiting_jobs_can_be_approved(self):
        from haizen import servicos, store
        t = store.criar_trabalho('criativos', 'legenda', 'local')
        with self.assertRaises(ValueError):
            servicos.aprovar(t['id'])
        store.gravar_entrega(t['id'], 'texto')
        self.assertEqual(servicos.aprovar(t['id'])['status'], 'aprovado')

    def test_redo_keeps_history_and_rejects_the_old_version(self):
        from haizen import servicos, store
        t = store.criar_trabalho('criativos', 'legenda', 'local')
        store.gravar_entrega(t['id'], 'v1')
        novo = servicos.refazer(t['id'], 'mais curta')
        self.assertIn('mais curta', novo['pedido'])
        self.assertIn('Versão anterior', novo['pedido'])
        self.assertEqual(store.trabalho(t['id'])['status'], 'rejeitado')


class ExecutorTests(_Temp):
    def test_prompt_has_instructions_client_rules_and_request(self):
        from haizen import agentes, executor, store
        c = store.salvar_cliente('Aurora', {'tom': 'leve'})
        p = executor.montar_prompt(agentes.carregar('criativos'), c, 'três legendas')
        for parte in ('Escreva legendas.', '"tom": "leve"', 'três legendas', 'não ordens'):
            self.assertIn(parte, p)

    def test_claude_code_never_receives_an_api_key(self):
        from haizen import executor
        done = subprocess.CompletedProcess([], 0, stdout=json.dumps({'result': 'Proposta'}), stderr='')
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-cobrada'}), \
             patch('haizen.executor.claude_disponivel', return_value='claude'), \
             patch('subprocess.run', return_value=done) as run:
            self.assertEqual(executor.executar_claude('prompt', Path(self.dir.name) / 'w'), 'Proposta')
        kwargs = run.call_args.kwargs
        self.assertNotIn('ANTHROPIC_API_KEY', kwargs['env'])
        self.assertEqual(kwargs['input'], 'prompt')

    def test_claude_code_error_is_reported(self):
        from haizen import executor
        done = subprocess.CompletedProcess([], 1, stdout=json.dumps({'is_error': True, 'result': 'limite atingido'}), stderr='')
        with patch('haizen.executor.claude_disponivel', return_value='claude'), \
             patch('subprocess.run', return_value=done):
            with self.assertRaises(RuntimeError) as e:
                executor.executar_claude('p', Path(self.dir.name) / 'w')
        self.assertIn('limite atingido', str(e.exception))


class WorkerTests(_Temp):
    def _esperar(self, cond, segundos=5):
        fim = time.time() + segundos
        while time.time() < fim:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_worker_delivers_and_records_errors(self):
        from haizen import store, worker
        ok = store.criar_trabalho('criativos', 'legenda', 'local')
        ruim = store.criar_trabalho('criativos', 'falhar', 'local')

        def fake(prompt):
            if 'falhar' in prompt:
                raise RuntimeError('modelo fora do ar')
            return 'Legenda pronta'
        avisos = []
        with patch('haizen.executor.executar_local', side_effect=fake):
            worker.iniciar(avisos.append)
            self.assertTrue(self._esperar(lambda: not worker.ocupado()))
        self.assertEqual(store.trabalho(ok['id'])['status'], 'aguardando_aprovacao')
        self.assertEqual(Path(store.trabalho(ok['id'])['arquivo']).read_text(encoding='utf-8').strip(), 'Legenda pronta')
        self.assertEqual(store.trabalho(ruim['id'])['status'], 'erro')
        self.assertIn('modelo fora do ar', store.trabalho(ruim['id'])['erro'])
        self.assertEqual(len(avisos), 2)


class PluginTests(_Temp):
    def setUp(self):
        super().setUp()
        import plugins.haizen as plugin
        self.plugin = importlib.reload(plugin)

    def test_declares_itself_core_with_a_brief(self):
        self.assertEqual(self.plugin.PLUGIN['tier'], 'core')
        self.assertTrue(self.plugin.PLUGIN['brief'])

    def test_voice_flow_delegate_status_approve(self):
        from haizen import store
        with patch('haizen.worker.iniciar'), \
             patch('haizen.executor.claude_disponivel', return_value='claude'):
            msg = self.plugin.run({'acao': 'delegar', 'agente': 'comercial',
                                   'pedido': 'proposta de site', 'cliente': 'Aurora'})
        self.assertIn('Claude Code', msg)
        tid = store.listar_trabalhos()[0]['id']
        self.assertIn('na fila', self.plugin.run({'acao': 'status'}))
        store.gravar_entrega(tid, 'Proposta')
        self.assertIn('aprovado', self.plugin.run({'acao': 'aprovar', 'id': tid}))

    def test_missing_fields_are_asked_not_crashed(self):
        self.assertIn('agente', self.plugin.run({'acao': 'delegar'}))
        self.assertIn('número', self.plugin.run({'acao': 'aprovar'}))
        self.assertIn('Ação desconhecida', self.plugin.run({'acao': 'voar'}))

    def test_unknown_agent_is_a_spoken_answer(self):
        msg = self.plugin.run({'acao': 'delegar', 'agente': 'juridico', 'pedido': 'x'})
        self.assertIn('comercial', msg)

    def test_client_notes_are_saved_and_read_back(self):
        self.plugin.run({'acao': 'ficha', 'cliente': 'Aurora', 'dados': 'Prefere tons pastel'})
        self.assertIn('pastel', self.plugin.run({'acao': 'ficha', 'cliente': 'aurora'}))


class McpServerTests(_Temp):
    def _carregar(self):
        tools = {}

        class FakeMCP:
            def __init__(self, *a, **k):
                pass

            def tool(self):
                def deco(fn):
                    tools[fn.__name__] = fn
                    return fn
                return deco

            def run(self):
                pass
        fastmcp = types.ModuleType('mcp.server.fastmcp')
        fastmcp.FastMCP = FakeMCP
        mods = {'mcp': types.ModuleType('mcp'), 'mcp.server': types.ModuleType('mcp.server'),
                'mcp.server.fastmcp': fastmcp}
        with patch.dict(sys.modules, mods):
            sys.modules.pop('haizen.mcp_server', None)
            importlib.import_module('haizen.mcp_server')
        return tools

    def test_claude_can_create_an_agent_queue_work_and_deliver(self):
        t = self._carregar()
        t['salvar_agente']('seo', 'SEO', 'Textos de SEO', 'local', 'Escreva títulos e descrições.')
        self.assertIn('seo', [a['nome'] for a in t['listar_agentes']()])
        self.assertIn('Escreva títulos', t['ver_prompt']('seo', 'página inicial'))
        r = t['criar_trabalho']('seo', 'página inicial', 'Aurora')
        tid = r['trabalho']['id']
        t['registrar_entrega'](tid, '# Títulos')
        lido = t['ler_trabalho'](tid)
        self.assertEqual(lido['status'], 'aguardando_aprovacao')
        self.assertEqual(lido['entrega'].strip(), '# Títulos')
        self.assertEqual(lido['cliente'], 'Aurora')
        self.assertEqual(t['listar_trabalhos']()[0]['cliente'], 'Aurora')

    def test_finished_work_cannot_be_overwritten(self):
        t = self._carregar()
        tid = t['criar_trabalho']('criativos', 'legenda')['trabalho']['id']
        t['registrar_entrega'](tid, 'v1')
        with self.assertRaises(ValueError):
            t['registrar_entrega'](tid, 'v2')


class InstaladorTests(unittest.TestCase):
    def test_keeps_other_servers_and_backs_up(self):
        from haizen import instalar_mcp
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d)
            (pasta / 'claude_desktop_config.json').write_text(json.dumps(
                {'mcpServers': {'outro': {'command': 'x'}}, 'tema': 'escuro'}))
            arq = instalar_mcp.registrar(pasta)
            dados = json.loads(arq.read_text())
            self.assertEqual(dados['mcpServers']['outro'], {'command': 'x'})
            self.assertEqual(dados['tema'], 'escuro')
            self.assertTrue(dados['mcpServers']['haizen']['args'][0].endswith('mcp_server.py'))
            self.assertEqual(len(list(pasta.glob('claude_desktop_config.backup-*.json'))), 1)


class BudgetTests(unittest.TestCase):
    def test_haizen_survives_the_local_tool_budget(self):
        from providers import schema
        core = [{'name': n, 'description': 'x' * 700, 'parameters': {'type': 'OBJECT', 'properties': {}}}
                for n in schema.CORE_TOOLS if n != 'haizen']
        import plugins.haizen as plugin
        decl = {k: plugin.PLUGIN[k] for k in ('name', 'description', 'parameters', 'tier')}
        kept = schema.budget(core + [decl], max_tools=10, max_chars=8000)
        self.assertIn('haizen', [d['name'] for d in kept])


class ClaudeLookupTests(unittest.TestCase):
    def test_finds_claude_outside_the_path(self):
        from haizen import executor
        with tempfile.TemporaryDirectory() as d:
            bin_dir = Path(d) / '.local' / 'bin'
            bin_dir.mkdir(parents=True)
            exe = bin_dir / ('claude.exe' if os.name == 'nt' else 'claude')
            exe.write_text('')
            with patch('shutil.which', return_value=None), \
                 patch('pathlib.Path.home', return_value=Path(d)), \
                 patch.dict(os.environ, {'HAIZEN_CLAUDE_PATH': ''}):
                self.assertEqual(executor.claude_disponivel(), str(exe))

    def test_manual_path_wins_and_must_exist(self):
        from haizen import executor
        with patch.dict(os.environ, {'HAIZEN_CLAUDE_PATH': '/nao/existe/claude'}), \
             patch('shutil.which', return_value='/usr/bin/claude'):
            self.assertIsNone(executor.claude_disponivel())


if __name__ == '__main__':
    unittest.main()

import csv
import datetime as dt
import http.client
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SEGREDO = 'Xy7#segredo99'


def _csv(pasta: Path, nome: str, linhas: list[dict]):
    if not linhas:
        (pasta / f'{nome}_export.csv').write_text('', encoding='utf-8')
        return
    with open(pasta / f'{nome}_export.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]))
        w.writeheader()
        w.writerows(linhas)


def _base44(pasta: Path):
    """Exportação inventada no formato do Base44."""
    meta = {'created_date': '2026-01-05T10:00:00', 'updated_date': '2026-01-06T10:00:00',
            'created_by_id': 'x', 'created_by': 'x', 'is_sample': 'false'}
    _csv(pasta, 'Cliente', [
        {'nome_empresa': 'Agência Norte', 'contato': '3899', 'email': 'a@n.com', 'status': 'Ativo',
         'endereco': '', 'observacoes': '', 'documentos_urls': '[]', 'id': 'c1', **meta},
        {'nome_empresa': "'+DOCE", 'contato': '', 'email': '', 'status': 'Ex-Cliente',
         'endereco': '', 'observacoes': '', 'documentos_urls': '[]', 'id': 'c2', **meta},
    ])
    _csv(pasta, 'Receita', [
        {'cliente_id': 'c1', 'cliente_nome': 'Agência Norte', 'valor': '1500.5',
         'descricao_servico': 'Vídeos Padaria Sol', 'data_vencimento': '2026-03-10',
         'recebido': 'true', 'data_recebimento': '2026-03-12', 'mes_referencia': '2026-03', 'id': 'r1', **meta},
        {'cliente_id': 'c2', 'cliente_nome': "'+DOCE", 'valor': '200', 'descricao_servico': 'Rótulos',
         'data_vencimento': '2026-03-20', 'recebido': 'false', 'data_recebimento': '',
         'mes_referencia': '2026-03', 'id': 'r2', **meta},
    ])
    _csv(pasta, 'Despesa', [
        {'custo': 'Adobe', 'categoria': 'Assinaturas', 'valor': '80', 'data_pagamento': '2026-03-02',
         'data_vencimento': '2026-03-01', 'pago': 'true', 'mes_referencia': '2026-02', 'id': 'd1', **meta},
    ])
    _csv(pasta, 'Tarefa', [
        {'titulo': 'Landing Page - Padaria Sol', 'responsavel_id': '', 'responsavel_nome': '',
         'descricao': f'Briefing no Drive\n\nWordpress\nusuario\n{SEGREDO}', 'data_entrega': '2026-03-15',
         'prioridade': 'Alta', 'cliente_nome': 'Agência Norte', 'ordem': '', 'horas_estimadas': '4',
         'cliente_id': 'c1', 'arquivos_urls': '[]', 'status': 'Concluída', 'id': 't1',
         'comentarios': json.dumps([{'autor_nome': 'H', 'texto': 'site.com.br\nsite\nAb1!cdefgh', 'data': '2026-03-14'},
                                    {'autor_nome': 'H', 'texto': 'Aprovado pelo cliente', 'data': '2026-03-15'}]),
         **meta},
        {'titulo': 'Cardápio', 'responsavel_id': '', 'responsavel_nome': '', 'descricao': 'Combo R$ 50 e R$ 120',
         'data_entrega': '2000-01-01', 'prioridade': 'Média', 'cliente_nome': '', 'ordem': '',
         'horas_estimadas': '', 'cliente_id': '', 'arquivos_urls': '[]', 'status': 'A Fazer', 'id': 't2',
         'comentarios': '[]', **meta},
    ])
    _csv(pasta, 'Subtarefa', [
        {'tarefa_id': 't1', 'titulo': 'Layout', 'concluida': 'true', 'ordem': '', 'id': 's1', **meta},
    ])
    _csv(pasta, 'Oportunidade', [])


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'HAIZEN_DB': str(self.dir / 'h.db'),
                                           'HAIZEN_ENTREGAS_DIR': str(self.dir / 'e')})
        self.env.start()
        (self.dir / 'csv').mkdir()
        _base44(self.dir / 'csv')

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def importar(self):
        from haizen import importar_base44
        return importar_base44.importar(self.dir / 'csv')


class SepararAcessosTests(unittest.TestCase):
    def test_keyword_block_moves_and_plain_text_stays(self):
        from haizen.importar_base44 import separar_acessos, AVISO_ACESSOS
        limpo, ac = separar_acessos('Fazer banner\n\nHOSTGATOR\nEmail: a@b.com\nSenha: 123')
        self.assertTrue(limpo.startswith('Fazer banner'))
        self.assertIn(AVISO_ACESSOS, limpo)
        self.assertIn('Senha: 123', ac)
        self.assertNotIn('Senha', limpo)

    def test_password_without_keyword_is_caught(self):
        from haizen.importar_base44 import separar_acessos
        limpo, ac = separar_acessos('meusite.com.br\nadmin\nQw3$rty!9z')
        self.assertIn('Qw3$rty!9z', ac)
        self.assertNotIn('Qw3$rty!9z', limpo)

    def test_prices_and_links_are_not_passwords(self):
        from haizen.importar_base44 import separar_acessos
        texto = ('Combo $500\nCombo $120\n\nhttps://drive.google.com/drive/folders/1Ab?usp=sharing'
                 '\n\nPágina 1 ✅ Texto: Por que comprar?')
        self.assertEqual(separar_acessos(texto), (texto, ''))


class ImportacaoTests(_Base):
    def test_counts_and_idempotency(self):
        r1 = self.importar()
        self.assertEqual((r1['clientes_novos'], r1['receitas_novas'], r1['despesas_novas'],
                          r1['tarefas_novas'], r1['subtarefas']), (2, 2, 1, 2, 1))
        r2 = self.importar()
        self.assertEqual(r2['receitas_atualizadas'], 2)
        self.assertNotIn('receitas_novas', r2)
        from haizen.central import dados
        self.assertEqual(len(dados.listar('receitas')), 2)

    def test_secrets_leave_description_and_comments(self):
        self.importar()
        from haizen import store
        with store.conexao() as con:
            t = con.execute("SELECT * FROM tarefas WHERE base44_id='t1'").fetchone()
        self.assertNotIn(SEGREDO, t['descricao'])
        self.assertNotIn('Ab1!cdefgh', t['comentarios'])
        self.assertIn(SEGREDO, t['acessos'])
        self.assertIn('Ab1!cdefgh', t['acessos'])
        self.assertIn('Aprovado pelo cliente', t['comentarios'])
        self.assertIn('Briefing no Drive', t['descricao'])

    def test_listing_never_exposes_access(self):
        self.importar()
        from haizen.central import dados
        tarefas = dados.listar('tarefas')
        self.assertTrue(all('acessos' not in t for t in tarefas))
        com = [t for t in tarefas if t['tem_acessos']]
        self.assertEqual(len(com), 1)
        self.assertIn(SEGREDO, dados.acessos_da_tarefa(com[0]['id']))

    def test_plus_names_lose_the_base44_apostrophe(self):
        self.importar()
        from haizen.central import dados
        self.assertIn('+DOCE', [c['nome'] for c in dados.listar('clientes')])

    def test_existing_voice_client_is_merged_not_duplicated(self):
        from haizen import store
        store.salvar_cliente('Agência Norte', {'tom': 'leve'})
        self.importar()
        from haizen.central import dados
        nomes = [c['nome'] for c in dados.listar('clientes')]
        self.assertEqual(nomes.count('Agência Norte'), 1)
        self.assertEqual(store.buscar_cliente('agencia norte')['dados'], {'tom': 'leve'})

    def test_drive_folders_become_brands_linked_to_payer(self):
        self.importar()
        drive = self.dir / 'drive'
        for n in ('01 - Agência Norte', '02 - Padaria Sol', '03 - Sem Dono Ltda'):
            (drive / n).mkdir(parents=True)
        from haizen import importar_base44
        r = importar_base44.importar_drive(drive)
        self.assertEqual(r['marcas_novas'], 3)
        from haizen.central import dados
        marcas = {m['nome']: m['cliente_nome'] for m in dados.listar('marcas')}
        self.assertEqual(marcas['Agência Norte'], 'Agência Norte')
        self.assertEqual(marcas['Padaria Sol'], 'Agência Norte')   # pelas tarefas/receitas
        self.assertIsNone(marcas['Sem Dono Ltda'])


class PainelTests(_Base):
    def test_numbers_for_the_month(self):
        self.importar()
        from haizen.central import dados
        p = dados.painel('2026-03-01', '2026-03-31')
        self.assertEqual(p['receita'], 1500.5)
        self.assertEqual(p['custos'], 80.0)
        self.assertEqual(p['lucro'], 1420.5)
        self.assertEqual(p['a_receber'], 200.0)
        self.assertEqual(p['vencido'], 200.0)          # venceu em 20/03/2026
        self.assertEqual(p['tarefas_atrasadas'], 1)
        self.assertEqual(p['top_clientes'][0]['cliente'], 'Agência Norte')
        self.assertEqual(p['serie'][-1], {'mes': '2026-03', 'receita': 1500.5, 'custos': 80.0})

    def test_marking_received_sets_the_date_and_unmarking_clears_it(self):
        self.importar()
        from haizen.central import dados
        r = [x for x in dados.listar('receitas') if not x['recebido']][0]
        r = dados.atualizar('receitas', r['id'], {'recebido': True})
        self.assertEqual(r['data_recebimento'], dt.date.today().isoformat())
        r = dados.atualizar('receitas', r['id'], {'recebido': False})
        self.assertEqual(r['data_recebimento'], '')

    def test_brazilian_money_input(self):
        from haizen.central import dados
        self.assertEqual(dados.centavos('1.234,56'), 123456)
        self.assertEqual(dados.centavos('R$ 80'), 8000)
        self.assertEqual(dados.centavos(3398.61), 339861)

    def test_invalid_stage_is_refused(self):
        from haizen.central import dados
        with self.assertRaises(ValueError):
            dados.criar('oportunidades', {'titulo': 'Site', 'etapa': 'Voando'})

    def test_finishing_a_task_records_when(self):
        from haizen.central import dados
        t = dados.criar('tarefas', {'titulo': 'Logo'})
        t = dados.atualizar('tarefas', t['id'], {'status': 'Concluída'})
        self.assertEqual(t['concluida_em'], dt.date.today().isoformat())
        t = dados.atualizar('tarefas', t['id'], {'status': 'Em Revisão'})
        self.assertEqual(t['concluida_em'], '')

    def test_deleting_a_client_keeps_its_money(self):
        self.importar()
        from haizen.central import dados
        cid = [c for c in dados.listar('clientes') if c['nome'] == 'Agência Norte'][0]['id']
        dados.apagar('clientes', cid)
        self.assertEqual(len(dados.listar('receitas')), 2)


class ServidorTests(_Base):
    def setUp(self):
        super().setUp()
        self.importar()
        from haizen.central import servidor
        self.porta = 18000 + os.getpid() % 1000
        self.p = patch.object(servidor, 'PORTA', self.porta)
        self.p.start()
        servidor.iniciar(abrir_navegador=False)
        self.servidor = servidor

    def tearDown(self):
        self.servidor.parar()
        self.p.stop()
        super().tearDown()

    def pedir(self, metodo, caminho, corpo=None, cab=None):
        c = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=5)
        c.request(metodo, caminho, body=json.dumps(corpo) if corpo is not None else None,
                  headers=cab if cab is not None else {'X-Central': '1'})
        r = c.getresponse()
        texto = r.read().decode('utf-8')
        c.close()
        return r.status, texto

    def test_api_requires_header_and_local_host(self):
        self.assertEqual(self.pedir('GET', '/api/painel', cab={})[0], 403)
        self.assertEqual(self.pedir('GET', '/api/painel', cab={'X-Central': '1', 'Host': 'evil.com'})[0], 403)
        self.assertEqual(self.pedir('GET', '/api/painel?de=2026-03-01&ate=2026-03-31')[0], 200)

    def test_create_edit_delete_round_trip(self):
        s, t = self.pedir('POST', '/api/despesas', {'descricao': 'Domínio', 'valor': '45,90'})
        self.assertEqual(s, 200)
        d = json.loads(t)
        self.assertEqual(d['valor'], 45.9)
        s, t = self.pedir('PATCH', f"/api/despesas/{d['id']}", {'pago': True})
        self.assertTrue(json.loads(t)['pago'])
        self.assertEqual(self.pedir('DELETE', f"/api/despesas/{d['id']}")[0], 200)
        self.assertEqual(self.pedir('GET', f"/api/despesas/{d['id']}")[0], 404)

    def test_errors_are_readable(self):
        s, t = self.pedir('POST', '/api/oportunidades', {'titulo': 'X', 'etapa': 'Voando'})
        self.assertEqual(s, 400)
        self.assertIn('Lead', json.loads(t)['erro'])

    def test_static_page_and_no_path_escape(self):
        s, t = self.pedir('GET', '/', cab={})
        self.assertEqual(s, 200)
        self.assertIn('Central HAIZEN', t)
        s, t = self.pedir('GET', '/../../haizen/store.py', cab={})
        self.assertNotIn('import sqlite3', t)

    def test_access_only_through_its_own_route(self):
        s, t = self.pedir('GET', '/api/tarefas')
        self.assertNotIn(SEGREDO, t)
        tid = [x for x in json.loads(t) if x['tem_acessos']][0]['id']
        s, t = self.pedir('GET', f'/api/tarefas/{tid}/acessos')
        self.assertIn(SEGREDO, t)


class VozTests(_Base):
    def test_voice_finance_summary(self):
        import importlib
        import plugins.haizen as plugin
        plugin = importlib.reload(plugin)
        from haizen.central import dados
        dados.criar('receitas', {'descricao': 'Teste', 'valor': '1.000,00', 'recebido': True})
        resp = plugin.run({'acao': 'financeiro'})
        self.assertIn('R$ 1.000,00', resp)


class TrocaDeVersaoTests(unittest.TestCase):
    """Uma cópia antiga escondida na porta não pode prender o navegador no código velho."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.porta = 19000 + os.getpid() % 900
        self.env = {**os.environ, "HAIZEN_DB": str(Path(self.tmp.name) / "h.db"),
                    "HAIZEN_CENTRAL_PORTA": str(self.porta)}

    def tearDown(self):
        from haizen.central import servidor
        servidor.parar()
        self.tmp.cleanup()

    def _antiga(self):
        import subprocess
        import sys
        import time
        codigo = ("from haizen.central import servidor; import time; "
                  "servidor.iniciar(abrir_navegador=False); time.sleep(60)")
        proc = subprocess.Popen([sys.executable, "-c", codigo], env=self.env,
                                cwd=str(Path(__file__).resolve().parent.parent))
        for _ in range(50):
            try:
                c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=1)
                c.request("GET", "/")
                c.close()
                return proc
            except OSError:
                time.sleep(0.1)
        proc.kill()
        self.fail("a cópia antiga não subiu")

    def test_new_copy_takes_over_the_port(self):
        from haizen.central import servidor
        antiga = self._antiga()
        try:
            with patch.object(servidor, "PORTA", self.porta):
                servidor.iniciar(abrir_navegador=False, assumir=True, espera=15)
                antiga.wait(timeout=10)                 # a antiga fechou sozinha
                c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
                c.request("GET", "/api/sistema/versao", headers={"X-Central": "1"})
                self.assertEqual(json.loads(c.getresponse().read())["pid"], os.getpid())
        finally:
            if antiga.poll() is None:
                antiga.kill()

    def test_quit_only_from_this_pc(self):
        from haizen.central import servidor
        with patch.object(servidor, "PORTA", self.porta), \
             patch.object(servidor.os, "_exit") as sair:
            servidor.iniciar(abrir_navegador=False)
            c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
            c.request("POST", "/api/sistema/sair", body=b"{}",
                      headers={"X-Central": "1", "Host": "meu-pc.tail123.ts.net"})
            self.assertEqual(c.getresponse().status, 400)
            sair.assert_not_called()

    def test_version_check(self):
        from haizen.central import servidor
        with patch.object(servidor, "VERSAO_INICIAL", servidor.versao_no_disco()):
            self.assertFalse(servidor.desatualizado())
        with patch.object(servidor, "VERSAO_INICIAL", servidor.versao_no_disco() - 3600):
            self.assertTrue(servidor.desatualizado())

    def test_restart_needs_the_launcher(self):
        from haizen.central import servidor
        with patch.object(servidor, "COMANDO_REINICIO", None):
            with self.assertRaises(ValueError):
                servidor.reiniciar()


if __name__ == '__main__':
    unittest.main()

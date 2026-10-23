import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import zipfile

from memory import memory_manager as memory
from memory import conversation_store
from manage_memory import import_legacy, export_backup


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'memory' / 'long_term.json'
        self.legacy = self.root / 'old' / 'long_term.json'
        for item in (patch.object(memory, 'MEMORY_PATH', self.path),
                     patch.object(memory, 'LEGACY_MEMORY_PATH', self.legacy),
                     patch.dict(os.environ, {'JARVIS_DATA_DIR': str(self.root)})):
            item.start()
            self.addCleanup(item.stop)

    def test_migrates_once_and_preserves_original(self):
        self.legacy.parent.mkdir()
        self.legacy.write_text(json.dumps({'identity': {'name': {'value': 'Hiago'}}}))
        original = self.legacy.read_bytes()
        self.assertEqual(memory.load_memory()['identity']['name']['value'], 'Hiago')
        memory.remember('city', 'Recife', 'identity')
        self.assertEqual(memory.load_memory()['identity']['city']['value'], 'Recife')
        self.assertEqual(self.legacy.read_bytes(), original)

    def test_concurrent_fact_and_session_writes_do_not_overwrite_each_other(self):
        def write(index):
            memory.remember(str(index), 'valor ' + str(index))
            memory.save_session_summary('sessão ' + str(index))
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(write, range(20)))
        saved = memory.load_memory()
        self.assertEqual(len(saved['notes']), 20)
        self.assertEqual(len(saved['sessions']), 20)

    def test_separate_process_writes_are_serialized(self):
        code = 'from memory.memory_manager import remember; import sys; [remember(sys.argv[1]+str(i), "persistido") for i in range(6)]'
        children = [subprocess.Popen([sys.executable, '-c', code, str(n)], env=os.environ.copy(), stdout=subprocess.DEVNULL) for n in range(3)]
        for child in children:
            self.assertEqual(child.wait(timeout=30), 0)
        self.assertEqual(len(memory.load_memory()['notes']), 18)

    def test_recovery_uses_last_good_backup(self):
        memory.remember('first', 'primeiro')
        memory.remember('second', 'segundo')
        self.path.write_text('{corrompido')
        self.assertEqual(memory.load_memory()['notes']['first']['value'], 'primeiro')
        memory.remember('third', 'terceiro')
        self.assertIn('third', memory.load_memory()['notes'])

    def test_missing_primary_recovers_backup_instead_of_empty_memory(self):
        memory.remember('first', 'preservado')
        memory.remember('second', 'mais recente')
        self.path.unlink()
        self.assertEqual(memory.load_memory()['notes']['first']['value'], 'preservado')

    def test_unrecoverable_corruption_is_never_overwritten(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('danificado')
        with self.assertRaises(RuntimeError):
            memory.remember('new', 'não substituir')
        self.assertEqual(self.path.read_text(), 'danificado')

    def test_large_facts_and_consumed_sessions_remain_searchable(self):
        value = 'contexto longo ' * 150
        memory.remember('projeto', value)
        memory.save_session_summary('Projeto orçamento aprovado pelo cliente')
        self.assertIsNotNone(memory.pop_last_session())
        self.assertIsNone(memory.pop_last_session())
        self.assertEqual(memory.load_memory()['notes']['projeto']['value'], value)
        self.assertEqual(len(memory.load_memory()['sessions']), 1)
        self.assertIn('orçamento aprovado', memory.search_memory('orçamento'))

    def test_completed_turns_survive_restart_and_are_recalled(self):
        conversation_store.record_turn('user', 'Trabalhamos no contrato do cliente Aurora')
        conversation_store.record_turn('assistant', 'O contrato Aurora está preparado')
        self.assertEqual(len(conversation_store.find_turns(['Aurora'])), 2)
        self.assertIn('contrato', memory.search_memory('Aurora'))

    def test_import_keeps_newer_values_and_backup_excludes_credentials(self):
        memory.remember('name', 'atual', 'identity')
        source = self.root / 'old.json'
        source.write_text(json.dumps({'identity': {'name': {'value': 'antigo'}, 'city': {'value': 'Recife'}}}))
        self.assertEqual(import_legacy(source), 1)
        self.assertEqual(memory.load_memory()['identity']['name']['value'], 'atual')
        conversation_store.record_turn('user', 'mensagem preservada')
        secret = self.root / 'google' / 'token_calendar.json'
        secret.parent.mkdir()
        secret.write_text('{"token":"fake-test-token"}')
        destination = self.root / 'backup.zip'
        export_backup(destination)
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(set(archive.namelist()), {'long_term.json', 'conversations.db'})
        with self.assertRaises(FileExistsError):
            export_backup(destination)


if __name__ == '__main__':
    unittest.main()

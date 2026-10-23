"""Inspect location, import older memories and export a user-controlled backup."""
import argparse
import json
import sqlite3
import tempfile
from pathlib import Path
import zipfile


def import_legacy(source):
    from memory import memory_manager as memory
    imported = json.loads(Path(source).read_text(encoding='utf-8'))
    if not isinstance(imported, dict):
        raise ValueError('O arquivo precisa conter uma memória JSON válida.')
    added = 0
    with memory._lock:
        current = memory.load_memory()
        for category, entries in imported.items():
            if isinstance(entries, dict):
                target = current.setdefault(category, {})
                if not isinstance(target, dict):
                    continue
                for key, value in entries.items():
                    if key not in target:
                        target[key] = value
                        added += 1
            elif category == 'sessions' and isinstance(entries, list):
                target = current.setdefault('sessions', [])
                for entry in entries:
                    if entry not in target:
                        target.append(entry)
                        added += 1
        memory.save_memory(current)
    return added


def export_backup(destination):
    from core.data_paths import data_dir
    from memory import memory_manager as memory
    destination = Path(destination)
    # Refuse overwriting an existing backup or any live data file.
    with tempfile.TemporaryDirectory() as temporary:
        with memory._lock:
            data = memory.load_memory()
        with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('long_term.json', json.dumps(data, ensure_ascii=False, indent=2))
            source = data_dir() / 'conversations.db'
            if source.exists():
                snapshot = Path(temporary) / 'conversations.db'
                with sqlite3.connect(source) as original, sqlite3.connect(snapshot) as target:
                    original.backup(target)
                archive.write(snapshot, 'conversations.db')


def main():
    parser = argparse.ArgumentParser(description='Memória persistente do Jarvis. Não inclui chaves nem tokens Google nos backups.')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    sub.add_parser('import').add_argument('source')
    sub.add_parser('export').add_argument('destination')
    args = parser.parse_args()
    if args.command == 'status':
        from memory.memory_manager import MEMORY_PATH
        print('Memória:', MEMORY_PATH)
    elif args.command == 'import':
        print(f'{import_legacy(args.source)} registros adicionados. Registros existentes preservados.')
    else:
        export_backup(args.destination)
        print('Backup criado sem chaves de API nem tokens de autorização. Guarde-o em local privado.')


if __name__ == '__main__':
    main()

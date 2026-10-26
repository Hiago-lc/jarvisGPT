"""Authorize read access to a locally mounted Google Drive folder."""
import argparse
import json
from pathlib import Path
from core.atomic_storage import write_json
from memory.config_manager import CONFIG_FILE


def authorize(folder, config_file=CONFIG_FILE):
    target = Path(folder).expanduser().resolve(strict=True)
    if not target.is_dir():
        raise ValueError('Selecione uma pasta, não um arquivo.')
    path = Path(config_file)
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    roots = data.get('file_read_roots', [])
    if not isinstance(roots, list):
        raise ValueError('file_read_roots precisa ser uma lista na configuração.')
    if str(target) not in roots:
        data['file_read_roots'] = roots + [str(target)]
        write_json(path, data)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', required=True, help='Pasta já montada pelo Google Drive para computador; concede leitura local.')
    args = parser.parse_args()
    try:
        target = authorize(args.folder)
        print(f'Leitura local autorizada: {target}. Não é uma conexão OAuth com a API do Drive.')
    except (OSError, ValueError) as error:
        parser.exit(1, f'Não foi possível autorizar a pasta ({type(error).__name__}). Confira se ela está montada e acessível.\n')

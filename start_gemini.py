"""Restore Gemini Live without removing saved settings or other providers."""
import json
import os
import platform


def configure():
    from memory import config_manager as cm
    data = cm.load_api_keys()
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not (key or data.get('gemini_api_key')):
        raise SystemExit('Configure sua chave Gemini na tela inicial usando python main.py, depois inicie novamente.')
    if key:
        data['gemini_api_key'] = key
    providers = data.setdefault('providers', {})
    providers.update(mode='gemini', sidecar='', sidecar_first=False)
    data.setdefault('os_system', platform.system())
    cm.ensure_config_dir()
    cm.CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')
    os.environ.pop('JARVIS_OPENAI_ONLY', None)
    os.environ.pop('JARVIS_NO_GEMINI', None)


if __name__ == '__main__':
    configure()
    from main import main
    main()

"""Discover and test visual REST models using a synthetic image, never the desktop."""
import argparse
import io
import json
from core import gemini
from core.atomic_storage import write_json


def configure(save=False):
    from google.genai import types
    from PIL import Image
    if not gemini.api_key():
        print('Chave Gemini não configurada. Configure-a no Jarvis primeiro.')
        return 1
    cl = gemini.client(timeout_ms=15000, strict_timeout=True)
    try:
        models = []
        for model in cl.models.list():
            name = (model.name or '').removeprefix('models/')
            actions = model.supported_actions or []
            if name.startswith('gemini-') and 'generateContent' in actions and not any(word in name for word in ('image', 'tts', 'live', 'robotics', 'embedding')):
                models.append(name)
        models = sorted(set(models), key=lambda name: ('flash' not in name, 'preview' in name, 'latest' not in name, name))
        print('Modelos de geração listados pela sua chave:')
        for name in models:
            print(' - ' + name)
        if not save:
            print('Para testar imagem e salvar um modelo aprovado: python check_gemini_visual.py --configure')
            return 0
        data = io.BytesIO()
        Image.new('RGB', (64, 64), (255, 0, 0)).save(data, format='PNG')
        for name in models[:4]:
            try:
                reply = cl.models.generate_content(model=name, contents=[types.Part.from_bytes(data=data.getvalue(), mime_type='image/png'), 'Identify the uniform color in this image. Return JSON {"color":"red|green|blue|black|white"}.'], config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0, max_output_tokens=1024))
                if json.loads(reply.text).get('color') != 'red':
                    print(f'{name}: teste visual inconclusivo')
                    continue
                # Read again so the key and all existing settings are preserved.
                settings = json.loads(gemini._KEY_FILE.read_text(encoding='utf-8'))
                settings['gemini_visual_model'] = name
                write_json(gemini._KEY_FILE, settings)
                print(f'Modelo visual testado e salvo: {name}. Reinicie o Jarvis.')
                return 0
            except Exception as error:
                # Never print SDK exceptions that might include request details.
                print(f'{name}: teste recusado ou indisponível ({type(error).__name__})')
        print('Nenhum modelo foi aprovado. Confira acesso, cota e rede; configuração preservada.')
        return 1
    except Exception as error:
        print(f'Não foi possível consultar os modelos ({type(error).__name__}). Confira acesso e rede.')
        return 1
    finally:
        cl.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configure', action='store_true', help='Testa até quatro modelos com imagem sintética e salva o primeiro aprovado. Pode consumir cota Gemini.')
    raise SystemExit(configure(parser.parse_args().configure))

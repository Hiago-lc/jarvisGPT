"""Authorize Calendar with a Google Cloud Desktop OAuth client."""
import argparse


def main():
    parser = argparse.ArgumentParser(description='Conectar Google Agenda ao Jarvis por OAuth no navegador.')
    parser.add_argument('--client', help='JSON de cliente OAuth para aplicativo de computador criado no Google Cloud')
    parser.add_argument('--disconnect', action='store_true', help='Apagar autorização local; revogue também no painel da conta Google se desejar')
    args = parser.parse_args()
    from core import google_calendar
    if args.disconnect:
        google_calendar.token_path().unlink(missing_ok=True)
        print('Autorização local removida. Para revogar o acesso, use as configurações de segurança da conta Google.')
        return
    if not args.client:
        parser.error('informe --client caminho/client_secret.json')
    try:
        google_calendar.connect(args.client)
        print('Google Agenda conectado. Inicie python start_gemini.py.')
    except Exception:
        raise SystemExit('Não foi possível conectar. Confira o cliente OAuth Desktop, a API Calendar habilitada, o usuário de teste e a autorização no navegador. Nenhum token será exibido.')


if __name__ == '__main__':
    main()

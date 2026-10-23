"""Authorize Calendar with a Google Cloud Desktop OAuth client."""
import argparse


def main():
    parser = argparse.ArgumentParser(description='Conectar Google Agenda ao Jarvis por OAuth no navegador.')
    parser.add_argument('--client', help='JSON de cliente OAuth para aplicativo de computador criado no Google Cloud')
    parser.add_argument('--check', action='store_true', help='Diagnóstico somente de leitura; não cria eventos nem mostra dados da agenda')
    parser.add_argument('--disconnect', action='store_true', help='Apagar autorização local; revogue também no painel da conta Google se desejar')
    args = parser.parse_args()
    from core import google_calendar
    if sum((bool(args.client), args.check, args.disconnect)) != 1:
        parser.error('use apenas uma opção: --client, --check ou --disconnect')
    if args.check:
        ok, code, message = google_calendar.check_connection()
        print(f'[GoogleAgenda] {code}: {message}')
        if not ok:
            raise SystemExit(1)
        return
    if args.disconnect:
        google_calendar.token_path().unlink(missing_ok=True)
        print('Autorização local removida. Para revogar o acesso, use as configurações de segurança da conta Google.')
        return
    if not args.client:
        parser.error('informe --client caminho/client_secret.json')
    try:
        google_calendar.connect(args.client)
        print('Google Agenda conectado. Inicie python start_gemini.py.')
    except google_calendar.CalendarSetupError as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit('Não foi possível conectar. Confira o cliente OAuth Desktop, a API Calendar habilitada, o usuário de teste e a autorização no navegador. Nenhum token será exibido.')


if __name__ == '__main__':
    main()

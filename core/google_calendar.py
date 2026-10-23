"""Google Calendar OAuth on the user's desktop. No credentials in the checkout."""
import json
from core.atomic_storage import write_json
from core.data_paths import data_dir

SCOPES = ['https://www.googleapis.com/auth/calendar.events']


def token_path():
    return data_dir() / 'google' / 'token_calendar.json'


def _save(credentials):
    write_json(token_path(), json.loads(credentials.to_json()))


def connect(client_file):
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES, autogenerate_code_verifier=True)
    # Desktop OAuth uses a loopback listener, PKCE and the user's own browser.
    credentials = flow.run_local_server(port=0, open_browser=True,
        authorization_prompt_message='Autorize o Jarvis no navegador aberto.',
        success_message='Google Agenda conectado ao Jarvis. Pode fechar esta aba.')
    _save(credentials)


def service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    path = token_path()
    if not path.exists():
        raise RuntimeError('Google Agenda não conectado. Execute python connect_google_calendar.py --client caminho/client_secret.json no seu computador.')
    credentials = Credentials.from_authorized_user_file(str(path), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _save(credentials)
    if not credentials.valid:
        raise RuntimeError('A autorização do Google expirou ou foi revogada. Conecte o Google Agenda novamente.')
    return build('calendar', 'v3', credentials=credentials, cache_discovery=False)

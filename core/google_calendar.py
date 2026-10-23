"""Google Calendar OAuth on the user's desktop. No credentials in the checkout."""
import json
from core.atomic_storage import write_json
from core.data_paths import data_dir
from core.google_calendar_errors import CalendarSetupError

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
        access_type='offline', prompt='consent', include_granted_scopes='true',
        authorization_prompt_message='Autorize o Jarvis no navegador aberto.',
        success_message='Google Agenda conectado ao Jarvis. Pode fechar esta aba.')
    granted = getattr(credentials, 'granted_scopes', None)
    if isinstance(granted, (list, tuple, set)) and not set(SCOPES).issubset(granted):
        raise CalendarSetupError('O Google não concedeu a permissão para eventos. Repita a conexão e aceite o acesso ao Google Agenda.')
    _save(credentials)


def service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    path = token_path()
    if not path.exists():
        raise CalendarSetupError('Google Agenda não conectado. Execute python connect_google_calendar.py --client caminho/client_secret.json no seu computador.')
    try:
        credentials = Credentials.from_authorized_user_file(str(path), SCOPES)
    except (ValueError, KeyError):
        raise CalendarSetupError('O arquivo de autorização local está inválido. Reconecte com python connect_google_calendar.py --client "caminho/client_secret.json". O arquivo atual foi preservado.') from None
    if credentials.expired and credentials.refresh_token:
        from google.auth.exceptions import RefreshError
        try:
            credentials.refresh(Request())
        except RefreshError:
            raise CalendarSetupError('Não foi possível renovar a autorização Google; ela pode ter expirado ou sido revogada. Reconecte com python connect_google_calendar.py --client "caminho/client_secret.json".') from None
        _save(credentials)
    if not credentials.valid:
        raise CalendarSetupError('A autorização do Google expirou ou foi revogada. Conecte o Google Agenda novamente.')
    return build('calendar', 'v3', credentials=credentials, cache_discovery=False)


def check_connection():
    """Read-only check; never creates a test appointment or displays event text."""
    from datetime import datetime, timezone
    from core.google_calendar_errors import diagnose
    try:
        service().events().list(calendarId='primary', timeMin=datetime.now(timezone.utc).isoformat(),
                                maxResults=1, fields='kind').execute(num_retries=0)
        return True, 'read_ok', 'Autorização e leitura da agenda principal funcionando. Isso não confirma permissão de escrita em outras agendas.'
    except Exception as error:
        code, reason = diagnose(error)
        if isinstance(error, CalendarSetupError) and getattr(error, 'resp', None) is None:
            reason = str(error)
        return False, code, reason

"""Create and list user-requested Google Calendar events, never through clicking."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from core import outcome


def _datetime(value):
    if not isinstance(value, str):
        raise ValueError('Informe data e hora ISO 8601 com fuso, por exemplo 2026-10-23T14:00:00-03:00.')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Falta o fuso horário. Use um horário ISO 8601 com deslocamento, por exemplo -03:00.')
    return result


def create_body(params):
    title = params.get('title')
    if not isinstance(title, str):
        raise ValueError('Informe o título do compromisso.')
    title = title.strip()
    if not title or len(title) > 200:
        raise ValueError('Informe um título de até 200 caracteres.')
    start, end = _datetime(params.get('start')), _datetime(params.get('end'))
    if end <= start:
        raise ValueError('O término precisa ser posterior ao início.')
    zone = str(params.get('timezone') or 'America/Sao_Paulo')
    zoneinfo = ZoneInfo(zone)
    if any(value.utcoffset() != value.astimezone(zoneinfo).utcoffset() for value in (start, end)):
        raise ValueError("O deslocamento do horário não corresponde ao fuso informado. Confira a hora e a timezone.")
    body = {'summary': title, 'description': str(params.get('description') or '')[:8000],
            'location': str(params.get('location') or '')[:1000],
            'start': {'dateTime': start.isoformat(), 'timeZone': zone},
            'end': {'dateTime': end.isoformat(), 'timeZone': zone}}
    digest = hashlib.sha256(json.dumps({'calendar': params.get('calendar_id') or 'primary', 'event': body}, sort_keys=True).encode()).hexdigest()
    body['id'] = digest
    body['extendedProperties'] = {'private': {'jarvisDigest': digest}}
    return body


def google_agenda(parameters, response=None, player=None, session_memory=None):
    params = parameters or {}
    action = params.get('action')
    try:
        if action == 'create':
            body = create_body(params)  # Validate before auth or a network write.
        elif action == 'list':
            start = _datetime(params['start']) if params.get('start') else datetime.now(timezone.utc)
            end = _datetime(params['end']) if params.get('end') else start + timedelta(days=7)
            if end <= start:
                raise ValueError('Intervalo de consulta inválido.')
        else:
            raise ValueError('Use action=create ou list.')
        from core.google_calendar import service
        events = service().events()
        calendar_id = params.get('calendar_id') or 'primary'
        if action == 'create':
            try:
                event = events.insert(calendarId=calendar_id, body=body, sendUpdates='none').execute(num_retries=0)
            except Exception as error:
                if getattr(getattr(error, 'resp', None), 'status', None) != 409:
                    raise
                event = events.get(calendarId=calendar_id, eventId=body['id']).execute(num_retries=0)
                if event.get('extendedProperties', {}).get('private', {}).get('jarvisDigest') != body['id']:
                    raise RuntimeError('Conflito de evento; nenhuma nova inclusão foi feita.')
            if event.get('id') != body['id'] or event.get('status') == 'cancelled':
                raise RuntimeError('O Google não confirmou o evento solicitado.')
            return outcome.done('google_agenda', title=event.get('summary', body['summary']), start=body['start']['dateTime'], event_id=event['id'], link=event.get('htmlLink'), verified=True)
        result = events.list(calendarId=calendar_id, timeMin=start.isoformat(), timeMax=end.isoformat(), singleEvents=True, orderBy='startTime', maxResults=30).execute(num_retries=1)
        rows = [{'title': e.get('summary', '(sem título)'), 'start': e.get('start'), 'end': e.get('end')} for e in result.get('items', [])]
        return outcome.untrusted('google_calendar', json.dumps({'events': rows, 'more_available': bool(result.get('nextPageToken'))}, ensure_ascii=False))
    except (ValueError, TypeError, ZoneInfoNotFoundError) as error:
        return outcome.ask('google_agenda', str(error))
    except Exception as error:
        # Do not print Google responses, OAuth tokens or personal calendar content.
        status = getattr(getattr(error, 'resp', None), 'status', None)
        if status in (401, 403):
            reason = 'O Google recusou o acesso. Confira a autorização, a API Calendar e as permissões dessa agenda.'
        elif status == 404:
            reason = 'Agenda não encontrada ou sem acesso para esta conta.'
        elif status == 429:
            reason = 'Limite de uso do Google Agenda atingido; tente mais tarde.'
        elif isinstance(error, RuntimeError):
            reason = str(error)
        else:
            reason = 'Não foi possível confirmar a operação no Google. Se repetir os mesmos dados de criação, o identificador estável evita duplicar o evento.'
        return outcome.failed('google_agenda', reason)


TOOL = {
    'name': 'google_agenda',
    'description': 'Create or list work events in the user-connected Google Calendar. Use this API tool instead of clicking the Calendar website. Only create when the user requests it; ask for missing date, time or duration. Convert natural language to offset-aware ISO 8601 using current local date. Timezone defaults to America/Sao_Paulo. This creates calendar events, not Google Tasks checkboxes. Repeated identical creates do not duplicate the event. Never invite guests or infer their emails.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'action': {'type': 'STRING', 'enum': ['create', 'list']},
        'title': {'type': 'STRING'}, 'start': {'type': 'STRING', 'description': 'ISO 8601 timestamp with UTC offset'},
        'end': {'type': 'STRING', 'description': 'ISO 8601 timestamp with UTC offset'},
        'timezone': {'type': 'STRING', 'description': 'IANA timezone, default America/Sao_Paulo'},
        'description': {'type': 'STRING'}, 'location': {'type': 'STRING'},
        'calendar_id': {'type': 'STRING', 'description': 'primary unless the user specifies another calendar'}},
        'required': ['action']},
    'handler': google_agenda,
}

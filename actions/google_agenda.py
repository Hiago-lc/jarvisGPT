"""Create and list user-requested Google Calendar events, never through clicking."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from core import outcome
from core.google_calendar_errors import CalendarSetupError


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


def _event_when(event):
    start = (event.get('start') or {})
    return start.get('dateTime') or start.get('date') or ''


def _change_body(event, params):
    """The fields to patch. Moving only the start keeps the event's duration."""
    patch = {}
    if isinstance(params.get('title'), str) and params['title'].strip():
        patch['summary'] = params['title'].strip()[:200]
    for key in ('description', 'location'):
        if isinstance(params.get(key), str):
            patch[key] = params[key][:8000 if key == 'description' else 1000]
    if params.get('start') or params.get('end'):
        zone = str(params.get('timezone') or (event.get('start') or {}).get('timeZone') or 'America/Sao_Paulo')
        old_start = (event.get('start') or {}).get('dateTime')
        old_end = (event.get('end') or {}).get('dateTime')
        start = _datetime(params['start']) if params.get('start') else _datetime(old_start)
        if params.get('end'):
            end = _datetime(params['end'])
        elif old_start and old_end:
            end = start + (_datetime(old_end) - _datetime(old_start))
        else:
            end = start + timedelta(hours=1)
        if end <= start:
            raise ValueError('O término precisa ser posterior ao início.')
        patch['start'] = {'dateTime': start.isoformat(), 'timeZone': zone}
        patch['end'] = {'dateTime': end.isoformat(), 'timeZone': zone}
    if not patch:
        raise ValueError('Diga o que mudar: novo horário, novo dia ou novo título.')
    return patch


def google_agenda(parameters, response=None, player=None, session_memory=None):
    params = parameters or {}
    action = params.get('action')
    try:
        if action in ('update', 'delete'):
            event_id = params.get('event_id')
            if not isinstance(event_id, str) or not event_id.strip():
                raise ValueError('Liste os eventos primeiro (action=list) e informe o event_id do que mudar.')
            from core.google_calendar import service
            events = service().events()
            calendar_id = params.get('calendar_id') or 'primary'
            event = events.get(calendarId=calendar_id, eventId=event_id).execute(num_retries=1)
            title = event.get('summary', '(sem título)')
            if action == 'update':
                changed = events.patch(calendarId=calendar_id, eventId=event_id, body=_change_body(event, params),
                                       sendUpdates='none').execute(num_retries=0)
                return outcome.done('google_agenda', changed=True, title=changed.get('summary', title),
                                    start=_event_when(changed), event_id=event_id, verified=True)
            # Excluir não tem volta: passa pelo aviso de confirmação na tela.
            from core import confirm
            if confirm.pending_title():
                return outcome.ask('google_agenda', 'Já existe uma confirmação esperando na tela; responda a ela primeiro.')

            def _delete():
                events.delete(calendarId=calendar_id, eventId=event_id, sendUpdates='none').execute(num_retries=0)
                return f'Excluí "{title}" do Google Agenda.'
            return confirm.request(key=f'agenda-delete-{event_id}', title=f'Excluir "{title}" do Google Agenda',
                                   detail=_event_when(event)[:16].replace('T', ' '), run=_delete)
        if action == 'create':
            body = create_body(params)  # Validate before auth or a network write.
        elif action == 'list':
            start = _datetime(params['start']) if params.get('start') else datetime.now(timezone.utc)
            end = _datetime(params['end']) if params.get('end') else start + timedelta(days=7)
            if end <= start:
                raise ValueError('Intervalo de consulta inválido.')
        else:
            raise ValueError('Use action=create, list, update ou delete.')
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
                    raise CalendarSetupError('Conflito de evento; nenhuma nova inclusão foi feita.')
            if event.get('id') != body['id'] or event.get('status') == 'cancelled':
                raise CalendarSetupError('O Google não confirmou o evento solicitado.')
            return outcome.done('google_agenda', title=event.get('summary', body['summary']), start=body['start']['dateTime'], event_id=event['id'], link=event.get('htmlLink'), verified=True)
        result = events.list(calendarId=calendar_id, timeMin=start.isoformat(), timeMax=end.isoformat(), singleEvents=True, orderBy='startTime', maxResults=30).execute(num_retries=1)
        rows = [{'event_id': e.get('id'), 'title': e.get('summary', '(sem título)'), 'start': e.get('start'), 'end': e.get('end')} for e in result.get('items', [])]
        return outcome.untrusted('google_calendar', json.dumps({'events': rows, 'more_available': bool(result.get('nextPageToken'))}, ensure_ascii=False))
    except (ValueError, TypeError, ZoneInfoNotFoundError) as error:
        return outcome.ask('google_agenda', str(error))
    except Exception as error:
        from core.google_calendar_errors import diagnose
        code, reason = diagnose(error)
        if isinstance(error, CalendarSetupError) and getattr(error, 'resp', None) is None:
            reason = str(error)
        # The old terminal receipt cut the reason after 80 characters. Emit this
        # sanitized diagnostic in full so users can act on it and share it safely.
        message = f"SYS: Google Agenda [{code}]: {reason}"
        print(f"[GoogleAgenda] {message}")
        if player:
            player.write_log(message)
        return outcome.failed('google_agenda', reason, code=code)



TOOL = {
    'name': 'google_agenda',
    'description': 'Create, list, change (move, rename) or delete events in the user-connected Google Calendar. Use this API tool instead of clicking the Calendar website. To change or delete: list first, then pass that event_id with action=update (new start/end/title; moving only the start keeps the duration) or action=delete (the user confirms on screen). Only create when the user requests it; ask for missing date, time or duration. Convert natural language to offset-aware ISO 8601 using current local date. Timezone defaults to America/Sao_Paulo. Never invite guests or infer their emails.',
    'brief': 'Google Agenda: criar, listar, mover/alterar (update com event_id) e excluir (delete com event_id) eventos. Horários ISO 8601 com -03:00.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'action': {'type': 'STRING', 'enum': ['create', 'list', 'update', 'delete']},
        'event_id': {'type': 'STRING', 'description': 'From action=list; required for update and delete.'},
        'title': {'type': 'STRING'}, 'start': {'type': 'STRING', 'description': 'ISO 8601 timestamp with UTC offset'},
        'end': {'type': 'STRING', 'description': 'ISO 8601 timestamp with UTC offset'},
        'timezone': {'type': 'STRING', 'description': 'IANA timezone, default America/Sao_Paulo'},
        'description': {'type': 'STRING'}, 'location': {'type': 'STRING'},
        'calendar_id': {'type': 'STRING', 'description': 'primary unless the user specifies another calendar'}},
        'required': ['action']},
    'handler': google_agenda,
}

"""Translate allowlisted Google error reasons without echoing response bodies."""
import json
import re


class CalendarSetupError(RuntimeError):
    """A fixed, user-safe local setup message, never a raw server response."""


def diagnose(error):
    status = getattr(getattr(error, 'resp', None), 'status', None)
    reasons = set()
    try:
        content = getattr(error, 'content', b'')
        if isinstance(content, (str, bytes)) and len(content) < 262144:
            body = json.loads(content).get('error', {})
            for item in (body.get('errors') or []) + (body.get('details') or []):
                if isinstance(item, dict) and isinstance(item.get('reason'), str):
                    reasons.add(re.sub('[^a-z0-9]', '', item['reason'].casefold()))
    except (ValueError, TypeError, AttributeError):
        pass
    if reasons & {'accessnotconfigured', 'servicedisabled', 'apidisabled'}:
        return 'api_disabled', 'A Google Calendar API está desativada no projeto do seu cliente OAuth. No Google Cloud, selecione esse mesmo projeto e habilite Google Calendar API. Aguarde a propagação e teste novamente.'
    if reasons & {'insufficientpermissions', 'accesstokenscopeinsufficient', 'insufficientauthenticationscopes'}:
        return 'scope_missing', 'O token não tem permissão para eventos. Execute novamente python connect_google_calendar.py --client "caminho/client_secret.json" e aceite a permissão para eventos do Google Agenda no navegador.'
    if reasons & {'ratelimitexceeded', 'userratelimitexceeded', 'quotaexceeded', 'dailylimitexceeded', 'calendarusagelimitsexceeded'} or status == 429:
        return 'quota_limit', 'O Google limitou a quantidade de operações. Aguarde antes de tentar novamente; confira as cotas de Calendar API no projeto. Não é necessário reconectar a conta por esse motivo.'
    if reasons & {'domainpolicy', 'orgrestrictionviolation'}:
        return 'workspace_policy', 'Uma política do Google Workspace bloqueou o acesso. Peça ao administrador da empresa para liberar o aplicativo OAuth e a agenda para sua conta.'
    if status == 401:
        return 'unauthorized', 'O Google recusou a autorização atual. Execute novamente python connect_google_calendar.py --client "caminho/client_secret.json" para autorizar a conta correta.'
    if status == 404:
        return 'calendar_not_found', 'Agenda não encontrada ou sem acesso para esta conta. Confira o calendar_id e a conta autorizada.'
    if status == 403:
        return 'permission_denied', 'O Google recusou esta operação, sem indicar uma causa reconhecida. Execute python connect_google_calendar.py --check. Confira se a conta autorizada pode fazer alterações nessa agenda e se o projeto OAuth tem Calendar API habilitada.'
    return 'unclassified', 'Não foi possível confirmar a operação no Google. Se repetir os mesmos dados de criação, o identificador estável evita duplicar o evento.'

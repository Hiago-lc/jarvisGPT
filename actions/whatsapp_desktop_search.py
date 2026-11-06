"""Verified search in native Windows WhatsApp, including Business."""
from core import outcome


def whatsapp_desktop_search(parameters, response=None, player=None, session_memory=None):
    params = parameters or {}
    query = params.get('query')
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        return outcome.ask('whatsapp_desktop_search', 'Informe o nome do contato a pesquisar, com até 200 caracteres.')
    from core.whatsapp_desktop import run_search
    result = run_search(query.strip(), str(params.get('window_title') or '').strip())
    if not result.startswith('status=done'):
        from actions import computer_control as control
        control._INPUT_TARGET_BLOCKED = True
    return result


TOOL = {
    'name': 'whatsapp_desktop_search',
    'description': 'Search contacts in the native Windows WhatsApp or WhatsApp Business application using accessibility, without Gemini vision or guessed coordinates. Prefer this over screen_find plus blind typing. Requires the app already open. Verifies focus and reads back the query. Success verifies ONLY the search text, not contact selection or message composition; inspect the results and select the exact contact before typing a draft. Does not open WhatsApp Web or send messages.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'query': {'type': 'STRING', 'description': 'Contact name to search, exactly as the user said it'},
        'window_title': {'type': 'STRING', 'description': 'Optional exact native WhatsApp window title if more than one exists'}}, 'required': ['query']},
    'handler': whatsapp_desktop_search,
}

"""Exact-contact WhatsApp Web drafts without visual model calls or sending."""
import threading
from core import outcome

_RUNNING = threading.Lock()


def whatsapp_draft(parameters, response=None, player=None, session_memory=None):
    params = parameters or {}
    action = params.get('action', 'write')
    recipient = params.get('recipient')
    text = params.get('text', '')
    if action not in ('write', 'clear', 'read') or not isinstance(recipient, str) or not recipient.strip():
        return outcome.ask('whatsapp_draft', 'Informe o nome exato do contato e a ação escrever, limpar rascunho ou ler.')
    if action == 'write' and (not isinstance(text, str) or not text.strip() or len(text) > 4000):
        return outcome.ask('whatsapp_draft', 'Informe o texto da mensagem, com até 4000 caracteres.')
    if not _RUNNING.acquire(blocking=False):
        return outcome.failed('whatsapp_draft', 'Já existe uma edição de rascunho em andamento.')
    try:
        from core.whatsapp_web import run
        ok, code, result = run(recipient.strip(), action, text, params.get('replace_existing') is True)
        if ok:
            return outcome.done('whatsapp_draft', recipient=recipient.strip(), sent=False, verified=True) + '\n' + outcome.untrusted('whatsapp_draft', result)
        if code in ('login_or_ui', 'contact_not_found', 'ambiguous_contact', 'existing_draft'):
            return outcome.ask('whatsapp_draft', result, code=code)
        return outcome.unverified('whatsapp_draft', result, code=code)
    finally:
        _RUNNING.release()


TOOL = {
    'name': 'whatsapp_draft',
    'description': 'Prepare, clear or read an UNSENT draft in WhatsApp Web by exact contact name, without Gemini vision. Prefer this tool for requests such as find Vitor and write this message but do NOT send; read the returned draft aloud when asked. Opens a dedicated visible browser; first use may require the user to scan a QR code. It never sends messages and is not a driver for the native Windows WhatsApp app. Do not use send_message when the user requests only a draft. Existing different drafts require an explicit replacement request.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'action': {'type': 'STRING', 'enum': ['write', 'clear', 'read']},
        'recipient': {'type': 'STRING', 'description': 'Exact contact display name as shown in WhatsApp Web.'},
        'text': {'type': 'STRING', 'description': 'Draft text, required for write. Never sent.'},
        'replace_existing': {'type': 'BOOLEAN', 'description': 'True only when the user explicitly requests replacing the existing draft.'}},
        'required': ['action', 'recipient']},
    'handler': whatsapp_draft,
}

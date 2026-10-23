"""Native Windows WhatsApp search, requiring a unique accessible input."""
from concurrent.futures import Future, TimeoutError
import re
import threading
import unicodedata
from core import outcome

_RUNNING = threading.Lock()
_active = None


def cancel():
    active = _active
    if active:
        active.set()


def _normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text)).casefold() if not unicodedata.combining(c)).strip()


def search_score(edit):
    name = _normalize(edit.element_info.name)
    identifier = _normalize(edit.element_info.automation_id).replace('_', '')
    if any(part in name for part in ('pesquisar ou iniciar', 'pesquisar ou comecar', 'search or start')):
        return 3
    if name in ('pesquisar', 'pesquisa', 'search') or identifier in ('searchbox', 'searchtextbox', 'searchquerytextbox'):
        return 2
    if 'pesquis' in name or re.search(r'\bsearch\b', name):
        return 1
    return 0


def search_in_window(window, query, stop):
    from core.screen_target import foreground_id
    from actions import computer_control as control
    edits = [edit for edit in window.descendants(control_type='Edit') if edit.is_visible() and edit.is_enabled()]
    ranked = [(search_score(edit), edit) for edit in edits if search_score(edit)]
    if not ranked:
        return outcome.failed('whatsapp_desktop_search', 'O WhatsApp não expôs um campo de busca reconhecido pela acessibilidade. Não digitei em outro campo.', code='search_not_accessible', edit_controls=len(edits))
    best = max(score for score, _ in ranked)
    matches = [edit for score, edit in ranked if score == best]
    if len(matches) != 1:
        return outcome.ask('whatsapp_desktop_search', 'Há mais de um campo de busca possível. Feche a busca interna da conversa ou indique o campo correto; nenhum texto foi digitado.')
    search = matches[0]
    if stop.is_set():
        return outcome.unverified('whatsapp_desktop_search', 'Busca interrompida antes da digitação.')
    # Never send input to the assistant, composer or some other foreground app.
    window.set_focus()
    search.set_focus()
    if stop.is_set() or foreground_id() != window.handle or not search.has_keyboard_focus():
        return outcome.failed('whatsapp_desktop_search', 'O Windows não confirmou o foco no campo de busca. Nada foi digitado.', code='focus_not_verified')
    try:
        search.set_edit_text(query)
    except Exception:
        return outcome.failed('whatsapp_desktop_search', 'O campo foi localizado, mas recusou edição por acessibilidade. Nenhum atalho de digitação foi usado como alternativa.', code='edit_pattern_unavailable')
    if stop.is_set():
        return outcome.unverified('whatsapp_desktop_search', 'Busca interrompida após a edição; confira o campo de busca.')
    if foreground_id() != window.handle or search.get_value().strip() != query:
        return outcome.unverified('whatsapp_desktop_search', 'A leitura do campo não confirmou a busca solicitada; não selecionei nenhum contato.', code='readback_mismatch')
    # Search is complete, but focus is still in search, not in the composer.
    # Require a new successful target before subsequent generic keyboard input.
    control._INPUT_TARGET_BLOCKED = True
    return outcome.done('whatsapp_desktop_search', query=query, query_verified=True, chat_selected=False, draft_written=False, verified=True)


def run_search(query, title=''):
    global _active
    import sys
    if sys.platform != 'win32':
        return outcome.failed('whatsapp_desktop_search', 'Esta busca é para o aplicativo nativo do Windows. Não abre o WhatsApp Web.')
    if not _RUNNING.acquire(blocking=False):
        return outcome.failed('whatsapp_desktop_search', 'Outra busca nativa ainda está em andamento.')
    stop = threading.Event()
    _active = stop
    future = Future()
    def worker():
        global _active
        try:
            import pythoncom
            pythoncom.CoInitialize()
            try:
                import psutil
                from pywinauto import Desktop
                windows = []
                for window in Desktop(backend='uia').windows():
                    name = window.window_text()
                    if not window.is_visible() or 'whatsapp' not in name.casefold():
                        continue
                    if title and name.casefold() != title.casefold():
                        continue
                    process = psutil.Process(window.process_id()).name().casefold()
                    if process in ('chrome.exe', 'msedge.exe', 'firefox.exe', 'opera.exe', 'brave.exe'):
                        continue
                    windows.append(window)
                if len(windows) != 1:
                    result = outcome.ask('whatsapp_desktop_search', 'Abra uma única janela do WhatsApp/WhatsApp Business do Windows, ou informe seu título exato. Nenhum campo foi editado.')
                else:
                    result = search_in_window(windows[0], query, stop)
                future.set_result(result)
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            future.set_result(outcome.failed('whatsapp_desktop_search', 'A busca por acessibilidade falhou. Confira pywinauto/pywin32 e se o WhatsApp está numa sessão desbloqueada. Nenhuma digitação por coordenadas foi tentada.'))
        finally:
            if _active is stop:
                _active = None
            _RUNNING.release()
    try:
        threading.Thread(target=worker, daemon=True, name='whatsapp-native-search').start()
    except Exception:
        _RUNNING.release()
        raise
    try:
        return future.result(timeout=8)
    except TimeoutError:
        stop.set()
        return outcome.unverified('whatsapp_desktop_search', 'O WhatsApp demorou para expor os controles. Interrupção solicitada; confira a busca. Não foi possível confirmar a operação.', code='uia_timeout')

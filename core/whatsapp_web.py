"""Visible WhatsApp Web draft editor. Deliberately contains no send operation."""
from concurrent.futures import Future, TimeoutError as FutureTimeout
import queue
import re
import threading
import time

from core.data_paths import data_dir

_JOBS = queue.Queue()
_WORKER_LOCK = threading.Lock()
_worker = None
_active = None


class DraftError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def cancel():
    active = _active
    if active is not None:
        active.set()


def _check(stop):
    if stop.is_set():
        raise DraftError('cancelled', 'Operação interrompida. Confira o rascunho na janela aberta; nenhuma instrução de envio foi executada.')


def _header_matches(page, recipient):
    headers = page.locator('#main header [title]')
    return any(item.is_visible() and (item.get_attribute('title') or '').strip().casefold() == recipient.casefold()
               for item in headers.all())


def edit_draft(page, recipient, action, text, replace_existing, stop):
    """All selectors are scoped to chat navigation or the message composer."""
    _check(stop)
    if not page.url.startswith('https://web.whatsapp.com/'):
        raise DraftError('wrong_site', 'A janela não está no WhatsApp Web oficial; operação cancelada.')
    if not _header_matches(page, recipient):
        search = page.locator('#side [contenteditable="true"][role="textbox"]')
        try:
            search.first.wait_for(state='visible', timeout=5000)
        except Exception:
            raise DraftError('login_or_ui', 'O WhatsApp Web não está pronto. Se a janela mostrar QR Code, vincule sua conta pelo celular. Se já estiver conectado, a interface pode ter mudado; nenhum rascunho foi alterado.') from None
        if search.count() != 1:
            raise DraftError('ambiguous_search', 'Não foi encontrado um único campo de busca; nenhum rascunho foi alterado.')
        _check(stop)
        search.fill(recipient, timeout=3000)
        candidates = page.locator('#pane-side span[title]').filter(has_text=re.compile(r'^\s*' + re.escape(recipient) + r'\s*$', re.IGNORECASE))
        try:
            candidates.first.wait_for(state='visible', timeout=5000)
        except Exception:
            raise DraftError('contact_not_found', 'Contato não encontrado pelo nome exato. Informe o nome completo como aparece no WhatsApp.') from None
        if candidates.count() != 1 or (candidates.first.get_attribute('title') or '').strip().casefold() != recipient.casefold():
            raise DraftError('ambiguous_contact', 'Mais de um resultado ou nome diferente. Informe um nome de contato único; nenhum rascunho foi alterado.')
        _check(stop)
        candidates.first.click(timeout=3000)
        until = time.monotonic() + 3
        while not _header_matches(page, recipient):
            _check(stop)
            if time.monotonic() >= until:
                raise DraftError('chat_not_verified', 'O cabeçalho da conversa não confirmou o contato escolhido. Nenhum texto foi digitado.')
            stop.wait(.1)
    composer = page.locator('#main footer [contenteditable="true"][role="textbox"]')
    try:
        composer.first.wait_for(state='visible', timeout=3000)
    except Exception:
        raise DraftError('composer_missing', 'O campo de mensagem não foi encontrado; nenhum rascunho foi alterado.') from None
    if composer.count() != 1:
        raise DraftError('ambiguous_composer', 'O campo de mensagem não é único; nenhum rascunho foi alterado.')
    _check(stop)
    if not _header_matches(page, recipient):
        raise DraftError('chat_changed', 'A conversa mudou antes da edição. Operação interrompida.')
    existing = composer.inner_text(timeout=2000).strip()
    expected = '' if action == 'clear' else text
    if action != 'read':
        if action == 'write' and existing and existing != expected.strip() and not replace_existing:
            raise DraftError('existing_draft', 'Já existe um rascunho diferente nesse contato. Peça explicitamente para substituí-lo ou limpá-lo.')
        if existing != expected.strip():
            _check(stop)
            # fill updates contenteditable text. No Enter key or send-button click.
            composer.fill(expected, timeout=3000)
    actual = composer.inner_text(timeout=2000).strip()
    if not _header_matches(page, recipient):
        raise DraftError('chat_changed', 'A conversa mudou durante a operação; confira o rascunho manualmente. Nenhum comando de envio foi executado.')
    if action != 'read' and actual != expected.strip():
        raise DraftError('readback_mismatch', 'A leitura do campo não confirmou o texto solicitado. Confira o rascunho; nenhum comando de envio foi executado.')
    _check(stop)
    return actual


def _loop():
    global _active
    driver = context = page = None
    while True:
        payload, stop, future = _JOBS.get()
        _active = stop
        try:
            _check(stop)
            if driver is None:
                try:
                    from playwright.sync_api import sync_playwright
                    driver = sync_playwright().start()
                except Exception:
                    raise DraftError('browser_dependency', 'Instale a dependência com python -m pip install playwright. O navegador precisa funcionar na sua sessão de desktop.') from None
            if context is None:
                profile = data_dir() / 'whatsapp-web-profile'
                for channel in ('chrome', 'msedge', None):
                    _check(stop)
                    try:
                        options = {'headless': False, 'timeout': 7000}
                        if channel:
                            options['channel'] = channel
                        context = driver.chromium.launch_persistent_context(str(profile), **options)
                        break
                    except Exception:
                        continue
                if context is None:
                    raise DraftError('browser_unavailable', 'Não foi possível abrir Chrome/Edge. Feche outra instância do Jarvis que use esse perfil. Alternativamente, instale o Chromium com python -m playwright install chromium.')
            if page is None or page.is_closed():
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(3000)
                page.goto('https://web.whatsapp.com/', wait_until='domcontentloaded', timeout=20000)
            if not page.url.startswith('https://web.whatsapp.com/'):
                page.goto('https://web.whatsapp.com/', wait_until='domcontentloaded', timeout=20000)
            _check(stop)
            actual = edit_draft(page, **payload, stop=stop)
            future.set_result((True, 'verified', actual))
        except DraftError as error:
            future.set_result((False, error.code, str(error)))
        except Exception:
            future.set_result((False, 'browser_error', 'A automação do navegador falhou. Confira a janela do WhatsApp Web; não foi possível confirmar o rascunho. Nenhum comando de envio é implementado neste fluxo.'))
            try:
                if page is None or page.is_closed():
                    context = page = None
            except Exception:
                context = page = None
        finally:
            with _WORKER_LOCK:
                if _active is stop:
                    _active = None


def run(recipient, action, text='', replace_existing=False):
    global _worker, _active
    stop = threading.Event()
    future = Future()
    with _WORKER_LOCK:
        _active = stop
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, daemon=True, name='whatsapp-draft-browser')
            _worker.start()
    _JOBS.put((dict(recipient=recipient, action=action, text=text, replace_existing=replace_existing), stop, future))
    try:
        return future.result(timeout=35)
    except FutureTimeout:
        stop.set()
        return False, 'timeout', 'O tempo de edição terminou. A interrupção foi solicitada; confira o rascunho na janela aberta. Não foi possível confirmar a operação e nenhum comando de envio é implementado.'

"""Visible WhatsApp Web: drafts, reading chats, and sending AFTER the user's OK.

The draft editor never presses Enter. Sending exists only as its own operation
(`send`), and the callers reach it only after the user approved that exact text
for that exact contact (a confirmation on screen, or the Send button of the
WhatsApp screen in the Jarvis interface). Reading the unread list uses the chat
list only, so nothing is marked as read until a conversation is opened.
"""
from concurrent.futures import Future, TimeoutError as FutureTimeout
import os
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


def _norm(text):
    """Nome sem emoji, pontuação e caixa: o WhatsApp desenha emoji como imagem,
    então o texto visível de "KHOTZ VIP ⚔️" é só "KHOTZ VIP"."""
    return ' '.join(re.sub(r'[^\w\s]', ' ', (text or '').casefold()).split())


def _header_matches(page, recipient):
    headers = page.locator('#main header [title]')
    if any(item.is_visible() and (item.get_attribute('title') or '').strip().casefold() == recipient.casefold()
           for item in headers.all()):
        return True
    # Layout novo do WhatsApp: o nome no cabeçalho pode vir sem o atributo title.
    try:
        header = page.locator('#main header')
        if header.count():
            linhas = [l for l in (header.first.inner_text(timeout=1000) or '').splitlines() if l.strip()]
            return bool(linhas) and _norm(linhas[0]) == _norm(recipient)
    except Exception:
        pass
    return False


_SEARCH_BOXES = ('#side [contenteditable="true"][role="textbox"]', '#side input[role="textbox"]',
                 '#side input[type="text"]', 'input[aria-label*="esquis"]', 'input[aria-label*="Search"]',
                 'div[contenteditable="true"][aria-label*="esquis"]', 'div[contenteditable="true"][aria-label*="Search"]')


def _search_box(page):
    for sel in _SEARCH_BOXES:
        try:
            box = page.locator(sel)
            if box.count() == 1 and box.first.is_visible() is True:
                return box
        except Exception:
            continue
    return None


def _exact_titles(page, recipient):
    """As entradas da lista de conversas cujo nome é exatamente `recipient`."""
    try:
        alvo = _norm(recipient)
        return [t for t in page.locator('#pane-side span[title]').all()
                if _norm(t.get_attribute('title')) == alvo]
    except Exception:
        return []


def _wait_header(page, recipient, stop):
    until = time.monotonic() + 4
    while not _header_matches(page, recipient):
        _check(stop)
        if time.monotonic() >= until:
            raise DraftError('chat_not_verified', 'O cabeçalho da conversa não confirmou o contato escolhido. Nenhum texto foi digitado.')
        stop.wait(.1)


def _open_chat(page, recipient, stop):
    """Opens the conversation whose name is exactly `recipient` and checks it."""
    _check(stop)
    if not page.url.startswith('https://web.whatsapp.com/'):
        raise DraftError('wrong_site', 'A janela não está no WhatsApp Web oficial; operação cancelada.')
    if _header_matches(page, recipient):
        return
    # 1) Está na lista de conversas? Clica direto, sem depender da busca.
    direto = _exact_titles(page, recipient)
    if len(direto) == 1:
        _check(stop)
        direto[0].click(timeout=3000)
        _wait_header(page, recipient, stop)
        return
    # 2) Senão, procura pelo campo de busca (o layout dele muda com frequência).
    search = _search_box(page)
    if search is None:
        search = page.locator('#side [contenteditable="true"][role="textbox"]')
        try:
            search.first.wait_for(state='visible', timeout=5000)
        except Exception:
            raise DraftError('login_or_ui', 'Não consegui abrir essa conversa no WhatsApp. Confira se o nome está igual ao da lista de conversas do Jarvis; se a tela do WhatsApp pedir QR Code, conecte pelo celular. Nenhum texto foi digitado.') from None
        if search.count() != 1:
            raise DraftError('ambiguous_search', 'Não foi encontrado um único campo de busca; nenhum rascunho foi alterado.')
    _check(stop)
    search.fill(recipient, timeout=3000)
    stop.wait(.8)
    achados = _exact_titles(page, recipient)
    if len(achados) == 1:
        achados[0].click(timeout=3000)
        _wait_header(page, recipient, stop)
        return
    candidates = page.locator('#pane-side span[title]').filter(has_text=re.compile(r'^\s*' + re.escape(recipient) + r'\s*$', re.IGNORECASE))
    try:
        candidates.first.wait_for(state='visible', timeout=5000)
    except Exception:
        raise DraftError('contact_not_found', 'Contato não encontrado pelo nome exato. Informe o nome completo como aparece no WhatsApp.') from None
    if candidates.count() != 1 or (candidates.first.get_attribute('title') or '').strip().casefold() != recipient.casefold():
        raise DraftError('ambiguous_contact', 'Mais de um resultado ou nome diferente. Informe um nome de contato único; nenhum rascunho foi alterado.')
    _check(stop)
    candidates.first.click(timeout=3000)
    _wait_header(page, recipient, stop)


def edit_draft(page, recipient, action, text, replace_existing, stop):
    """All selectors are scoped to chat navigation or the message composer."""
    _open_chat(page, recipient, stop)
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


# ── reading ─────────────────────────────────────────────────────────────────
_UNREAD_BADGE = ('span[aria-label*="não lida"], span[aria-label*="nao lida"], '
                 'span[aria-label*="unread"], span[aria-label*="no leído"]')
_META = re.compile(r'^\[(?P<hora>[^,\]]+),\s*(?P<data>[^\]]+)\]\s*(?P<autor>.*?):\s*$')


def parse_meta(meta):
    """'[10:32, 27/10/2026] João: ' -> {'hora': '10:32', 'data': '27/10/2026', 'autor': 'João'}."""
    m = _META.match((meta or '').strip() + ' ')
    if not m:
        m = _META.match((meta or '').strip())
    return {k: v.strip() for k, v in m.groupdict().items()} if m else {'hora': '', 'data': '', 'autor': ''}


_QR = ('[data-ref] canvas, canvas[aria-label*="QR"], canvas[aria-label*="qr"], '
       'canvas[aria-label*="Scan"], canvas[aria-label*="scan"], canvas[aria-label*="scane"]')


def _visible(locator):
    try:
        return locator.count() > 0 and locator.first.is_visible()
    except Exception:
        return False


def login_state(page, stop, wait=40):
    """'ok' (conversas na tela), 'qr' (pedindo para escanear) ou 'carregando'."""
    until = time.monotonic() + wait
    while True:
        _check(stop)
        if _visible(page.locator('#pane-side')):
            return 'ok'
        if _visible(page.locator(_QR)):
            return 'qr'
        if time.monotonic() >= until:
            return 'carregando'
        stop.wait(.5)


def qr_png(page):
    """O QR Code como PNG, para mostrar dentro do Jarvis."""
    for sel in ('[data-ref]', _QR):
        loc = page.locator(sel)
        if _visible(loc):
            return loc.first.screenshot(timeout=5000)
    return page.screenshot(timeout=5000)


def login_info(page, stop, wait=15):
    import base64
    state = login_state(page, stop, wait)
    out = {'estado': state, 'imagem': ''}
    if state == 'qr':
        out['imagem'] = base64.b64encode(qr_png(page)).decode('ascii')
    return out


def _require_login(page, stop):
    state = login_state(page, stop, 40)
    if state == 'qr':
        raise DraftError('login_qr', 'O WhatsApp Web está pedindo o QR Code. Abra a tela WhatsApp do Jarvis e escaneie pelo celular (WhatsApp > Aparelhos conectados).')
    if state != 'ok':
        raise DraftError('login_or_ui', 'O WhatsApp Web não terminou de carregar em 40 segundos. Tente de novo; se continuar, reinicie o Jarvis.')


def _chat_rows(page):
    for sel in ('#pane-side [role="listitem"]', '#pane-side [role="row"]', '#pane-side [role="gridcell"]'):
        rows = page.locator(sel)
        if rows.count():
            return rows
    return page.locator('#pane-side [role="listitem"]')


def recent_chats(page, stop, limit=25):
    """[{'contato', 'nao_lidas', 'previa'}] das conversas visíveis na lista; abre nenhuma."""
    _check(stop)
    if not page.url.startswith('https://web.whatsapp.com/'):
        raise DraftError('wrong_site', 'A janela não está no WhatsApp Web oficial.')
    _require_login(page, stop)
    out, vistos = [], set()
    for row in _chat_rows(page).all()[:80]:
        _check(stop)
        titles = [t.get_attribute('title') or '' for t in row.locator('span[title]').all()]
        titles = [t.strip() for t in titles if t.strip()]
        if not titles or titles[0] in vistos:
            continue
        vistos.add(titles[0])
        badge = row.locator(_UNREAD_BADGE)
        unread = 0
        if badge.count():
            label = badge.first.get_attribute('aria-label') or badge.first.inner_text()
            digits = re.search(r'\d+', label or '')
            unread = int(digits.group()) if digits else 1
        out.append({'contato': titles[0], 'nao_lidas': unread,
                    'previa': titles[-1] if len(titles) > 1 else ''})
        if len(out) >= limit:
            break
    return out


def unread_chats(page, stop, limit=25):
    """Só as conversas com mensagens não lidas (pela lista; abre nenhuma)."""
    return [c for c in recent_chats(page, stop, 80) if c['nao_lidas']][:limit]


def show_window(page, show=True):
    """Traz a janela do WhatsApp Web para a tela ou a minimiza de novo."""
    try:
        cdp = page.context.new_cdp_session(page)
        wid = cdp.send('Browser.getWindowForTarget')['windowId']
        cdp.send('Browser.setWindowBounds', {'windowId': wid, 'bounds': {'windowState': 'normal' if show else 'minimized'}})
        if show:
            page.bring_to_front()
        return True
    except Exception:
        return False


_AUDIO_BOTAO = ('[data-icon="audio-play"], [data-icon="ptt-play"], [data-icon="audio-download"], '
                'button[aria-label*="voz" i], button[aria-label*="voice" i], button[aria-label*="áudio" i]')
_HORA_RE = re.compile(r'\b(\d{1,2}:\d{2})\b')


def read_chat(page, recipient, stop, count=15):
    """The last `count` messages of a conversation (opening it marks it read).

    Mensagens de voz vêm como {'tipo': 'audio', 'id': ...}: o texto delas sai
    por transcrição (op 'audio'), que só roda quando pedida."""
    _require_login(page, stop)
    _open_chat(page, recipient, stop)
    linhas = [r for r in page.locator('#main [data-id]').all()
              if re.match(r'^(true|false)_', r.get_attribute('data-id') or '')][-count:]
    if not linhas:      # layout sem data-id: só os textos, como antes
        out = []
        for item in page.locator('#main [data-pre-plain-text]').all()[-count:]:
            meta = parse_meta(item.get_attribute('data-pre-plain-text'))
            mine = item.locator('xpath=ancestor::div[contains(@class, "message-out")]').count() > 0
            out.append({**meta, 'de': 'eu' if mine else 'contato', 'texto': (item.inner_text() or '').strip(), 'tipo': 'texto'})
        return out
    out = []
    for linha in linhas:
        _check(stop)
        mid = linha.get_attribute('data-id') or ''
        de = 'eu' if mid.startswith('true_') else 'contato'
        texto_el = linha.locator('[data-pre-plain-text]')
        if texto_el.count():
            item = texto_el.first
            meta = parse_meta(item.get_attribute('data-pre-plain-text'))
            out.append({**meta, 'de': de, 'texto': (item.inner_text() or '').strip(), 'tipo': 'texto', 'id': mid})
            continue
        bruto = (linha.inner_text() or '').strip()
        # Cada pedaço de texto separado: duração ("0:07") e hora ("09:11").
        horas = linha.evaluate(
            "el => [...el.querySelectorAll('*')].filter(e => !e.childElementCount)"
            ".map(e => (e.textContent || '').trim()).filter(t => /^\\d{1,2}:\\d{2}$/.test(t))") or _HORA_RE.findall(bruto)
        if linha.locator(_AUDIO_BOTAO).count():
            duracao = horas[0] if len(horas) > 1 else ''
            out.append({'hora': horas[-1] if horas else '', 'data': '', 'autor': '', 'de': de, 'tipo': 'audio',
                        'id': mid, 'duracao': duracao, 'texto': '[mensagem de voz]'})
        elif bruto:
            out.append({'hora': horas[-1] if horas else '', 'data': '', 'autor': '', 'de': de, 'tipo': 'midia',
                        'id': mid, 'texto': '[foto, vídeo ou arquivo]'})
    return out


_CAPTURAR_AUDIO = """async (id) => {
  if (!window.__jarvisPlay) {
    window.__jarvisPlay = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      if (window.__jarvisCaptura) { const f = window.__jarvisCaptura; window.__jarvisCaptura = null; f(this); return Promise.resolve(); }
      return window.__jarvisPlay.apply(this, arguments);
    };
  }
  const linha = [...document.querySelectorAll('#main [data-id]')].find((e) => e.getAttribute('data-id') === id);
  if (!linha) return { erro: 'nao_achou' };
  linha.scrollIntoView({ block: 'center' });
  const icone = linha.querySelector('[data-icon="audio-play"], [data-icon="ptt-play"], [data-icon="audio-download"]');
  const botao = (icone && icone.closest('button, [role="button"]')) ||
    linha.querySelector('button[aria-label*="voz" i], button[aria-label*="voice" i], button[aria-label*="áudio" i]');
  if (!botao) return { erro: 'sem_botao' };
  const src = await new Promise((ok) => {
    const limite = setTimeout(() => { window.__jarvisCaptura = null; ok(''); }, 20000);
    window.__jarvisCaptura = (el) => {
      const ver = (n) => { const s = el.currentSrc || el.src; if (s) { clearTimeout(limite); ok(s); } else if (n > 0) setTimeout(() => ver(n - 1), 100); };
      ver(100);
    };
    botao.click();
  });
  const pausa = linha.querySelector('[data-icon="audio-pause"], [data-icon="ptt-pause"]');
  if (pausa) (pausa.closest('button, [role="button"]') || pausa).click();
  if (!src) return { erro: 'sem_audio' };
  const resp = await fetch(src);
  const buf = new Uint8Array(await resp.arrayBuffer());
  let bin = '';
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return { b64: btoa(bin), tipo: resp.headers.get('content-type') || '' };
}"""


def baixar_audio(page, recipient, msg_id, stop):
    """Os bytes de uma mensagem de voz: aperta o play (sem tocar) e pega o
    arquivo que o WhatsApp Web prepara para o player."""
    import base64
    _require_login(page, stop)
    _open_chat(page, recipient, stop)
    r = page.evaluate(_CAPTURAR_AUDIO, msg_id)
    if r.get('erro') == 'nao_achou':
        raise DraftError('audio_missing', 'Essa mensagem de voz não está mais entre as últimas da conversa.')
    if r.get('erro'):
        raise DraftError('audio_failed', 'Não consegui baixar a mensagem de voz pelo WhatsApp Web '
                         f'({r["erro"]}). Ouça pelo celular.')
    return {'audio': base64.b64decode(r['b64']), 'tipo': r.get('tipo', '')}


def send_message(page, recipient, text, stop):
    """Writes `text` in that exact conversation, presses Enter and checks it left.

    Only ever called after the user approved this text for this contact."""
    text = (text or '').strip()
    if not text or len(text) > 4000:
        raise DraftError('bad_text', 'A mensagem precisa ter de 1 a 4000 caracteres.')
    _open_chat(page, recipient, stop)
    composer = page.locator('#main footer [contenteditable="true"][role="textbox"]')
    try:
        composer.first.wait_for(state='visible', timeout=3000)
    except Exception:
        raise DraftError('composer_missing', 'O campo de mensagem não foi encontrado; nada foi enviado.') from None
    if composer.count() != 1:
        raise DraftError('ambiguous_composer', 'O campo de mensagem não é único; nada foi enviado.')
    existing = composer.inner_text(timeout=2000).strip()
    if existing and existing != text:
        raise DraftError('existing_draft', 'Já existe outro rascunho nessa conversa; nada foi enviado. Limpe o rascunho e tente de novo.')
    composer.fill(text, timeout=3000)
    if composer.inner_text(timeout=2000).strip() != text:
        raise DraftError('readback_mismatch', 'O texto no campo não confirmou; nada foi enviado.')
    _check(stop)
    if not _header_matches(page, recipient):
        raise DraftError('chat_changed', 'A conversa mudou antes do envio; nada foi enviado.')
    composer.press('Enter', timeout=3000)
    until = time.monotonic() + 5
    while composer.inner_text(timeout=2000).strip():
        if time.monotonic() >= until:
            raise DraftError('not_sent', 'O WhatsApp não confirmou o envio; confira a conversa.')
        stop.wait(.1)
    return text


def _do(page, payload, stop):
    op = payload.get('op', 'draft')
    if op == 'login':
        return login_info(page, stop, payload.get('wait', 15))
    if op == 'recent':
        return recent_chats(page, stop, payload.get('limit', 25))
    if op == 'window':
        return show_window(page, payload.get('show', True))
    if op == 'unread':
        return unread_chats(page, stop, payload.get('limit', 25))
    if op == 'read':
        return read_chat(page, payload['recipient'], stop, payload.get('count', 15))
    if op == 'audio':
        return baixar_audio(page, payload['recipient'], payload['id'], stop)
    if op == 'send':
        return send_message(page, payload['recipient'], payload['text'], stop)
    return edit_draft(page, payload['recipient'], payload['action'], payload.get('text', ''),
                      payload.get('replace_existing', False), stop)


def _janela_visivel():
    """JARVIS_WHATSAPP_VISIVEL=1 mostra a janela do navegador (só para conferir algo)."""
    return bool(os.environ.get('JARVIS_WHATSAPP_VISIVEL'))


def _launch(driver, stop):
    """O WhatsApp Web roda escondido, sem janela nem aba: o QR Code e as conversas
    aparecem só dentro do Jarvis. O login fica guardado neste perfil."""
    profile = data_dir() / 'whatsapp-web-profile'
    for channel in ('chrome', 'msedge', None):
        _check(stop)
        try:
            options = {'headless': not _janela_visivel(), 'timeout': 15000, 'locale': 'pt-BR',
                       'viewport': {'width': 1280, 'height': 900}}
            if channel:
                options['channel'] = channel
            return driver.chromium.launch_persistent_context(str(profile), **options)
        except Exception:
            continue
    raise DraftError('browser_unavailable', 'Não foi possível abrir Chrome/Edge. Feche outra instância do Jarvis que use esse perfil. Alternativamente, instale o Chromium com python -m playwright install chromium.')


def _disfarcar(page):
    """O navegador escondido se apresenta como "HeadlessChrome", e o WhatsApp Web
    recusa esse nome ("atualize o navegador"). Usa o nome normal do mesmo Chrome."""
    if _janela_visivel():
        return
    try:
        cdp = page.context.new_cdp_session(page)
        agente = cdp.send('Browser.getVersion').get('userAgent', '')
        if 'Headless' in agente:
            cdp.send('Network.setUserAgentOverride', {'userAgent': agente.replace('HeadlessChrome', 'Chrome'),
                                                      'acceptLanguage': 'pt-BR,pt;q=0.9', 'platform': 'Windows'})
    except Exception:
        pass


def _loop():
    global _active
    driver = context = page = None
    while True:
        payload, stop, future = _JOBS.get()
        _active = stop
        if payload.get('op') == 'fechar':
            # Fecha o navegador escondido e o Playwright (ao desligar o Jarvis).
            for fechar in (lambda: context and context.close(), lambda: driver and driver.stop()):
                try:
                    fechar()
                except Exception:
                    pass
            driver = context = page = None
            future.set_result((True, 'closed', True))
            _active = None
            continue
        try:
            _check(stop)
            if driver is None:
                try:
                    from playwright.sync_api import sync_playwright
                    driver = sync_playwright().start()
                except Exception:
                    raise DraftError('browser_dependency', 'Instale a dependência com python -m pip install playwright. O navegador precisa funcionar na sua sessão de desktop.') from None
            if context is None:
                context = _launch(driver, stop)
            for attempt in (1, 2):
                started = False
                try:
                    if page is None or page.is_closed():
                        page = context.pages[0] if context.pages else context.new_page()
                        page.set_default_timeout(3000)
                        _disfarcar(page)
                        page.goto('https://web.whatsapp.com/', wait_until='domcontentloaded', timeout=20000)
                    if not page.url.startswith('https://web.whatsapp.com/'):
                        page.goto('https://web.whatsapp.com/', wait_until='domcontentloaded', timeout=20000)
                    _check(stop)
                    started = True
                    actual = _do(page, payload, stop)
                    break
                except DraftError:
                    raise
                except Exception:
                    # A janela do WhatsApp Web foi fechada: abre de novo (o login
                    # fica guardado no perfil, sem QR Code) e tenta uma vez mais.
                    # Nunca repetir um envio que já começou: duplicaria a mensagem.
                    if attempt == 2 or (started and payload.get('op') == 'send'):
                        raise
                    try:
                        context.close()
                    except Exception:
                        pass
                    context = page = None
                    context = _launch(driver, stop)
            future.set_result((True, 'verified', actual))
        except DraftError as error:
            future.set_result((False, error.code, str(error)))
        except Exception as error:
            motivo = f'{type(error).__name__}: {str(error).splitlines()[0][:200] if str(error) else ""}'
            print(f'[WhatsApp Web] {payload.get("op")}: {motivo}')
            future.set_result((False, 'browser_error', f'A automação do WhatsApp Web falhou ({motivo}).' + (' Veja na conversa se a mensagem saiu antes de tentar de novo.' if payload.get('op') == 'send' else '')))
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
    return run_op(dict(op='draft', recipient=recipient, action=action, text=text,
                       replace_existing=replace_existing))


def fechar(timeout=8):
    """Fecha o WhatsApp Web escondido, se estiver aberto (sem abrir só para fechar)."""
    if _worker is None or not _worker.is_alive():
        return True
    return run_op({'op': 'fechar'}, timeout=timeout)[0]


def run_op(payload, timeout=35):
    """(ok, code, result) for one browser operation, in the browser thread."""
    global _worker, _active
    stop = threading.Event()
    future = Future()
    with _WORKER_LOCK:
        _active = stop
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, daemon=True, name='whatsapp-draft-browser')
            _worker.start()
    _JOBS.put((payload, stop, future))
    try:
        return future.result(timeout=timeout)
    except FutureTimeout:
        stop.set()
        return False, 'timeout', 'O tempo de edição terminou. A interrupção foi solicitada; confira o rascunho na janela aberta. Não foi possível confirmar a operação e nenhum comando de envio é implementado.'

"""Synthetic browser smoke check; never contacts a real WhatsApp account."""
import shutil
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import threading
from playwright.sync_api import sync_playwright
from core.whatsapp_web import edit_draft

html = '''<html><body>
<div id="side"><div contenteditable="true" role="textbox"></div></div>
<div id="pane-side"><span title="Vitor" id="vitor">Vitor</span></div>
<div id="main"><header><span title="Ana" id="chat">Ana</span></header>
<footer><div contenteditable="true" role="textbox" id="composer"></div>
<button id="send">Enviar</button></footer></div>
<script>window.sent=0;window.enter=0;
document.querySelector('#vitor').onclick=()=>{const e=document.querySelector('#chat');e.title='Vitor';e.textContent='Vitor';};
document.querySelector('#send').onclick=()=>window.sent++;
document.addEventListener('keydown',e=>{if(e.key==='Enter'){window.enter++;window.sent++;}});
</script></body></html>'''
executable = next((shutil.which(x) for x in ('chromium','chromium-browser','google-chrome','microsoft-edge') if shutil.which(x)), None)
with sync_playwright() as engine:
    browser = engine.chromium.launch(executable_path=executable,headless=True)
    page = browser.new_page()
    page.route('**/*',lambda route: route.fulfill(status=200,content_type='text/html',body=html))
    page.goto('https://web.whatsapp.com/')
    text = 'Estou testando agora. Ação e café.'
    assert edit_draft(page,'Vitor','write',text,False,threading.Event()) == text
    assert edit_draft(page,'Vitor','read','',False,threading.Event()) == text
    assert edit_draft(page,'Vitor','clear','',False,threading.Event()) == ''
    assert page.evaluate('window.sent') == 0
    assert page.evaluate('window.enter') == 0
    browser.close()
print('PASS: navegador real, página simulada; contato, escrita com acentos, leitura e limpeza; zero Enter e zero envios.')

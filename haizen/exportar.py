"""Exporta a página de indicadores de uma conta (Meta ou Google) em PDF ou JPG.

Abre a própria tela da central num navegador sem janela, no modo de exportação (sem menu, botões
e chat, com cabeçalho de relatório), no período pedido, e salva como PDF (páginas A4) ou como
uma imagem JPG da página inteira. Assim o arquivo sai igual ao que você vê na tela.
"""
from __future__ import annotations

import json
import re
import threading

_UMA_POR_VEZ = threading.Lock()
TIPOS = {"pdf": "application/pdf", "jpg": "image/jpeg"}


def nome_arquivo(cliente: str, plataforma: str, ini: str, fim: str, formato: str) -> str:
    base = re.sub(r"[^\w\- ]+", "", cliente or "conta", flags=re.UNICODE).strip() or "conta"
    rede = "Meta Ads" if plataforma == "meta" else "Google Ads"
    return f"Indicadores {rede} - {base} - {ini} a {fim}.{formato}"


def indicadores(plataforma: str, conta_id: str, ini: str, fim: str, formato: str, porta: int) -> bytes:
    if formato not in TIPOS:
        raise ValueError("formato deve ser pdf ou jpg")
    from playwright.sync_api import sync_playwright
    from haizen.producao.ferramentas import _navegador
    tela = "trafego" if plataforma == "meta" else "googleads"
    url = f"http://127.0.0.1:{porta}/?exportar=1#/{tela}/{conta_id}"
    periodo = json.dumps({"id": "livre", "ini": ini, "fim": fim})
    with _UMA_POR_VEZ, sync_playwright() as p:
        b = _navegador(p)
        try:
            ctx = b.new_context(viewport={"width": 1240, "height": 1400}, device_scale_factor=2 if formato == "jpg" else 1, bypass_csp=True,
                                locale="pt-BR")
            ctx.add_init_script(f"try {{ localStorage.setItem('central.periodo.anuncios', {json.dumps(periodo)}); }} catch (e) {{}}")
            page = ctx.new_page()
            page.goto(url, wait_until="load")
            page.wait_for_function("() => window.__indicadoresProntos === true || !!window.__indicadoresErro", timeout=180_000)
            erro = page.evaluate("() => window.__indicadoresErro || ''")
            if erro:
                raise ValueError(erro)
            page.evaluate("async () => { if (document.fonts) await document.fonts.ready; }")
            page.wait_for_timeout(300)
            if formato == "pdf":
                page.emulate_media(media="print")
                return page.pdf(format="A4", print_background=True, scale=0.78,
                                margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
            return page.screenshot(type="jpeg", quality=90, full_page=True)
        finally:
            b.close()

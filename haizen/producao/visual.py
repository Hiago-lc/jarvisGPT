"""Ferramentas de direção de arte: ver referências de verdade, montar pranchas,
recortar produto do fundo, tratar foto e conferir vídeo numa folha de contato.

    python visual.py referencias "anuncio clinica estetica" --pasta fontes/referencias [--video]
    python visual.py ver-site URL saida.jpg [--largura 1440 --altura 2200]
    python visual.py baixar saida_dir URL [URL...]
    python visual.py prancha saida.jpg img1 img2 ... [--colunas 3 --legendas]
    python visual.py contato video.mp4 saida.jpg [--quadros 12]
    python visual.py recortar foto.jpg saida.png
    python visual.py tratar foto.jpg saida.jpg --estilo vivo|quente|frio|pb|cinema|suave [--granulado 0.04]

Tudo roda neste PC. As referências são só para estudo interno (prancha de
direção): nunca copie uma peça de outra marca.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
if str(_AQUI.parents[1]) not in sys.path:
    sys.path.insert(0, str(_AQUI.parents[1]))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")

# Onde procurar: o que é anúncio de verdade (Biblioteca de Anúncios da Meta) e o
# que é direção de arte premiada (Behance, Dribbble, Pinterest).
FONTES = {
    "meta_ads": "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=BR&media_type=image"
                "&search_type=keyword_unordered&q={q}",
    "behance": "https://www.behance.net/search/projects?search={q}",
    "dribbble": "https://dribbble.com/search/{q_traco}",
    "pinterest": "https://br.pinterest.com/search/pins/?q={q}",
}
FONTES_VIDEO = {
    "meta_ads": "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=BR&media_type=video"
                "&search_type=keyword_unordered&q={q}",
    "behance": "https://www.behance.net/search/projects?search={q}%20motion%20design",
    "dribbble": "https://dribbble.com/search/{q_traco}-motion",
    "pinterest": "https://br.pinterest.com/search/pins/?q={q}%20motion%20design",
}

# Esconde avisos de cookie, janelas de login e barras fixas antes da captura.
_LIMPAR_CSS = """
[role="dialog"], [aria-modal="true"], #onetrust-banner-sdk, .cookie, [class*="cookie"], [id*="cookie"],
[class*="Cookie"], [data-test-id="signup"], [data-test-id="fullPageSignupModal"], .signup-overlay,
[class*="login-modal"], [class*="LoginModal"], [class*="Modal__overlay"], div[data-testid="unauth-modal"]
{ display: none !important; }
html, body { overflow: auto !important; }
"""


def _navegador(p):
    for canal in ("chrome", "msedge", None):
        try:
            return p.chromium.launch(**({"channel": canal} if canal else {}))
        except Exception:  # noqa: BLE001
            continue
    sys.exit("ERRO: nenhum navegador disponível. Rode: python -m playwright install chromium")


def _reduzir(origem: Path, destino: Path, largura: int = 1400, qualidade: int = 82) -> Path:
    """JPG mais leve para abrir com Read (o que importa é ver a composição)."""
    from PIL import Image
    im = Image.open(origem).convert("RGB")
    if im.width > largura:
        im = im.resize((largura, int(im.height * largura / im.width)), Image.LANCZOS)
    if im.height > 2600:
        im = im.crop((0, 0, im.width, 2600))
    im.save(destino, "JPEG", quality=qualidade, optimize=True)
    return destino


def _capturar(page, url: str, saida: Path, altura: int, rolar: int = 3) -> list[str]:
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3500)
    page.add_style_tag(content=_LIMPAR_CSS)
    for _ in range(rolar):                                  # carrega as imagens "preguiçosas"
        page.mouse.wheel(0, 1400)
        page.wait_for_timeout(900)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(800)
    page.add_style_tag(content=_LIMPAR_CSS)
    bruto = saida.with_suffix(".bruto.png")
    page.screenshot(path=str(bruto), full_page=True)
    _reduzir(bruto, saida)
    bruto.unlink(missing_ok=True)
    # As imagens grandes da página, para baixar em alta as que valerem a pena.
    return page.evaluate("""() => [...document.images]
        .filter(i => (i.naturalWidth || i.width) >= 300 && (i.naturalHeight || i.height) >= 300)
        .map(i => i.currentSrc || i.src).filter(s => s && s.startsWith('http')).slice(0, 30)""")


def referencias(a) -> None:
    """Abre as melhores fontes de referência para o tema e captura o que aparece."""
    from playwright.sync_api import sync_playwright
    pasta = Path(a.pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    tema = " ".join(a.tema).strip()
    q = urllib.parse.quote(tema)
    q_traco = urllib.parse.quote(re.sub(r"\s+", "-", tema.lower()))
    fontes = FONTES_VIDEO if a.video else FONTES
    escolhidas = [f for f in (a.fontes.split(",") if a.fontes else fontes) if f in fontes]
    resultado = {"tema": tema, "capturas": [], "imagens": {}, "falhas": {}}
    with sync_playwright() as p:
        b = _navegador(p)
        ctx = b.new_context(viewport={"width": 1440, "height": 1800}, user_agent=UA, locale="pt-BR")
        for nome in escolhidas:
            url = fontes[nome].format(q=q, q_traco=q_traco)
            saida = pasta / f"ref-{nome}-{_slug(tema)}.jpg"
            page = ctx.new_page()
            try:
                imgs = _capturar(page, url, saida, 1800)
                resultado["capturas"].append({"fonte": nome, "url": url, "arquivo": str(saida)})
                resultado["imagens"][nome] = imgs
            except Exception as e:  # noqa: BLE001
                resultado["falhas"][nome] = str(e)[:200]
            finally:
                page.close()
        b.close()
    (pasta / f"referencias-{_slug(tema)}.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1),
                                                           encoding="utf-8")
    for c in resultado["capturas"]:
        print(f"OK {c['fonte']}: {c['arquivo']}")
    for n, e in resultado["falhas"].items():
        print(f"FALHOU {n}: {e}")
    print(f"Links das imagens (para baixar em alta com 'baixar'): {pasta / ('referencias-' + _slug(tema) + '.json')}")


def ver_site(a) -> None:
    from playwright.sync_api import sync_playwright
    saida = Path(a.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = _navegador(p)
        ctx = b.new_context(viewport={"width": a.largura, "height": a.altura}, user_agent=UA, locale="pt-BR")
        page = ctx.new_page()
        imgs = _capturar(page, a.url, saida, a.altura, rolar=2)
        b.close()
    print(f"OK {saida}")
    if imgs:
        print("Imagens grandes na página:\n" + "\n".join(imgs[:15]))


def baixar(a) -> None:
    pasta = Path(a.pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    for url in a.urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": url})
            with urllib.request.urlopen(req, timeout=40) as r:
                dados = r.read(25_000_000)
                tipo = r.headers.get("Content-Type", "")
            ext = ".png" if "png" in tipo else ".webp" if "webp" in tipo else ".jpg"
            destino = pasta / f"ref-{hashlib.md5(url.encode()).hexdigest()[:10]}{ext}"
            destino.write_bytes(dados)
            if ext == ".webp":
                from PIL import Image
                Image.open(destino).convert("RGB").save(destino.with_suffix(".jpg"), quality=90)
                destino.unlink()
                destino = destino.with_suffix(".jpg")
            print(f"OK {destino}")
        except Exception as e:  # noqa: BLE001
            print(f"FALHOU {url[:90]}: {e}")


def prancha(a) -> None:
    """Junta várias imagens numa prancha só (mais barato de ver e comparar)."""
    from PIL import Image, ImageDraw, ImageFont
    arquivos = [Path(x) for x in a.imagens if Path(x).is_file()]
    if not arquivos:
        sys.exit("ERRO: nenhuma imagem encontrada")
    col = max(1, min(a.colunas, len(arquivos)))
    larg_cel = max(200, a.largura // col)
    cels = []
    for f in arquivos:
        im = Image.open(f).convert("RGB")
        im.thumbnail((larg_cel - 16, int((larg_cel - 16) * 1.6)), Image.LANCZOS)
        cels.append((f, im))
    linhas = [cels[i:i + col] for i in range(0, len(cels), col)]
    alt_leg = 34 if a.legendas else 0
    alturas = [max(im.height for _, im in ln) + 16 + alt_leg for ln in linhas]
    tela = Image.new("RGB", (larg_cel * col, sum(alturas)), (24, 24, 27))
    d = ImageDraw.Draw(tela)
    try:
        fonte = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        fonte = ImageFont.load_default()
    y = 0
    for ln, h in zip(linhas, alturas):
        for i, (f, im) in enumerate(ln):
            x = i * larg_cel + (larg_cel - im.width) // 2
            tela.paste(im, (x, y + 8))
            if a.legendas:
                d.text((i * larg_cel + 10, y + 8 + im.height + 6), f.stem[:48], fill=(220, 220, 220), font=fonte)
        y += h
    saida = Path(a.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    tela.save(saida, "JPEG", quality=85)
    print(f"OK {saida} ({len(arquivos)} imagens)")


def contato(a) -> None:
    """Folha de contato do vídeo: N quadros em grade, com o tempo de cada um."""
    from PIL import Image, ImageDraw, ImageFont

    from haizen.producao.ferramentas import ffmpeg, _duracao
    video = Path(a.video)
    dur = _duracao(video) or 10.0
    n = max(4, min(30, a.quadros))
    with tempfile.TemporaryDirectory() as tmp:
        quadros = []
        for i in range(n):
            t = min(dur - 0.05, (i + 0.5) * dur / n)
            alvo = Path(tmp) / f"q{i:02d}.jpg"
            subprocess.run([ffmpeg(), "-nostdin", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
                            "-frames:v", "1", "-vf", "scale=360:-2", str(alvo)], stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=120)
            if alvo.is_file():
                quadros.append((t, Image.open(alvo).convert("RGB")))
        if not quadros:
            sys.exit("ERRO: não consegui extrair quadros do vídeo")
        col = 6 if n > 8 else 4
        w, h = quadros[0][1].size
        linhas = (len(quadros) + col - 1) // col
        tela = Image.new("RGB", (col * (w + 8) + 8, linhas * (h + 36) + 8), (20, 20, 22))
        d = ImageDraw.Draw(tela)
        try:
            fonte = ImageFont.truetype("arial.ttf", 20)
        except OSError:
            fonte = ImageFont.load_default()
        for i, (t, im) in enumerate(quadros):
            x, y = 8 + (i % col) * (w + 8), 8 + (i // col) * (h + 36)
            tela.paste(im, (x, y))
            d.text((x + 4, y + h + 6), f"{t:05.2f}s", fill=(230, 230, 230), font=fonte)
        saida = Path(a.saida)
        saida.parent.mkdir(parents=True, exist_ok=True)
        tela.save(saida, "JPEG", quality=85)
    print(f"OK {saida} ({len(quadros)} quadros de {dur:.1f}s)")


def _rembg():
    try:
        from rembg import new_session, remove
        return new_session, remove
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "rembg[cpu]"], stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=1800)
        import importlib
        importlib.invalidate_caches()
        try:
            from rembg import new_session, remove
            return new_session, remove
        except ImportError:
            sys.exit("ERRO: não consegui instalar o rembg (recorte de fundo). Rode: pip install \"rembg[cpu]\"")


def recortar(a) -> None:
    """Tira o fundo da foto (produto, pessoa) e devolve PNG transparente, sem bordas sobrando."""
    from PIL import Image
    new_session, remove = _rembg()
    im = Image.open(a.imagem).convert("RGBA")
    try:
        sessao = new_session(a.modelo)
    except Exception:  # noqa: BLE001
        sessao = new_session("u2net")
    out = remove(im, session=sessao, alpha_matting=a.refinar, post_process_mask=True)
    caixa = out.getbbox()
    if caixa:
        out = out.crop(caixa)
    saida = Path(a.saida).with_suffix(".png")
    saida.parent.mkdir(parents=True, exist_ok=True)
    out.save(saida)
    print(f"OK {saida} ({out.width}x{out.height}, fundo transparente)")


ESTILOS = {
    # contraste, saturação, brilho, (r, g, b) multiplicadores
    "vivo": (1.12, 1.18, 1.02, (1.0, 1.0, 1.0)),
    "quente": (1.08, 1.06, 1.03, (1.06, 1.0, 0.92)),
    "frio": (1.08, 1.0, 1.0, (0.94, 1.0, 1.07)),
    "pb": (1.18, 0.0, 1.0, (1.0, 1.0, 1.0)),
    "cinema": (1.15, 0.9, 0.97, (1.03, 0.99, 0.95)),
    "suave": (0.94, 0.92, 1.05, (1.02, 1.0, 0.99)),
}


def tratar(a) -> None:
    """Tratamento de cor coerente para uma série inteira (use o mesmo estilo em todas)."""
    from PIL import Image, ImageEnhance, ImageFilter
    c, s, b, (mr, mg, mb) = ESTILOS[a.estilo]
    im = Image.open(a.imagem).convert("RGB")
    im = ImageEnhance.Contrast(im).enhance(c)
    im = ImageEnhance.Color(im).enhance(s)
    im = ImageEnhance.Brightness(im).enhance(b)
    if (mr, mg, mb) != (1.0, 1.0, 1.0):
        r, g, bl = im.split()
        im = Image.merge("RGB", (r.point(lambda v: min(255, int(v * mr))), g.point(lambda v: min(255, int(v * mg))),
                                 bl.point(lambda v: min(255, int(v * mb)))))
    if a.estilo == "cinema":                     # sombras levemente azuladas, luzes quentes
        r, g, bl = im.split()
        bl = bl.point(lambda v: min(255, int(v + (18 * (1 - v / 255)))))
        im = Image.merge("RGB", (r, g, bl))
    im = im.filter(ImageFilter.UnsharpMask(radius=1.6, percent=int(a.nitidez * 100), threshold=3))
    if a.vinheta > 0:
        from PIL import ImageDraw
        w, h = im.size
        mascara = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mascara).ellipse((-w * 0.25, -h * 0.25, w * 1.25, h * 1.25), fill=255)
        mascara = mascara.filter(ImageFilter.GaussianBlur(min(w, h) * 0.18))
        escuro = ImageEnhance.Brightness(im).enhance(1 - a.vinheta)
        im = Image.composite(im, escuro, mascara)
    if a.granulado > 0:
        w, h = im.size
        ruido = Image.effect_noise((w, h), 64).convert("RGB")
        im = Image.blend(im, ruido, a.granulado)
    saida = Path(a.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    im.save(saida, quality=94) if saida.suffix.lower() in (".jpg", ".jpeg") else im.save(saida)
    print(f"OK {saida} (estilo {a.estilo})")


def _slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", t.lower())[:40].strip("-") or "ref"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("referencias"); s.add_argument("tema", nargs="+"); s.add_argument("--pasta", default="fontes/referencias")
    s.add_argument("--video", action="store_true"); s.add_argument("--fontes", default=""); s.set_defaults(f=referencias)
    s = sub.add_parser("ver-site"); s.add_argument("url"); s.add_argument("saida")
    s.add_argument("--largura", type=int, default=1440); s.add_argument("--altura", type=int, default=2200)
    s.set_defaults(f=ver_site)
    s = sub.add_parser("baixar"); s.add_argument("pasta"); s.add_argument("urls", nargs="+"); s.set_defaults(f=baixar)
    s = sub.add_parser("prancha"); s.add_argument("saida"); s.add_argument("imagens", nargs="+")
    s.add_argument("--colunas", type=int, default=3); s.add_argument("--largura", type=int, default=1500)
    s.add_argument("--legendas", action="store_true"); s.set_defaults(f=prancha)
    s = sub.add_parser("contato"); s.add_argument("video"); s.add_argument("saida")
    s.add_argument("--quadros", type=int, default=12); s.set_defaults(f=contato)
    s = sub.add_parser("recortar"); s.add_argument("imagem"); s.add_argument("saida")
    s.add_argument("--modelo", default="isnet-general-use"); s.add_argument("--refinar", action="store_true")
    s.set_defaults(f=recortar)
    s = sub.add_parser("tratar"); s.add_argument("imagem"); s.add_argument("saida")
    s.add_argument("--estilo", choices=sorted(ESTILOS), default="vivo"); s.add_argument("--nitidez", type=float, default=0.6)
    s.add_argument("--vinheta", type=float, default=0.0); s.add_argument("--granulado", type=float, default=0.0)
    s.set_defaults(f=tratar)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()

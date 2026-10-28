"""Ferramentas que os agentes da HAIZEN usam para produzir arquivos de verdade.

Uso (o agente chama pelo terminal, de dentro da pasta do trabalho):

    python ferramentas.py verificar
    python ferramentas.py inventario "G:/Meu Drive/CLIENTES/10 - KHOTZ"
    python ferramentas.py cores "logo.png"
    python ferramentas.py render peca.html peca.png --largura 1080 --altura 1440
    python ferramentas.py render proposta.html proposta.pdf --largura 1240 --altura 1754
    python ferramentas.py animar anima.html video.mp4 --largura 1080 --altura 1920 --segundos 8 [--musica m.mp3]
    python ferramentas.py video saida.mp4 --entradas a.png b.mp4 c.jpg --largura 1080 --altura 1920
                                [--dur-imagem 3] [--max-clipe 5] [--musica m.mp3]

Tudo roda neste PC: o navegador escondido (Playwright) desenha o HTML no tamanho
exato e o ffmpeg monta os vídeos. Nada é enviado para fora.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IMAGENS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic", ".svg"}
VIDEOS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
AUDIOS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
FONTES = {".ttf", ".otf", ".woff", ".woff2"}
FONTES_TRABALHO = {".psd", ".ai", ".prproj", ".aep", ".fig", ".xd", ".cdr", ".indd"}
DOCS = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md", ".pptx"}
IGNORAR = {"desktop.ini", "thumbs.db", ".ds_store"}


# ── utilidades ───────────────────────────────────────────────────────────────
def ffmpeg() -> str:
    """O ffmpeg do PATH ou o do pacote imageio-ffmpeg."""
    achado = shutil.which("ffmpeg")
    if achado:
        return achado
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        pass
    sys.exit("ERRO: o ffmpeg não está instalado. Rode instalar-producao.bat (na pasta do Jarvis) "
             "ou: python -m pip install imageio-ffmpeg")


def _duracao(caminho: Path) -> float | None:
    try:
        r = subprocess.run([ffmpeg(), "-i", str(caminho)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
    except Exception:  # noqa: BLE001
        return None
    import re
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def _navegador(p):
    """Chrome ou Edge instalados; senão o Chromium do Playwright."""
    for canal in ("chrome", "msedge", None):
        try:
            return p.chromium.launch(**({"channel": canal} if canal else {}))
        except Exception:  # noqa: BLE001
            continue
    sys.exit("ERRO: nenhum navegador disponível. Rode: python -m playwright install chromium")


def _abrir(page, html: Path, largura: int, altura: int):
    page.set_viewport_size({"width": largura, "height": altura})
    page.goto(html.resolve().as_uri(), wait_until="load")
    page.evaluate("async () => { if (document.fonts) await document.fonts.ready; }")
    # Imagens grandes do Drive podem demorar: espera todas carregarem.
    page.evaluate("""async () => { await Promise.all([...document.images].map(i => i.complete ? 0 :
        new Promise(r => { i.onload = i.onerror = r; }))); }""")


# ── comandos ─────────────────────────────────────────────────────────────────
def verificar(_a) -> None:
    linhas = [f"python: {sys.executable}"]
    try:
        from PIL import Image  # noqa: F401
        linhas.append("pillow: ok")
    except Exception as e:  # noqa: BLE001
        linhas.append(f"pillow: FALTA ({e})")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = _navegador(p)
            linhas.append(f"navegador: ok ({b.version})")
            b.close()
    except SystemExit as e:
        linhas.append(str(e))
    except Exception as e:  # noqa: BLE001
        linhas.append(f"playwright: FALTA ({e})")
    achado = shutil.which("ffmpeg")
    if not achado:
        try:
            import imageio_ffmpeg
            achado = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001
            achado = ""
    linhas.append(f"ffmpeg: {achado or 'FALTA (rode instalar-producao.bat)'}")
    print("\n".join(linhas))


def inventario(a) -> None:
    """O material do cliente: logos, fontes, fotos, vídeos, arquivos de trabalho."""
    raiz = Path(a.pasta)
    if not raiz.is_dir():
        sys.exit(f"ERRO: pasta não encontrada: {raiz}")
    grupos: dict[str, list] = {"logos": [], "fontes": [], "imagens": [], "videos": [], "audios": [],
                               "arquivos_de_trabalho": [], "documentos": []}
    arquivos = []
    for dirpath, dirnames, filenames in os.walk(raiz):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and "JARVIS - para revisar" not in d]
        for nome in filenames:
            if nome.lower() in IGNORAR or nome.startswith("~$"):
                continue
            arquivos.append(Path(dirpath) / nome)
    arquivos.sort(key=lambda f: f.stat().st_mtime if f.exists() else 0, reverse=True)
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        Image = None
    for f in arquivos:
        ext = f.suffix.lower()
        rel = str(f.relative_to(raiz)).replace("\\", "/")
        info = {"arquivo": rel}
        if ext in IMAGENS and Image is not None and ext not in (".svg", ".heic"):
            try:
                with Image.open(f) as im:
                    info["tamanho"] = f"{im.width}x{im.height}"
                    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                        alfa = im.convert("RGBA").getchannel("A")
                        if alfa.getextrema()[0] < 250:
                            info["fundo_transparente"] = True
            except Exception:  # noqa: BLE001
                pass
        if ("logo" in rel.lower() or "id visual" in rel.lower() or "identidade" in rel.lower()) and (ext in IMAGENS or ext in {".ai", ".pdf", ".eps"}):
            grupos["logos"].append(info)
        elif ext in FONTES:
            grupos["fontes"].append(info)
        elif ext in IMAGENS:
            grupos["imagens"].append(info)
        elif ext in VIDEOS:
            grupos["videos"].append(info)
        elif ext in AUDIOS:
            grupos["audios"].append(info)
        elif ext in FONTES_TRABALHO:
            grupos["arquivos_de_trabalho"].append(info)
        elif ext in DOCS:
            grupos["documentos"].append(info)
    limite = a.max
    saida = {"pasta": str(raiz), "total_arquivos": len(arquivos)}
    for k, v in grupos.items():
        saida[k] = v[:limite]
        if len(v) > limite:
            saida[k + "_omitidos"] = len(v) - limite
    print(json.dumps(saida, ensure_ascii=False, indent=1))


def cores(a) -> None:
    """As cores principais de uma imagem (logo, peça antiga), em hexadecimal."""
    from PIL import Image
    with Image.open(a.imagem) as im:
        im = im.convert("RGBA")
        im.thumbnail((300, 300))
        dados = im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()
        pixels = [p[:3] for p in dados if p[3] > 200]
    if not pixels:
        sys.exit("ERRO: a imagem não tem pixels visíveis")
    base = Image.new("RGB", (len(pixels), 1))
    base.putdata(pixels)
    pal = base.quantize(colors=max(2, a.n + 2), method=Image.Quantize.MEDIANCUT)
    contagem = sorted(pal.getcolors(), reverse=True)
    paleta = pal.getpalette()
    total = sum(c for c, _ in contagem)
    for c, i in contagem[:a.n]:
        r, g, b = paleta[i * 3:i * 3 + 3]
        print(f"#{r:02X}{g:02X}{b:02X}  {100 * c / total:4.1f}%")


def render(a) -> None:
    """HTML -> PNG/JPG (tamanho exato) ou PDF."""
    from playwright.sync_api import sync_playwright
    html, saida = Path(a.html), Path(a.saida)
    if not html.is_file():
        sys.exit(f"ERRO: não achei {html}")
    saida.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = _navegador(p)
        ctx = b.new_context(device_scale_factor=a.escala)
        page = ctx.new_page()
        _abrir(page, html, a.largura, a.altura)
        # A imagem final é o estado de chegada: animações de entrada terminadas.
        page.evaluate("() => document.getAnimations().forEach(x => { try { x.finish(); } catch (e) {} })")
        if saida.suffix.lower() == ".pdf":
            page.emulate_media(media="print")
            page.pdf(path=str(saida), width=f"{a.largura}px", height=f"{a.altura}px",
                     print_background=True, margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        else:
            tipo = "jpeg" if saida.suffix.lower() in (".jpg", ".jpeg") else "png"
            extra = {"quality": 92} if tipo == "jpeg" else {}
            page.screenshot(path=str(saida), type=tipo, full_page=a.pagina_inteira,
                            clip=None if a.pagina_inteira else {"x": 0, "y": 0, "width": a.largura, "height": a.altura},
                            **extra)
        b.close()
    print(f"OK {saida} ({a.largura}x{a.altura}{' x' + str(a.escala) if a.escala != 1 else ''})")


def animar(a) -> None:
    """HTML com animações CSS -> MP4, quadro a quadro (sem perder quadros)."""
    from playwright.sync_api import sync_playwright
    html, saida = Path(a.html), Path(a.saida)
    total = int(a.segundos * a.fps)
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        b = _navegador(p)
        page = b.new_page()
        _abrir(page, html, a.largura, a.altura)
        for i in range(total):
            t = i * 1000 / a.fps
            page.evaluate("""(t) => { document.getAnimations().forEach(x => { x.pause(); x.currentTime = t; });
                                      if (window.quadro) window.quadro(t); }""", t)
            page.screenshot(path=f"{tmp}/q{i:05d}.png", clip={"x": 0, "y": 0, "width": a.largura, "height": a.altura})
        b.close()
        cmd = [ffmpeg(), "-y", "-loglevel", "error", "-framerate", str(a.fps), "-i", f"{tmp}/q%05d.png"]
        if a.musica:
            cmd += ["-i", a.musica, "-af", f"afade=t=out:st={max(0, a.segundos - 1.5)}:d=1.5", "-shortest"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20",
                "-movflags", "+faststart", str(saida)]
        subprocess.run(cmd, check=True)
    print(f"OK {saida} ({a.largura}x{a.altura}, {a.segundos}s)")


def video(a) -> None:
    """Junta imagens e clipes num vídeo no formato pedido (corta para preencher)."""
    saida = Path(a.saida)
    ff = ffmpeg()
    escala = (f"scale={a.largura}:{a.altura}:force_original_aspect_ratio=increase,"
              f"crop={a.largura}:{a.altura},setsar=1,fps=30,format=yuv420p")
    with tempfile.TemporaryDirectory() as tmp:
        partes = []
        for i, entrada in enumerate(a.entradas):
            f = Path(entrada)
            if not f.is_file():
                sys.exit(f"ERRO: não achei {f}")
            parte = Path(tmp) / f"p{i:03d}.mp4"
            if f.suffix.lower() in VIDEOS:
                cmd = [ff, "-y", "-loglevel", "error", "-i", str(f), "-t", str(a.max_clipe), "-an", "-vf", escala]
            else:
                zoom = (f"scale={a.largura * 2}:{a.altura * 2}:force_original_aspect_ratio=increase,"
                        f"crop={a.largura * 2}:{a.altura * 2},zoompan=z='min(zoom+0.0008,1.08)':d={int(a.dur_imagem * 30)}"
                        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={a.largura}x{a.altura}:fps=30,setsar=1,format=yuv420p")
                cmd = [ff, "-y", "-loglevel", "error", "-loop", "1", "-i", str(f), "-t", str(a.dur_imagem),
                       "-vf", zoom if a.zoom else escala]
            subprocess.run(cmd + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(parte)], check=True)
            partes.append(parte)
        lista = Path(tmp) / "lista.txt"
        lista.write_text("".join(f"file '{p.as_posix()}'\n" for p in partes), encoding="utf-8")
        cmd = [ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lista)]
        if a.musica:
            dur = sum(_duracao(p) or 0 for p in partes)
            cmd += ["-i", a.musica, "-af", f"afade=t=out:st={max(0, dur - 1.5)}:d=1.5", "-shortest",
                    "-c:a", "aac", "-b:a", "160k"]
        cmd += ["-c:v", "copy" if not a.musica else "libx264", "-movflags", "+faststart", str(saida)]
        if a.musica:
            cmd[cmd.index("libx264") + 1:cmd.index("libx264") + 1] = ["-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
        subprocess.run(cmd, check=True)
    print(f"OK {saida} ({a.largura}x{a.altura}, {len(partes)} partes)")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="ferramentas", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verificar").set_defaults(f=verificar)
    s = sub.add_parser("inventario"); s.add_argument("pasta"); s.add_argument("--max", type=int, default=60); s.set_defaults(f=inventario)
    s = sub.add_parser("cores"); s.add_argument("imagem"); s.add_argument("-n", type=int, default=6); s.set_defaults(f=cores)
    s = sub.add_parser("render"); s.add_argument("html"); s.add_argument("saida")
    s.add_argument("--largura", type=int, required=True); s.add_argument("--altura", type=int, required=True)
    s.add_argument("--escala", type=float, default=1); s.add_argument("--pagina-inteira", action="store_true"); s.set_defaults(f=render)
    s = sub.add_parser("animar"); s.add_argument("html"); s.add_argument("saida")
    s.add_argument("--largura", type=int, required=True); s.add_argument("--altura", type=int, required=True)
    s.add_argument("--segundos", type=float, default=8); s.add_argument("--fps", type=int, default=30)
    s.add_argument("--musica", default=""); s.set_defaults(f=animar)
    s = sub.add_parser("video"); s.add_argument("saida"); s.add_argument("--entradas", nargs="+", required=True)
    s.add_argument("--largura", type=int, default=1080); s.add_argument("--altura", type=int, default=1920)
    s.add_argument("--dur-imagem", type=float, default=3); s.add_argument("--max-clipe", type=float, default=5)
    s.add_argument("--zoom", action="store_true", help="aproximação lenta nas imagens")
    s.add_argument("--musica", default=""); s.set_defaults(f=video)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()

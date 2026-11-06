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
def _ffmpeg_achado() -> str:
    achado = shutil.which("ffmpeg")
    if achado:
        return achado
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return ""


def ffmpeg() -> str:
    """O ffmpeg do PATH ou o do pacote imageio-ffmpeg. Se faltar, instala o pacote
    (está no requirements do Jarvis) uma vez e tenta de novo."""
    achado = _ffmpeg_achado()
    if achado:
        return achado
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "imageio-ffmpeg"], stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=600)
        import importlib
        importlib.invalidate_caches()
    except Exception:  # noqa: BLE001
        pass
    achado = _ffmpeg_achado()
    if achado:
        return achado
    sys.exit("ERRO: o ffmpeg não está instalado. Rode instalar-producao.bat (na pasta do Jarvis) "
             "ou: python -m pip install imageio-ffmpeg")


def _duracao(caminho: Path) -> float | None:
    try:
        r = subprocess.run([ffmpeg(), "-i", str(caminho)], capture_output=True, text=True, stdin=subprocess.DEVNULL,
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


# Controla o relógio de tudo o que anima na página: CSS/Web Animations, GSAP
# (window.timeline, ou a linha do tempo global), Lottie e uma função window.quadro(ms).
_TEMPO_JS = """(t) => {
  document.getAnimations().forEach(x => { try { x.pause(); x.currentTime = t; } catch (e) {} });
  const s = t / 1000;
  const tl = window.timeline || window.tl;
  if (tl && tl.seek) { tl.pause(); tl.seek(s, false); }
  else if (window.gsap && window.gsap.globalTimeline) {
    const g = window.gsap.globalTimeline;
    if (window.__inicioGsap === undefined) { window.__inicioGsap = g.time(); g.pause(); }
    g.time(window.__inicioGsap + s, false);
  }
  if (window.lottie && window.lottie.goToAndStop) { try { window.lottie.goToAndStop(t, false); } catch (e) {} }
  if (window.quadro) window.quadro(t);
}"""


def _ass_tempo(s: float) -> str:
    h, r = divmod(max(0.0, s), 3600)
    m, r = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{r:05.2f}"


def _srt_tempo(s: float) -> str:
    ms = int(round(max(0.0, s) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    seg, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{seg:02d},{ms:03d}"


def _cor_ass(hexa: str) -> str:
    h = (hexa or "#FFD400").lstrip("#")
    if len(h) != 6:
        h = "FFD400"
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def palavras_do_audio(video: Path) -> list[dict]:
    """[{texto, ini, fim}] de cada palavra falada (Whisper local)."""
    from faster_whisper import WhisperModel
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        subprocess.run([ffmpeg(), "-nostdin", "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1",
                        "-ar", "16000", str(wav)], check=True, stdin=subprocess.DEVNULL)
        nome = os.environ.get("JARVIS_WHISPER_LEGENDAS", "small")
        modelo = WhisperModel(nome, device="cpu", compute_type="int8")
        segs, _ = modelo.transcribe(str(wav), language="pt", word_timestamps=True, vad_filter=True,
                                    condition_on_previous_text=False)
        return [{"texto": w.word.strip(), "ini": float(w.start), "fim": float(w.end)}
                for sg in segs for w in (sg.words or []) if w.word.strip()]


def montar_legendas(palavras: list[dict], por_linha: int, largura: int, altura: int, cor: str,
                    fonte: str, margem_baixo: int) -> tuple[str, str]:
    """(ASS com a palavra falada em destaque, SRT simples)."""
    grupos = [palavras[i:i + por_linha] for i in range(0, len(palavras), por_linha)]
    tamanho = max(36, int(largura * 0.068))
    ass = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {largura}", f"PlayResY: {altura}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Leg,{fonte},{tamanho},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(3, tamanho // 12)},2,2,{int(largura * 0.08)},{int(largura * 0.08)},{margem_baixo},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    srt = []
    destaque = _cor_ass(cor)
    for n, g in enumerate(grupos, 1):
        fim_grupo = g[-1]["fim"]
        prox = grupos[n][0]["ini"] if n < len(grupos) else fim_grupo + 0.4
        fim_grupo = min(max(fim_grupo, g[-1]["ini"] + 0.25), prox)
        for i, w in enumerate(g):
            ini = w["ini"]
            fim = g[i + 1]["ini"] if i + 1 < len(g) else fim_grupo
            if fim <= ini:
                continue
            texto = " ".join((f"{{\\c{destaque}}}{x['texto'].upper()}{{\\c&H00FFFFFF&}}" if j == i
                              else x["texto"].upper()) for j, x in enumerate(g))
            ass.append(f"Dialogue: 0,{_ass_tempo(ini)},{_ass_tempo(fim)},Leg,,0,0,0,,{texto}")
        srt += [str(n), f"{_srt_tempo(g[0]['ini'])} --> {_srt_tempo(fim_grupo)}", " ".join(x["texto"] for x in g), ""]
    return "\n".join(ass) + "\n", "\n".join(srt)


def legendar(a) -> None:
    """Legenda queimada no vídeo, palavra a palavra, a partir da fala (Whisper local).
    Grava também o .srt ao lado da saída."""
    video, saida = Path(a.video), Path(a.saida)
    palavras = palavras_do_audio(video)
    if not palavras:
        sys.exit("ERRO: não encontrei fala no vídeo para legendar")
    largura, altura = _dimensoes(video)
    margem = a.margem if a.margem is not None else int(altura * 0.2)
    ass, srt = montar_legendas(palavras, a.por_linha, largura, altura, a.cor, a.fonte, margem)
    saida.with_suffix(".srt").write_text(srt, encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "leg.ass").write_text(ass, encoding="utf-8")
        r = subprocess.run([ffmpeg(), "-nostdin", "-y", "-loglevel", "error", "-i", str(video.resolve()), "-vf",
                            "ass=leg.ass", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                            "-c:a", "copy", "-movflags", "+faststart", str(saida.resolve())], cwd=tmp,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace")
        if r.returncode != 0:
            sys.exit(f"ERRO: o ffmpeg não queimou a legenda ({(r.stderr or '')[-300:]}). O .srt ficou em "
                     f"{saida.with_suffix('.srt')}; um ffmpeg completo (winget install Gyan.FFmpeg) resolve.")
    print(f"OK {saida} ({len(palavras)} palavras legendadas; .srt ao lado)")


def _dimensoes(video: Path) -> tuple[int, int]:
    r = subprocess.run([ffmpeg(), "-nostdin", "-i", str(video)], capture_output=True, text=True, errors="replace",
                       stdin=subprocess.DEVNULL)
    import re as _re
    m = _re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", r.stderr or "")
    return (int(m.group(1)), int(m.group(2))) if m else (1080, 1920)


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
            page.evaluate(_TEMPO_JS, t)
            page.screenshot(path=f"{tmp}/q{i:05d}.png", clip={"x": 0, "y": 0, "width": a.largura, "height": a.altura})
        b.close()
        cmd = [ffmpeg(), "-y", "-loglevel", "error", "-framerate", str(a.fps), "-i", f"{tmp}/q%05d.png"]
        if a.musica:
            cmd += ["-i", a.musica, "-af", f"afade=t=out:st={max(0, a.segundos - 1.5)}:d=1.5", "-shortest"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20",
                "-movflags", "+faststart", str(saida)]
        subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)
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
            subprocess.run(cmd + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(parte)], check=True,
                           stdin=subprocess.DEVNULL)
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
        subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)
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
    s = sub.add_parser("legendar"); s.add_argument("video"); s.add_argument("saida")
    s.add_argument("--por-linha", type=int, default=3); s.add_argument("--cor", default="#FFD400")
    s.add_argument("--fonte", default="Montserrat ExtraBold"); s.add_argument("--margem", type=int, default=None)
    s.set_defaults(f=legendar)
    s = sub.add_parser("video"); s.add_argument("saida"); s.add_argument("--entradas", nargs="+", required=True)
    s.add_argument("--largura", type=int, default=1080); s.add_argument("--altura", type=int, default=1920)
    s.add_argument("--dur-imagem", type=float, default=3); s.add_argument("--max-clipe", type=float, default=5)
    s.add_argument("--zoom", action="store_true", help="aproximação lenta nas imagens")
    s.add_argument("--musica", default=""); s.set_defaults(f=video)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()

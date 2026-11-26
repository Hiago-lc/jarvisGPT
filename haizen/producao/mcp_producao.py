"""Ferramentas de produção dos agentes como servidor MCP (sem depender do terminal).

No Windows o Claude Code pode rodar comandos pelo PowerShell em vez do Bash, e
as permissões "Bash(python:*)" deixam de valer: o agente ficava sem conseguir
renderizar nada. Aqui as mesmas ferramentas (render, animar, vídeo, quadros,
ffmpeg, scripts python) viram ferramentas próprias, liberadas por nome.

Tudo o que é GRAVADO precisa ficar dentro da pasta do trabalho
(HAIZEN_TRABALHO_PASTA). Ler pode ser de qualquer pasta liberada (cliente).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

try:                                      # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP  # noqa: E402
except ImportError:                       # mcp 1.x
    from mcp.server.fastmcp import FastMCP  # noqa: E402

FERRAMENTAS = Path(__file__).resolve().parent / "ferramentas.py"
mcp = FastMCP("producao", instructions=(
    "Ferramentas de produção da HAIZEN: ver o material do cliente, renderizar HTML em PNG/JPG/PDF, animar HTML "
    "em MP4, montar vídeos, extrair quadros para conferir, rodar ffmpeg e scripts python. Tudo o que for "
    "gravado fica na pasta do trabalho."))


def _pasta() -> Path:
    p = os.environ.get("HAIZEN_TRABALHO_PASTA", "").strip()
    if not p:
        raise RuntimeError("pasta do trabalho não definida")
    return Path(p).resolve()


def _dentro(caminho: str, gravar: bool = True) -> Path:
    """Caminhos relativos são da pasta do trabalho; para gravar, precisa estar dentro dela."""
    p = Path(caminho)
    p = (p if p.is_absolute() else _pasta() / p).resolve()
    if gravar and _pasta() != p and _pasta() not in p.parents:
        raise ValueError(f"só dá para gravar dentro da pasta do trabalho ({_pasta()}), não em {p}")
    return p


def _rodar(args: list[str], timeout: int = 1800) -> str:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    # stdin fechado: o ffmpeg lê o teclado e, num servidor MCP, o "teclado" é o canal
    # de conversa com o Claude — ele travava e derrubava a conexão.
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(_pasta()),
                       stdin=subprocess.DEVNULL,
                       env=env, timeout=timeout)
    saida = ((r.stdout or "") + ("\n" + r.stderr if r.stderr else "")).strip()
    if r.returncode != 0:
        raise RuntimeError(f"falhou (código {r.returncode}): {saida[-3000:]}")
    return saida[-6000:] or "ok"


def _exe_ffmpeg() -> str:
    """O ffmpeg sem derrubar o servidor (a ferramenta original encerra o processo se faltar)."""
    from haizen.producao.ferramentas import ffmpeg as achar
    try:
        return achar()
    except SystemExit as e:
        raise RuntimeError(str(e) or "ffmpeg não encontrado: rode instalar-producao.bat") from None


def _ferr(*args: str, timeout: int = 1800) -> str:
    return _rodar([sys.executable, str(FERRAMENTAS), *args], timeout)


@mcp.tool()
def verificar() -> str:
    """Confere se o ffmpeg e o navegador de renderização estão prontos."""
    return _ferr("verificar", timeout=120)


@mcp.tool()
def inventario(pasta: str, maximo: int = 60) -> str:
    """Lista o material de uma pasta (logos, fotos, vídeos com duração, fontes, peças antigas)."""
    return _ferr("inventario", str(_dentro(pasta, gravar=False)), "--max", str(maximo), timeout=300)


@mcp.tool()
def cores(imagem: str, quantidade: int = 6) -> str:
    """As cores principais de um logo ou peça (hex)."""
    return _ferr("cores", str(_dentro(imagem, gravar=False)), "-n", str(quantidade), timeout=120)


@mcp.tool()
def render(html: str, saida: str, largura: int, altura: int, pagina_inteira: bool = False, escala: float = 1) -> str:
    """HTML → PNG/JPG no tamanho exato (ou PDF se saida terminar em .pdf). As animações CSS
    terminam antes da captura."""
    args = ["render", str(_dentro(html, gravar=False)), str(_dentro(saida)), "--largura", str(largura),
            "--altura", str(altura), "--escala", str(escala)]
    return _ferr(*(args + (["--pagina-inteira"] if pagina_inteira else [])), timeout=600)


@mcp.tool()
def animar(html: str, saida: str, largura: int = 1080, altura: int = 1920, segundos: float = 8, fps: int = 30,
           musica: str = "") -> str:
    """HTML com animações → MP4, quadro a quadro no tempo exato. Funciona com CSS @keyframes, GSAP (exponha
    `window.timeline = gsap.timeline()`), Lottie (lottie-web) e uma função `window.quadro(ms)`."""
    args = ["animar", str(_dentro(html, gravar=False)), str(_dentro(saida)), "--largura", str(largura),
            "--altura", str(altura), "--segundos", str(segundos), "--fps", str(fps)]
    if musica:
        args += ["--musica", str(_dentro(musica, gravar=False))]
    return _ferr(*args, timeout=1800)


VISUAL = Path(__file__).resolve().parent / "visual.py"
KIT = Path(__file__).resolve().parent / "kit"


def _vis(*args: str, timeout: int = 900) -> str:
    return _rodar([sys.executable, str(VISUAL), *args], timeout)


@mcp.tool()
def referencias(tema: str, video: bool = False, fontes: str = "") -> str:
    """PESQUISA VISUAL: abre a Biblioteca de Anúncios da Meta, Behance, Dribbble e Pinterest com o tema
    (ex.: "anuncio clinica estetica", "pacote viagem nordeste reels") e salva capturas em fontes/referencias/.
    Abra as capturas com Read para VER as referências. `video=True` busca motion design/anúncios em vídeo.
    `fontes` opcional: "meta_ads,behance,dribbble,pinterest". Gera também um .json com links das imagens."""
    return _vis("referencias", *tema.split(), "--pasta", str(_dentro("fontes/referencias")),
                *(["--video"] if video else []), *(["--fontes", fontes] if fontes else []), timeout=600)


@mcp.tool()
def ver_site(url: str, saida: str = "", largura: int = 1440, altura: int = 2200) -> str:
    """Captura uma página (projeto do Behance, site do cliente, concorrente) em JPG para você ver com Read."""
    saida = saida or f"fontes/referencias/site-{abs(hash(url)) % 10**8}.jpg"
    return _vis("ver-site", url, str(_dentro(saida)), "--largura", str(largura), "--altura", str(altura), timeout=300)


@mcp.tool()
def baixar_imagens(urls: list[str], pasta: str = "fontes/referencias") -> str:
    """Baixa em alta as imagens de referência escolhidas (links do .json da pesquisa ou do ver_site)."""
    return _vis("baixar", str(_dentro(pasta)), *urls[:15], timeout=300)


@mcp.tool()
def prancha(imagens: list[str], saida: str = "fontes/referencias/prancha.jpg", colunas: int = 3,
            legendas: bool = True) -> str:
    """Junta várias imagens numa prancha só: para montar o moodboard ou comparar suas versões lado a lado
    (mais barato do que abrir uma por uma)."""
    return _vis("prancha", str(_dentro(saida)), *[str(_dentro(i, gravar=False)) for i in imagens[:24]],
                "--colunas", str(colunas), *(["--legendas"] if legendas else []), timeout=300)


@mcp.tool()
def folha_de_contato(video: str, saida: str = "", quadros: int = 12) -> str:
    """Folha de contato do vídeo (N quadros em grade com o tempo): confira ritmo, legibilidade e transições
    de uma vez só."""
    v = _dentro(video, gravar=False)
    saida = saida or f"fontes/quadros/{v.stem}-contato.jpg"
    return _vis("contato", str(v), str(_dentro(saida)), "--quadros", str(quadros), timeout=600)


@mcp.tool()
def recortar(imagem: str, saida: str) -> str:
    """Tira o fundo da foto (produto, pessoa) e salva PNG transparente, pronto para compor com sombra.
    Na primeira vez instala o recorte automático (alguns minutos)."""
    return _vis("recortar", str(_dentro(imagem, gravar=False)), str(_dentro(saida)), timeout=2400)


@mcp.tool()
def tratar_foto(imagem: str, saida: str, estilo: str = "vivo", vinheta: float = 0.0, granulado: float = 0.0) -> str:
    """Tratamento de cor coerente para a série (use o MESMO estilo em todas as fotos): vivo, quente, frio, pb,
    cinema, suave. vinheta 0–0.4, granulado 0–0.08."""
    return _vis("tratar", str(_dentro(imagem, gravar=False)), str(_dentro(saida)), "--estilo", estilo,
                "--vinheta", str(vinheta), "--granulado", str(granulado), timeout=300)


@mcp.tool()
def kit_de_design() -> str:
    """Copia o kit da HAIZEN para fontes/kit/ (CSS com tipografia forte, texturas, selos, CTA, zonas seguras;
    motion.js para vídeo) e lista os modelos de layout com quando usar cada um. Copie o modelo escolhido para
    fontes/<peca>.html e reescreva com a marca do cliente — o modelo é ponto de partida, não a peça."""
    import shutil
    destino = _dentro("fontes/kit")
    destino.mkdir(parents=True, exist_ok=True)
    for f in ("haizen-kit.css", "motion.js"):
        shutil.copy2(KIT / f, destino / f)
    (destino / "modelos").mkdir(exist_ok=True)
    linhas = ["Kit em fontes/kit/ (haizen-kit.css, motion.js). Modelos em fontes/kit/modelos/ — copie para fontes/ "
              "(o link do CSS é kit/haizen-kit.css):"]
    for m in sorted((KIT / "modelos").glob("*.html")):
        shutil.copy2(m, destino / "modelos" / m.name)
        texto = m.read_text(encoding="utf-8")
        ini = texto.find("<!--")
        resumo = " ".join(texto[ini + 4:texto.find("-->", ini)].split()) if ini >= 0 else ""
        linhas.append(f"- {m.name}: {resumo[:330]}")
    return "\n".join(linhas)


@mcp.tool()
def legendar(video: str, saida: str, palavras_por_vez: int = 3, cor_destaque: str = "#FFD400",
             fonte: str = "Montserrat ExtraBold") -> str:
    """Legenda queimada a partir da fala do vídeo (Whisper local, palavra a palavra, a falada em destaque).
    Grava também o .srt. Use a cor de destaque da marca."""
    return _ferr("legendar", str(_dentro(video, gravar=False)), str(_dentro(saida)), "--por-linha",
                 str(palavras_por_vez), "--cor", cor_destaque, "--fonte", fonte, timeout=1800)


@mcp.tool()
def video(saida: str, entradas: list[str], largura: int = 1080, altura: int = 1920, dur_imagem: float = 3,
          max_clipe: float = 5, zoom: bool = False, musica: str = "") -> str:
    """Junta imagens e clipes num vídeo (cortes dos clipes, zoom lento nas fotos, música opcional)."""
    args = ["video", str(_dentro(saida)), "--entradas", *[str(_dentro(e, gravar=False)) for e in entradas],
            "--largura", str(largura), "--altura", str(altura), "--dur-imagem", str(dur_imagem),
            "--max-clipe", str(max_clipe)]
    if zoom:
        args.append("--zoom")
    if musica:
        args += ["--musica", str(_dentro(musica, gravar=False))]
    return _ferr(*args, timeout=1800)


@mcp.tool()
def quadros(video: str, segundos: list[float], pasta_saida: str = "fontes/quadros") -> list[str]:
    """Extrai quadros de um vídeo (JPG) nos segundos pedidos, para você abrir e conferir."""
    origem = _dentro(video, gravar=False)
    destino = _dentro(pasta_saida)
    destino.mkdir(parents=True, exist_ok=True)
    feitos = []
    for s in segundos[:20]:
        alvo = destino / f"{origem.stem}-{float(s):05.1f}s.jpg"
        _rodar([_exe_ffmpeg(), "-nostdin", "-y", "-loglevel", "error", "-ss", str(s), "-i", str(origem), "-frames:v", "1", "-q:v", "3",
                str(alvo)], timeout=120)
        feitos.append(str(alvo))
    return feitos


@mcp.tool()
def ffmpeg(argumentos: list[str]) -> str:
    """Roda o ffmpeg com estes argumentos (sem o "ffmpeg" no começo). O ÚLTIMO argumento é o
    arquivo de saída e precisa ficar na pasta do trabalho."""
    if not argumentos:
        raise ValueError("faltam os argumentos")
    args = list(argumentos)
    args[-1] = str(_dentro(args[-1]))
    return _rodar([_exe_ffmpeg(), "-hide_banner", "-nostdin", *args], timeout=1800)


@mcp.tool()
def python(script: str, argumentos: list[str] | None = None) -> str:
    """Roda um script python que VOCÊ gravou na pasta do trabalho (ex.: fontes/gerar_planilha.py),
    com a pasta do trabalho como diretório atual. Use para planilhas, ler .docx/.pdf, tratar imagens."""
    s = _dentro(script)
    if s.suffix.lower() != ".py" or not s.is_file():
        raise ValueError("o script precisa ser um .py dentro da pasta do trabalho")
    return _rodar([sys.executable, str(s), *[str(a) for a in (argumentos or [])]], timeout=1800)


if __name__ == "__main__":
    mcp.run()

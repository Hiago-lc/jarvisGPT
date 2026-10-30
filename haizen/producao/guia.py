"""O que a HAIZEN aprende com cada cliente, e as receitas de produção.

Guia da marca: um arquivo do Jarvis dentro de "JARVIS - para revisar" na pasta
do cliente. Cada ajuste pedido na revisão, cada observação ao aprovar e cada
preferência que o usuário contar ao Jarvis vira uma linha ali, e todo agente
lê o guia antes de produzir. O material do cliente não é tocado.

Receitas: o passo a passo de um tipo de peça que já deu certo (reels de
pacote de viagem, carrossel de oferta...), em haizen/producao/receitas/*.md.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

RECEITAS = Path(__file__).resolve().parent / "receitas"
NOME_GUIA = "_GUIA DA MARCA (Jarvis).md"


def arquivo_guia(marca: Path) -> Path:
    return Path(marca) / "JARVIS - para revisar" / NOME_GUIA


def ler_guia(marca: Path | None) -> str:
    if not marca:
        return ""
    try:
        return arquivo_guia(marca).read_text(encoding="utf-8")
    except OSError:
        return ""


def anotar(marca: Path, nota: str, origem: str = "") -> Path:
    """Acrescenta uma preferência ao guia (cria o arquivo na primeira vez)."""
    nota = " ".join((nota or "").split())
    if not nota:
        raise ValueError("nota vazia")
    arq = arquivo_guia(marca)
    arq.parent.mkdir(parents=True, exist_ok=True)
    if not arq.is_file():
        arq.write_text(
            f"# Guia da marca: {Path(marca).name}\n\n"
            "O que o dono da HAIZEN já aprovou, pediu para mudar ou contou sobre este cliente.\n"
            "Os agentes leem antes de produzir. Pode editar à vontade.\n\n## Preferências e ajustes\n",
            encoding="utf-8")
    texto = arq.read_text(encoding="utf-8")
    if nota.lower() in texto.lower():            # não repete a mesma lição
        return arq
    quando = dt.date.today().strftime("%d/%m/%Y")
    linha = f"- {quando}{f' ({origem})' if origem else ''}: {nota[:600]}\n"
    with arq.open("a", encoding="utf-8") as f:
        if not texto.endswith("\n"):
            f.write("\n")
        f.write(linha)
    return arq


def _cabecalho(texto: str) -> dict:
    m = re.match(r"---\s*\n(.*?)\n---\s*\n", texto, re.S)
    out = {}
    for linha in (m.group(1).splitlines() if m else []):
        if ":" in linha:
            k, v = linha.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def receitas() -> list[dict]:
    """[{nome, descricao, arquivo}] das receitas de produção."""
    out = []
    for arq in sorted(RECEITAS.glob("*.md")):
        cab = _cabecalho(arq.read_text(encoding="utf-8"))
        out.append({"nome": cab.get("nome", arq.stem), "descricao": cab.get("descricao", ""),
                    "arquivo": arq})
    return out

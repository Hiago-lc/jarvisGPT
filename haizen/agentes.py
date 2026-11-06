"""Definições dos agentes da HAIZEN.

Cada agente é um arquivo Markdown em `haizen/agentes/`, legível e editável por
uma pessoa, pelo Jarvis e pelo Claude (via MCP):

    ---
    nome: comercial
    titulo: Comercial
    descricao: Transforma um briefing em proposta comercial.
    executor: claude
    ---
    Você é o agente comercial da HAIZEN...

`executor` diz quem faz o trabalho:
    local   o modelo configurado no Jarvis (Ollama ou Groq). Custo zero.
    claude  o Claude Code instalado no PC, pela assinatura. Mais forte, mas
            consome o limite de uso do plano: reserve para o que vale a pena.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

EXECUTORES = ("local", "claude")
_NOME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,40}$")


def pasta_agentes() -> Path:
    override = os.environ.get("HAIZEN_AGENTES_DIR", "").strip()
    return Path(override) if override else Path(__file__).resolve().parent / "agentes"


@dataclass
class Agente:
    nome: str
    titulo: str
    descricao: str
    executor: str
    instrucoes: str
    extras: dict = field(default_factory=dict)

    def resumo(self) -> dict:
        return {"nome": self.nome, "titulo": self.titulo,
                "descricao": self.descricao, "executor": self.executor}


def validar_nome(nome: str) -> str:
    nome = (nome or "").strip().lower()
    if not _NOME_RE.match(nome):
        raise ValueError("nome do agente: use letras minúsculas, números, - ou _ "
                         "(2 a 41 caracteres, começando por letra)")
    return nome


def parse(texto: str, nome_arquivo: str = "") -> Agente:
    meta: dict[str, str] = {}
    corpo = texto
    if texto.startswith("---"):
        partes = texto.split("\n---", 1)
        if len(partes) == 2:
            for linha in partes[0].splitlines()[1:]:
                if ":" in linha:
                    k, v = linha.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
            corpo = partes[1].lstrip("-").lstrip("\n")
    nome = validar_nome(meta.get("nome") or Path(nome_arquivo).stem)
    executor = (meta.get("executor") or "local").lower()
    if executor not in EXECUTORES:
        raise ValueError(f"executor inválido em {nome}: use {' ou '.join(EXECUTORES)}")
    instrucoes = corpo.strip()
    if not instrucoes:
        raise ValueError(f"o agente {nome} não tem instruções")
    conhecidos = {"nome", "titulo", "descricao", "executor"}
    return Agente(nome=nome, titulo=meta.get("titulo") or nome.title(),
                  descricao=meta.get("descricao", ""), executor=executor,
                  instrucoes=instrucoes,
                  extras={k: v for k, v in meta.items() if k not in conhecidos})


def serializar(a: Agente) -> str:
    linhas = ["---", f"nome: {a.nome}", f"titulo: {a.titulo}",
              f"descricao: {a.descricao}", f"executor: {a.executor}"]
    linhas += [f"{k}: {v}" for k, v in a.extras.items()]
    return "\n".join(linhas) + "\n---\n" + a.instrucoes.strip() + "\n"


def listar() -> list[Agente]:
    out = []
    pasta = pasta_agentes()
    if not pasta.is_dir():
        return out
    for arq in sorted(pasta.glob("*.md")):
        try:
            out.append(parse(arq.read_text(encoding="utf-8"), arq.name))
        except (OSError, ValueError):
            continue        # um arquivo quebrado não derruba os outros
    return out


def carregar(nome: str) -> Agente:
    nome = validar_nome(nome)
    arq = pasta_agentes() / f"{nome}.md"
    if not arq.is_file():
        disponiveis = ", ".join(a.nome for a in listar()) or "nenhum"
        raise KeyError(f"não existe o agente '{nome}' (disponíveis: {disponiveis})")
    return parse(arq.read_text(encoding="utf-8"), arq.name)


def salvar(nome: str, titulo: str, descricao: str, executor: str,
           instrucoes: str) -> Agente:
    """Cria ou substitui um agente. Valida antes de gravar."""
    a = Agente(nome=validar_nome(nome), titulo=(titulo or nome).strip(),
               descricao=(descricao or "").strip().replace("\n", " "),
               executor=(executor or "local").strip().lower(),
               instrucoes=(instrucoes or "").strip())
    parse(serializar(a))                       # mesma validação da leitura
    pasta = pasta_agentes()
    pasta.mkdir(parents=True, exist_ok=True)
    tmp = pasta / f".{a.nome}.md.tmp"
    tmp.write_text(serializar(a), encoding="utf-8")
    os.replace(tmp, pasta / f"{a.nome}.md")
    return a

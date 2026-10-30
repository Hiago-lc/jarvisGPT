"""As operações da HAIZEN, iguais para a voz (plugin) e para o Claude (MCP)."""
from __future__ import annotations

import json
import re

from . import agentes, executor, store

_NOMES_STATUS = {
    "na_fila": "na fila", "executando": "em execução",
    "aguardando_aprovacao": "aguardando sua aprovação", "aprovado": "aprovado",
    "rejeitado": "rejeitado", "erro": "com erro", "esperando": "esperando as etapas anteriores",
}


def _cliente(cliente: str) -> tuple[dict | None, str]:
    if not (cliente or "").strip():
        return None, ""
    cli = store.buscar_cliente(cliente)
    if cli is None:
        cli = store.salvar_cliente(cliente.strip())
        return cli, f"Criei uma ficha nova para {cli['nome']}, ainda vazia. "
    return cli, ""


def _quem(a: agentes.Agente, forcado: str = "") -> tuple[str, str]:
    quem = (forcado or a.executor).lower()
    if quem not in agentes.EXECUTORES:
        raise ValueError(f"executor inválido: {quem}")
    if quem == "claude" and not executor.claude_disponivel() and executor.PERMITIR_LOCAL:
        return "local", "O Claude Code não está disponível; usei o modelo local. "
    return quem, ""


def _com_material(pedido: str, anexos: list | None) -> tuple[str, list[str]]:
    """Confere os anexos e anota no pedido o que foi enviado (os agentes leem)."""
    if not anexos:
        return pedido, []
    from haizen.central import anexos as _anexos
    lista = _anexos.varios(anexos)
    nomes = ", ".join(d["nome"] for d in lista)
    return (f"{pedido}\n\nMaterial enviado pelo usuário (na pasta \"{MATERIAL}\"): {nomes}",
            [d["id"] for d in lista])


MATERIAL = "00 - Material enviado"


def delegar(agente: str, pedido: str, cliente: str = "",
            executor_forcado: str = "", anexos: list | None = None) -> dict:
    """Coloca um trabalho na fila. Devolve o trabalho e um aviso, se houver."""
    a = agentes.carregar(agente)
    cli, aviso = _cliente(cliente)
    quem, aviso2 = _quem(a, executor_forcado)
    pedido, ids = _com_material(pedido, anexos)
    t = store.criar_trabalho(a.nome, pedido, quem, cli["id"] if cli else None, anexos=ids)
    return {"trabalho": t, "aviso": (aviso + aviso2).strip()}


# ── projetos: o gerente planeja, a equipe executa em etapas ─────────────────
def _equipe() -> list[agentes.Agente]:
    return [a for a in agentes.listar() if a.nome != "gerente"]


def criar_projeto(pedido: str, cliente: str = "", titulo: str = "", marca: str = "",
                  anexos: list | None = None) -> dict:
    """Abre o projeto e põe o gerente para montar o plano (a primeira etapa)."""
    pedido = (pedido or "").strip()
    if not pedido:
        raise ValueError("Diga o que o projeto precisa.")
    titulo = titulo or pedido[:80]
    pedido, ids = _com_material(pedido, anexos)
    cli, aviso = _cliente(cliente)
    pasta = store.pasta_da_marca(cli["id"] if cli else None, f"{pedido} {cliente}", marca)
    if not pasta:
        aviso += ("Não sei qual pasta de cliente usar: os arquivos vão para Documentos\\HAIZEN\\entregas. "
                  "Escolha a marca no projeto para os agentes usarem o material do cliente. ")
    proj = store.criar_projeto(titulo, pedido, cli["id"] if cli else None, pasta, ids)
    equipe = "\n".join(f"- {a.nome}: {a.titulo}. {a.descricao}" for a in _equipe())
    try:
        gerente = agentes.carregar("gerente")
        quem, aviso2 = _quem(gerente)
    except KeyError:
        gerente, quem, aviso2 = None, "local", ""
    if gerente is None:
        # Sem o arquivo do gerente: o plano padrão entra direto.
        _criar_etapas(proj, _plano_padrao(pedido), cli["id"] if cli else None, base=0)
        return {"projeto": proj, "aviso": aviso.strip()}
    store.criar_trabalho("gerente", f"{pedido}\n\n## Equipe disponível\n{equipe}", quem,
                         cli["id"] if cli else None, projeto_id=proj["id"], etapa=0,
                         titulo="Plano do projeto", aprovacao=False)
    return {"projeto": proj, "aviso": (aviso + aviso2).strip()}


def _ler_plano(texto: str) -> dict | None:
    """O JSON do gerente, validado; None se não der para usar."""
    bloco = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto or "", re.S)
    bruto = bloco.group(1) if bloco else None
    if bruto is None:
        ini, fim = (texto or "").find("{"), (texto or "").rfind("}")
        bruto = texto[ini:fim + 1] if 0 <= ini < fim else ""
    try:
        plano = json.loads(bruto)
    except ValueError:
        return None
    nomes = {a.nome for a in _equipe()}
    etapas = []
    for i, e in enumerate((plano.get("etapas") or [])[:8], start=1):
        if not isinstance(e, dict) or e.get("agente") not in nomes or not str(e.get("tarefa") or "").strip():
            continue
        deps = [int(d) for d in (e.get("depende_de") or []) if str(d).isdigit() and 0 < int(d) < i]
        etapas.append({"n": i, "agente": e["agente"], "titulo": str(e.get("titulo") or e["agente"])[:60],
                       "tarefa": str(e["tarefa"]).strip(), "depende_de": deps,
                       "aprovacao": bool(e.get("aprovacao"))})
    if len(etapas) < 1:
        return None
    # Renumera (etapas descartadas deixam buracos) mantendo as dependências válidas.
    novo = {e["n"]: k for k, e in enumerate(etapas, start=1)}
    for e in etapas:
        e["depende_de"] = [novo[d] for d in e["depende_de"] if d in novo]
        e["n"] = novo[e["n"]]
    if not any(e["aprovacao"] for e in etapas):
        etapas[-1]["aprovacao"] = True
    return {"titulo": str(plano.get("titulo") or "").strip()[:120], "etapas": etapas}


_SERVICOS = (
    ("comercial", "Proposta comercial", r"propost|or[çc]ament|fechar|contrato", True),
    ("designer", "Identidade visual", r"identidade|logo|marca|branding|paleta|visual", True),
    ("dev", "Site", r"\bsite|loja|e-?commerce|landing|p[áa]gina|sistema|app\b", False),
    ("trafego", "Plano de tráfego", r"tr[áa]fego|an[úu]ncio|campanha|ads\b|patrocinad", False),
    ("social", "Calendário de conteúdo", r"rede|instagram|social|post|conte[úu]do|tiktok", False),
    ("criativos", "Criativos e textos", r"criativ|legenda|banner|post|arte|copy|an[úu]ncio", False),
    ("video", "Vídeo", r"v[íi]deo|reels|motion|anima[çc]", False),
)


def _plano_padrao(pedido: str) -> dict:
    """Quando o gerente não devolve um plano usável: as etapas pelos serviços citados."""
    etapas = [{"n": 1, "agente": "atendimento", "titulo": "Briefing", "depende_de": [], "aprovacao": False,
               "tarefa": "Organize o pedido do projeto num briefing para a equipe."}]
    nomes = {a.nome for a in _equipe()}
    for agente, titulo, padrao, aprova in _SERVICOS:
        if agente in nomes and re.search(padrao, pedido, re.I):
            deps = [1] + [e["n"] for e in etapas if e["agente"] == "designer" and agente in ("dev", "criativos", "social", "video")]
            deps += [e["n"] for e in etapas if e["agente"] == "criativos" and agente == "video"]
            deps += [e["n"] for e in etapas if e["agente"] == "trafego" and agente == "criativos"]
            etapas.append({"n": len(etapas) + 1, "agente": agente, "titulo": titulo, "depende_de": sorted(set(deps)),
                           "aprovacao": aprova, "tarefa": f"{titulo} para este projeto, conforme o pedido e o briefing."})
    if len(etapas) == 1:
        etapas.append({"n": 2, "agente": "comercial", "titulo": "Proposta comercial", "depende_de": [1],
                       "aprovacao": True, "tarefa": "Proposta comercial para este projeto."})
    producao = [e["n"] for e in etapas[1:] if e["agente"] != "comercial"]
    if producao and "revisor" in nomes:
        etapas.append({"n": len(etapas) + 1, "agente": "revisor", "titulo": "Revisão final", "aprovacao": True,
                       "depende_de": producao, "tarefa": "Revise as entregas do projeto antes de irem ao cliente."})
    return {"titulo": "", "etapas": [e for e in etapas if e["agente"] in nomes]}


def _criar_etapas(proj: dict, plano: dict, cliente_id, base: int) -> list[dict]:
    """Cria as etapas do plano; as sem dependência já entram na fila."""
    ids: dict[int, int] = {}
    criados = []
    for e in plano["etapas"]:
        a = agentes.carregar(e["agente"])
        quem, _ = _quem(a)
        deps = [ids[d] for d in e["depende_de"] if d in ids]
        t = store.criar_trabalho(a.nome, e["tarefa"], quem, cliente_id, projeto_id=proj["id"],
                                 etapa=base + e["n"], titulo=e["titulo"], depende_de=deps,
                                 aprovacao=e["aprovacao"], status="esperando" if deps else "na_fila")
        ids[e["n"]] = t["id"]
        criados.append(t)
    return criados


def apos_entrega(t: dict) -> None:
    """Chamado pela fila quando uma etapa fica pronta: o plano do gerente vira
    etapas; etapas sem aprovação seguem sozinhas; as seguintes são liberadas."""
    t = store.trabalho(t["id"]) or t
    if not t.get("projeto_id"):
        return
    proj = store.projeto(t["projeto_id"])
    if proj is None:
        return
    if t["agente"] == "gerente" and t.get("etapa", 0) == 0:
        texto = ""
        try:
            from pathlib import Path
            texto = Path(t["arquivo"]).read_text(encoding="utf-8")
        except (OSError, TypeError):
            pass
        plano = _ler_plano(texto)
        obs = "" if plano else "O gerente não devolveu um plano legível; usei o plano padrão pelos serviços citados."
        plano = plano or _plano_padrao(proj["pedido"])
        if plano.get("titulo"):
            store.renomear_projeto(proj["id"], plano["titulo"])
        _criar_etapas(proj, plano, t["cliente_id"], base=0)
        store.atualizar(t["id"], status="aprovado", observacao=obs)
    elif not t.get("aprovacao"):
        store.atualizar(t["id"], status="aprovado", observacao="seguiu sozinho (etapa sem aprovação)")
    liberar(proj["id"])


def liberar(pid: int) -> int:
    """Etapas cujas dependências já foram aprovadas entram na fila."""
    etapas = store.trabalhos_do_projeto(pid)
    status = {t["id"]: t["status"] for t in etapas}
    liberadas = 0
    for t in etapas:
        if t["status"] != "esperando":
            continue
        deps = json.loads(t.get("depende_de") or "[]")
        if all(status.get(d) == "aprovado" for d in deps):
            store.atualizar(t["id"], status="na_fila")
            liberadas += 1
    if liberadas:
        from . import worker
        worker.iniciar()
    return liberadas


def situacao_projeto(etapas: list[dict]) -> str:
    validas = [t for t in etapas if t["status"] != "rejeitado"]
    if not validas or all(t["agente"] == "gerente" for t in validas):
        return "planejando"
    if any(t["status"] == "erro" for t in validas):
        return "erro"
    if any(t["status"] == "aguardando_aprovacao" for t in validas):
        return "aguardando"
    if all(t["status"] == "aprovado" for t in validas):
        return "concluido"
    return "andamento"


def refazer(tid: int, ajuste: str, anexos: list | None = None) -> dict:
    """Devolve à fila com o ajuste pedido, mantendo o histórico no pedido."""
    t = store.trabalho(tid)
    if t is None:
        raise KeyError(f"não existe o trabalho {tid}")
    pedido = t["pedido"]
    if (ajuste or "").strip():
        pedido += f"\n\nAjuste pedido na revisão: {ajuste.strip()}"
        if t["arquivo"]:
            pedido += f"\nVersão anterior: {t['arquivo']}"
    pedido, ids = _com_material(pedido, anexos)
    ids = list(dict.fromkeys(json.loads(t.get("anexos") or "[]") + ids))
    novo = store.criar_trabalho(t["agente"], pedido, t["executor"], t["cliente_id"],
                                projeto_id=t.get("projeto_id"), etapa=t.get("etapa") or 0,
                                titulo=t.get("titulo") or "", aprovacao=bool(t.get("aprovacao", 1)),
                                depende_de=json.loads(t.get("depende_de") or "[]"), anexos=ids)
    store.atualizar(tid, status="rejeitado", observacao=(ajuste or "").strip())
    _aprender(t, ajuste, "ajuste pedido")
    if t.get("projeto_id"):
        # As etapas seguintes passam a esperar a nova versão.
        for outra in store.trabalhos_do_projeto(t["projeto_id"]):
            deps = json.loads(outra.get("depende_de") or "[]")
            if tid in deps:
                store.atualizar(outra["id"], depende_de=[novo["id"] if d == tid else d for d in deps])
    return novo


def _aprender(t: dict, nota: str, como: str) -> None:
    """Ajustes e observações da revisão vão para o guia da marca do cliente."""
    if not (nota or "").strip():
        return
    try:
        from pathlib import Path
        from haizen.producao import guia
        proj = store.projeto(t["projeto_id"]) if t.get("projeto_id") else None
        marca = (proj or {}).get("marca_pasta") or store.pasta_da_marca(t.get("cliente_id"), t.get("pedido", ""))
        if marca and Path(marca).is_dir():
            guia.anotar(Path(marca), nota, f"{como} em {t.get('titulo') or t['agente']}")
    except Exception as e:  # noqa: BLE001 - aprender é extra; a revisão segue
        print(f"[HAIZEN] não anotei no guia da marca: {e}")


def tentar_de_novo(tid: int) -> dict:
    """Um trabalho que deu erro volta para a fila, com o mesmo pedido."""
    t = store.trabalho(tid)
    if t is None:
        raise KeyError(f"não existe o trabalho {tid}")
    if t["status"] != "erro":
        raise ValueError(f"o trabalho {tid} está {_NOMES_STATUS[t['status']]}, não com erro")
    try:
        quem, _ = _quem(agentes.carregar(t["agente"]))    # o executor atual do agente
    except KeyError:
        quem = t["executor"]
    executor._SEM_LOGIN["ate"] = 0.0                      # a pessoa pode ter acabado de fazer o /login
    return store.atualizar(tid, status="na_fila", erro="", executor=quem)


def aprovar(tid: int, observacao: str = "") -> dict:
    t = store.trabalho(tid)
    if t is None:
        raise KeyError(f"não existe o trabalho {tid}")
    if t["status"] != "aguardando_aprovacao":
        raise ValueError(f"o trabalho {tid} está {_NOMES_STATUS[t['status']]}, "
                         "não aguardando aprovação")
    feito = store.atualizar(tid, status="aprovado", observacao=(observacao or "").strip())
    _aprender(t, observacao, "aprovado com observação")
    if feito.get("projeto_id"):
        liberar(feito["projeto_id"])
    return feito


def descrever(t: dict) -> str:
    cli = store.cliente_por_id(t["cliente_id"])
    alvo = f" para {cli['nome']}" if cli else ""
    etapa = f" ({t['titulo']})" if t.get("titulo") else ""
    texto = f"Trabalho {t['id']}: {t['agente']}{etapa}{alvo}, {_NOMES_STATUS[t['status']]}"
    if t["status"] == "erro" and t["erro"]:
        texto += f" ({t['erro'][:120]})"
    return texto + "."


def resumo() -> str:
    pend = store.listar_trabalhos("aguardando_aprovacao", 10)
    fila = store.listar_trabalhos("na_fila", 10) + store.listar_trabalhos("executando", 5)
    erros = store.listar_trabalhos("erro", 3)
    projetos = []
    for proj in store.listar_projetos(5):
        sit = situacao_projeto(store.trabalhos_do_projeto(proj["id"]))
        if sit != "concluido":
            projetos.append(f"{proj['titulo']} ({ {'planejando': 'gerente planejando', 'andamento': 'em andamento', 'aguardando': 'esperando sua aprovação', 'erro': 'com erro'}.get(sit, sit) })")
    if not (pend or fila or erros or projetos):
        return "Nenhum trabalho pendente."
    partes = []
    if projetos:
        partes.append("Projetos: " + "; ".join(projetos) + ".")
    if pend:
        partes.append(f"{len(pend)} aguardando sua aprovação: "
                      + "; ".join(descrever(t) for t in pend))
    if fila:
        partes.append(f"{len(fila)} na fila ou em execução: "
                      + "; ".join(descrever(t) for t in fila))
    if erros:
        partes.append("Com erro: " + "; ".join(descrever(t) for t in erros))
    return " ".join(partes)

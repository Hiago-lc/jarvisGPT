"""As operações da HAIZEN, iguais para a voz (plugin) e para o Claude (MCP)."""
from __future__ import annotations

from . import agentes, executor, store

_NOMES_STATUS = {
    "na_fila": "na fila", "executando": "em execução",
    "aguardando_aprovacao": "aguardando sua aprovação", "aprovado": "aprovado",
    "rejeitado": "rejeitado", "erro": "com erro",
}


def delegar(agente: str, pedido: str, cliente: str = "",
            executor_forcado: str = "") -> dict:
    """Coloca um trabalho na fila. Devolve o trabalho e um aviso, se houver."""
    a = agentes.carregar(agente)
    aviso = ""
    cli = None
    if (cliente or "").strip():
        cli = store.buscar_cliente(cliente)
        if cli is None:
            cli = store.salvar_cliente(cliente.strip())
            aviso = f"Criei uma ficha nova para {cli['nome']}, ainda vazia. "
    quem = (executor_forcado or a.executor).lower()
    if quem not in agentes.EXECUTORES:
        raise ValueError(f"executor inválido: {quem}")
    if quem == "claude" and not executor.claude_disponivel():
        quem = "local"
        aviso += "O Claude Code não foi encontrado; usei o modelo local. "
    t = store.criar_trabalho(a.nome, pedido, quem, cli["id"] if cli else None)
    return {"trabalho": t, "aviso": aviso.strip()}


def refazer(tid: int, ajuste: str) -> dict:
    """Devolve à fila com o ajuste pedido, mantendo o histórico no pedido."""
    t = store.trabalho(tid)
    if t is None:
        raise KeyError(f"não existe o trabalho {tid}")
    pedido = t["pedido"]
    if (ajuste or "").strip():
        pedido += f"\n\nAjuste pedido na revisão: {ajuste.strip()}"
        if t["arquivo"]:
            pedido += f"\nVersão anterior: {t['arquivo']}"
    novo = store.criar_trabalho(t["agente"], pedido, t["executor"], t["cliente_id"])
    store.atualizar(tid, status="rejeitado", observacao=(ajuste or "").strip())
    return novo


def aprovar(tid: int, observacao: str = "") -> dict:
    t = store.trabalho(tid)
    if t is None:
        raise KeyError(f"não existe o trabalho {tid}")
    if t["status"] != "aguardando_aprovacao":
        raise ValueError(f"o trabalho {tid} está {_NOMES_STATUS[t['status']]}, "
                         "não aguardando aprovação")
    return store.atualizar(tid, status="aprovado", observacao=(observacao or "").strip())


def descrever(t: dict) -> str:
    cli = store.cliente_por_id(t["cliente_id"])
    alvo = f" para {cli['nome']}" if cli else ""
    texto = f"Trabalho {t['id']}: {t['agente']}{alvo}, {_NOMES_STATUS[t['status']]}"
    if t["status"] == "erro" and t["erro"]:
        texto += f" ({t['erro'][:120]})"
    return texto + "."


def resumo() -> str:
    pend = store.listar_trabalhos("aguardando_aprovacao", 10)
    fila = store.listar_trabalhos("na_fila", 10) + store.listar_trabalhos("executando", 5)
    erros = store.listar_trabalhos("erro", 3)
    if not (pend or fila or erros):
        return "Nenhum trabalho pendente."
    partes = []
    if pend:
        partes.append(f"{len(pend)} aguardando sua aprovação: "
                      + "; ".join(descrever(t) for t in pend))
    if fila:
        partes.append(f"{len(fila)} na fila ou em execução: "
                      + "; ".join(descrever(t) for t in fila))
    if erros:
        partes.append("Com erro: " + "; ".join(descrever(t) for t in erros))
    return " ".join(partes)

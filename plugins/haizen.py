"""HAIZEN: o Jarvis delega trabalhos aos agentes da agência e você aprova.

Uma ferramenta só, com uma ação, em vez de seis ferramentas: o modelo local
recebe poucas ferramentas por vez, e esta precisa caber sempre ("tier": core).
"""
from __future__ import annotations

PLUGIN = {
    "name": "haizen",
    "tier": "core",
    "brief": ("Agentes e central da HAIZEN: projeto (gerente divide entre a equipe), delegar trabalho, status, aprovar, fichas; "
              "financeiro, listar e registrar receitas/despesas/tarefas, concluir tarefa."),
    "description": (
        "Comanda os agentes da agência HAIZEN. Use quando o usuário pedir uma "
        "proposta, criativos, legendas, roteiros ou outro trabalho para um cliente, "
        "perguntar como estão os trabalhos, aprovar ou pedir ajuste numa entrega, "
        "ou guardar dados de um cliente. Ações: "
        "projeto (pedido + cliente): abre um projeto inteiro (ex.: site + marca + campanha) e o "
        "gerente divide em etapas para a equipe, com aprovação do usuário nos pontos importantes; "
        "use projeto quando o pedido envolver mais de um serviço. "
        "delegar (agente + pedido + cliente) para uma tarefa só, status, aprovar (id), "
        "refazer (id + pedido com o ajuste), ficha (cliente; com dados para "
        "salvar, sem dados para consultar), agentes (lista os agentes), "
        "central (abre a central com faturamento, clientes, tarefas e pipeline), "
        "financeiro (resume recebido, custos e pendências do mês), "
        "listar (tipo: receitas, despesas, tarefas, oportunidades ou clientes; filtro cliente), "
        "registrar (tipo + campos: valor, descricao, cliente, vencimento, recebido; "
        "tarefa: titulo, cliente, data_entrega), concluir (tarefa pelo titulo). "
        "Só diga que registrou depois que esta ferramenta confirmar."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "acao": {"type": "STRING",
                     "enum": ["projeto", "delegar", "status", "aprovar", "refazer", "ficha", "agentes",
                              "central", "financeiro", "listar", "registrar", "concluir"],
                     "description": "O que fazer"},
            "agente": {"type": "STRING",
                       "description": "Nome do agente, ex.: comercial, criativos"},
            "cliente": {"type": "STRING", "description": "Nome do cliente"},
            "pedido": {"type": "STRING",
                       "description": "O que o agente deve fazer, ou o ajuste pedido"},
            "id": {"type": "INTEGER", "description": "Número do trabalho"},
            "dados": {"type": "STRING",
                      "description": "Dados do cliente para salvar na ficha, em texto livre"},
            "tipo": {"type": "STRING",
                     "enum": ["receitas", "despesas", "tarefas", "oportunidades", "clientes"]},
            "valor": {"type": "NUMBER", "description": "Em reais, ex. 600"},
            "descricao": {"type": "STRING"},
            "vencimento": {"type": "STRING", "description": "AAAA-MM-DD ou DD/MM"},
            "recebido": {"type": "BOOLEAN", "description": "Receita já recebida / despesa já paga"},
            "titulo": {"type": "STRING", "description": "Título da tarefa"},
            "data_entrega": {"type": "STRING"},
        },
        "required": ["acao"],
    },
}


# Tela da central pedida em palavras.
_TELAS = (("financeiro", ("financ", "receita", "despesa", "faturamento", "pagamento")),
          ("clientes", ("cliente",)),
          ("tarefas", ("tarefa", "entrega")),
          ("pipeline", ("pipeline", "oportunidade", "lead", "funil")),
          ("escritorio", ("escritório", "escritorio", "equipe", "projeto")),
          ("agentes", ("agente", "trabalho", "aprova")),
          ("painel", ("painel", "resumo")))

_retomado = False


def _retomar(player) -> None:
    """Na primeira chamada da sessão: trabalhos que ficaram pela metade quando
    o Jarvis fechou voltam à fila, e a fila volta a andar."""
    global _retomado
    if _retomado:
        return
    _retomado = True
    from haizen import store, worker
    if store.recuperar_interrompidos() or store.listar_trabalhos("na_fila", 1):
        worker.iniciar(lambda msg: _log(player, msg))


def _log(player, texto: str) -> None:
    if player:
        try:
            player.write_log(f"HAIZEN: {texto}")
        except Exception:
            pass


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        from haizen import agentes, servicos, store, worker
    except Exception as e:
        return f"O módulo HAIZEN não carregou: {e}"

    try:
        _retomar(player)
    except Exception:
        pass
    p = parameters or {}
    acao = str(p.get("acao") or "").strip().lower()
    try:
        if acao == "delegar":
            agente = str(p.get("agente") or "").strip()
            pedido = str(p.get("pedido") or "").strip()
            if not agente or not pedido:
                return "Preciso do agente e do pedido para delegar."
            r = servicos.delegar(agente, pedido, str(p.get("cliente") or ""))
            t = r["trabalho"]
            worker.iniciar(lambda msg: _log(player, msg))
            quem = "o Claude Code" if t["executor"] == "claude" else "o modelo local"
            return (f"{r['aviso']} Trabalho {t['id']} na fila para o agente "
                    f"{t['agente']}, feito por {quem}. Aviso quando estiver pronto.").strip()

        if acao == "projeto":
            pedido = str(p.get("pedido") or "").strip()
            if not pedido:
                return "O que o projeto precisa? Por exemplo: site, identidade visual e campanha de lançamento."
            r = servicos.criar_projeto(pedido, str(p.get("cliente") or ""))
            worker.iniciar(lambda msg: _log(player, msg))
            return (f"{r['aviso']} Projeto {r['projeto']['id']} aberto. O gerente está montando o plano "
                    "e distribuindo para a equipe; acompanhe na tela Escritório. "
                    "Aviso quando uma etapa precisar da sua aprovação.").strip()

        if acao == "status":
            return servicos.resumo()

        if acao == "aprovar":
            if not p.get("id"):
                return "Qual o número do trabalho?"
            t = servicos.aprovar(int(p["id"]))
            return f"Trabalho {t['id']} aprovado."

        if acao == "refazer":
            if not p.get("id"):
                return "Qual o número do trabalho?"
            novo = servicos.refazer(int(p["id"]), str(p.get("pedido") or ""))
            worker.iniciar(lambda msg: _log(player, msg))
            return f"Pedi uma nova versão: trabalho {novo['id']} na fila."

        if acao == "ficha":
            nome = str(p.get("cliente") or "").strip()
            if not nome:
                clientes = store.listar_clientes()
                return ("Clientes: " + ", ".join(c["nome"] for c in clientes)
                        if clientes else "Nenhum cliente cadastrado ainda.")
            dados = str(p.get("dados") or "").strip()
            if dados:
                c = store.salvar_cliente(nome, notas=dados)
                return f"Ficha de {c['nome']} atualizada."
            c = store.buscar_cliente(nome)
            if c is None:
                return f"Não encontrei a ficha de {nome}."
            campos = "; ".join(f"{k}: {v}" for k, v in c["dados"].items())
            return f"{c['nome']}. {campos} {c['notas']}".strip()

        if acao == "agentes":
            lista = agentes.listar()
            if not lista:
                return "Nenhum agente configurado."
            return "Agentes: " + "; ".join(f"{a.nome} ({a.descricao})" for a in lista)

        if acao == "central":
            # Dentro da janela do Jarvis, a central abre ali mesmo, na tela
            # pedida ("abre o financeiro"); sem a janela, no navegador.
            pedido = " ".join(str(p.get(k) or "") for k in ("pedido", "tipo", "dados")).lower()
            rota = next((r for r, chaves in _TELAS if any(c in pedido for c in chaves)), "")
            if player is not None and hasattr(player, "show_central"):
                player.show_central(rota)
                return f"Abri a central da HAIZEN{' em ' + rota if rota else ''} aqui na janela."
            from haizen.central import servidor
            servidor.iniciar(abrir_navegador=True)
            return "Abri a central da HAIZEN no navegador."

        if acao == "financeiro":
            from haizen.central import dados
            hoje = dados.hoje()
            d = dados.painel(hoje[:8] + "01", hoje)
            brl = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
            partes = [f"Este mês: recebido R$ {brl(d['receita'])}, custos R$ {brl(d['custos'])}, "
                      f"lucro R$ {brl(d['lucro'])}."]
            if d["a_receber"]:
                partes.append(f"A receber: R$ {brl(d['a_receber'])}"
                              + (f", sendo R$ {brl(d['vencido'])} vencido." if d["vencido"] else "."))
            if d["tarefas_atrasadas"]:
                partes.append(f"{d['tarefas_atrasadas']} tarefas atrasadas.")
            return " ".join(partes)

        if acao in ("listar", "registrar", "concluir"):
            # Mesma lógica do chat da central: as duas interfaces gravam igual.
            from haizen.central.cerebro import _central
            args = {k: v for k, v in parameters.items() if v not in (None, "")}
            if args.get("tipo") == "despesas" and "recebido" in args:
                args["pago"] = args.pop("recebido")
            return _central(args)

        return ("Ação desconhecida. Use delegar, status, aprovar, refazer, ficha, agentes, "
                "central, financeiro, listar, registrar ou concluir.")
    except (KeyError, ValueError) as e:
        return str(e).strip("'\"")
    except Exception as e:
        return f"A HAIZEN falhou: {type(e).__name__}: {e}"

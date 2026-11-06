"""Núcleo HAIZEN: clientes, agentes e a fila de trabalhos que o Jarvis comanda.

    agentes.py   definições dos agentes (arquivos Markdown em haizen/agentes/)
    store.py     fichas de clientes e trabalhos (SQLite)
    executor.py  quem executa um trabalho: o modelo local ou o Claude Code
    worker.py    processa a fila em segundo plano
    mcp_server.py  expõe tudo isso ao app do Claude

Nada aqui publica, envia ou gasta nada: toda entrega termina em
"aguardando aprovação", e só uma pessoa a aprova.
"""

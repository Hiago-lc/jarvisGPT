# HAIZEN: agentes comandados pelo Jarvis e criados com o Claude

O Jarvis passa a delegar trabalhos a agentes da HAIZEN. Cada entrega fica aguardando a sua aprovação: nada é publicado, enviado ou cobrado sozinho.

| Quem | Papel | Custo |
| --- | --- | --- |
| Jarvis (voz, modelo local) | Recebe o pedido, põe na fila, avisa quando fica pronto | Zero |
| Agente com `executor: local` | Textos curtos: legendas, roteiros, variações de anúncio | Zero |
| Agente com `executor: claude` | Propostas, textos longos, código: roda o Claude Code no seu PC | Limite da assinatura do Claude |
| Claude, no app | Cria e ajusta agentes, revisa entregas, cadastra clientes | Assinatura do Claude |

## Pela voz

- "Jarvis, pede para o comercial uma proposta de site institucional para a Padaria Aurora."
- "Como estão os trabalhos?"
- "Aprova o trabalho 3."
- "Refaz o trabalho 3 com um tom mais informal."
- "Salva na ficha da Aurora: prefere tons pastel, público de 25 a 40 anos."
- "Quais agentes eu tenho?"

As entregas ficam em **Documentos\HAIZEN\entregas**, um arquivo Markdown por trabalho. Se o Jarvis fechar no meio de um trabalho, ele volta para a fila na próxima vez que você usar a HAIZEN.

## Agentes incluídos

- **comercial** (`executor: claude`): briefing → proposta comercial.
- **criativos** (`executor: local`): legendas, roteiros de Reels, anúncios, calendário de posts.

Cada agente é um arquivo em `haizen/agentes/`. Para criar outro, peça ao Claude (abaixo) ou copie um arquivo e edite.

## O Claude cria e gerencia os agentes (MCP)

Uma vez, no PowerShell, dentro de `C:\JARVIS`:

```powershell
py -m pip install mcp
py -m haizen.instalar_mcp --claude-code
```

Depois, feche o app do Claude pela bandeja do Windows (não basta fechar a janela) e abra de novo. A HAIZEN aparece nas ferramentas do chat. O instalador faz uma cópia de segurança da configuração e mantém os outros servidores que você já tenha.

Exemplos de pedidos ao Claude:

- "Crie um agente de SEO para a HAIZEN que escreve títulos e meta descrições. Mostre o prompt antes de salvar."
- "Cadastre o cliente Padaria Aurora: segmento padaria artesanal, Instagram @padariaaurora, tom acolhedor."
- "Revise a entrega do trabalho 4 e me diga o que está fraco."
- "Faça você mesmo o trabalho 5 e registre a entrega." (usa a conversa atual, sem rodar o Claude Code)

## Cuidados com a assinatura Pro

- O Claude Code e o app do Claude dividem o mesmo limite de uso. Deixe `executor: claude` só para o que vale a pena (propostas, código).
- Se existir uma variável `ANTHROPIC_API_KEY` no Windows, o Claude Code cobra pela API. A HAIZEN remove essa variável antes de chamar o Claude Code, mas o ideal é nem tê-la.
- Se o Claude Code não for encontrado, o trabalho roda no modelo local e o Jarvis avisa.

## Onde ficam os dados

| O quê | Onde |
| --- | --- |
| Fichas e trabalhos | `%LOCALAPPDATA%\JarvisGPT\haizen.db` |
| Entregas | `Documentos\HAIZEN\entregas` |
| Agentes | `C:\JARVIS\haizen\agentes\*.md` |

Variáveis opcionais: `HAIZEN_DB`, `HAIZEN_ENTREGAS_DIR`, `HAIZEN_AGENTES_DIR`, `HAIZEN_CLAUDE_TIMEOUT` (segundos, padrão 900), `HAIZEN_LOCAL_TIMEOUT_MS` (padrão 300000).

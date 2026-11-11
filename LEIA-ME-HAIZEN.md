# HAIZEN: agentes comandados pelo Jarvis e criados com o Claude

O Jarvis passa a delegar trabalhos a agentes da HAIZEN. Cada entrega fica aguardando a sua aprovação: nada é publicado, enviado ou cobrado sozinho.

## O Claude é o cérebro do Jarvis (versão web)

O atalho **Jarvis HAIZEN** abre a central numa janela própria. Quem responde e age é o **Claude**, pelo Claude Code do PC e com a sua assinatura (não a API). Ele continua a mesma conversa entre uma mensagem e outra, e usa as ferramentas do Jarvis:

| Ferramenta | O que faz |
| --- | --- |
| Financeiro, clientes, tarefas, pipeline | Consulta, registra, marca como recebido, conclui (confere antes para não duplicar) |
| Google Agenda | Lista, cria, muda, move e exclui eventos; horários livres |
| WhatsApp | Lê conversas e ouve áudios; para **enviar**, a mensagem espera você clicar em Confirmar na tela |
| Projetos e agentes | Abre projetos, acompanha, aprova e pede novas versões quando você manda |
| Guia da marca | Guarda preferências de cada cliente que os agentes seguem sempre |
| Computador | Abre programas, volume, navegador, arquivos, YouTube... (o que é irreversível pede confirmação) |
| Pastas dos clientes | Lê logos, manuais e referências para responder (sem alterar nada) |

Fale pelo microfone (botão **Falar** ou **Conversa**) ou digite. **Limpar conversa** começa uma conversa nova com o Claude.

Se o Claude Code não estiver instalado, o Jarvis volta ao modelo local. Se ele não estiver conectado à sua conta, a resposta explica como conectar (`conectar-claude.bat`, depois `/login`). Para forçar o modelo local: variável `JARVIS_CEREBRO=local`. Para escolher o modelo do Claude: `JARVIS_CLAUDE_MODELO` (ex.: `sonnet`).

### O fluxo de produção

1. Você pede ao Jarvis ("faz um reels da excursão para Porto Seguro com as filmagens da pasta dela").
2. O Claude abre um **projeto**; o gerente planeja e os agentes produzem os arquivos na pasta do cliente, em `JARVIS - para revisar`.
3. Você revisa na tela do trabalho e aprova ou pede ajuste ("o texto do gancho ficou pequeno").
4. Cada ajuste e cada observação ao aprovar vira uma linha no **guia da marca** do cliente (`JARVIS - para revisar\_GUIA DA MARCA (Jarvis).md`), e todo agente lê o guia antes de produzir. O que você aprovou uma vez não precisa ser repetido.
5. Tipos de peça que já deram certo viram **receitas** (`haizen\producao\receitas\*.md`), que os agentes seguem: a primeira é o reels de pacote de viagem. Se o cliente tiver um `CLAUDE.md` próprio na pasta dele, os agentes leem também.

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
- "Abre um projeto para a Loja Aurora: proposta de e-commerce e campanha de Black Friday."

As entregas ficam em **Documentos\HAIZEN\entregas**, um arquivo Markdown por trabalho. Se o Jarvis fechar no meio de um trabalho, ele volta para a fila na próxima vez que você usar a HAIZEN.

## Escritório e projetos

A tela **Escritório** (barra lateral) mostra a equipe trabalhando: cada agente na sua mesa, com um balão dizendo o que está fazendo, o que terminou e espera você, ou onde travou. Atualiza sozinha.

Um **projeto** junta vários serviços. Clique em **Novo projeto** ou diga: "Jarvis, abre um projeto para a Padaria Sol: site novo, identidade visual e lançamento no Instagram". Então:

1. O **gerente** lê o pedido e monta o plano: as etapas, quem faz cada uma e qual depende de qual.
2. Cada etapa entra na fila quando as anteriores estão aprovadas, e o agente recebe as entregas delas para continuar o trabalho.
3. Etapas marcadas com ✓? (proposta, conceito de marca, revisão final) esperam você aprovar; as outras seguem sozinhas.
4. Clique numa etapa para ler a entrega, aprovar ou pedir nova versão; as etapas seguintes passam a usar a versão nova.

A fila faz um trabalho por vez (a placa de vídeo é uma só); o escritório mostra os outros esperando.

## Os agentes produzem arquivos

Cada trabalho ganha uma pasta dentro da pasta do cliente:
`CLIENTES\<cliente>\JARVIS - para revisar\<projeto>\<etapa>`. Ali o agente grava as peças prontas (PNG no tamanho exato, PDF, MP4, site), os arquivos-fonte em `fontes\` (HTML, para ajustes) e o `RELATORIO.md`. Ele lê o material da pasta do cliente (logo, fotos de produto, fontes, peças antigas) sem alterar nada lá. Você revisa as peças na tela do trabalho (miniaturas, vídeos, "Abrir pasta") e aprova.

A pasta do cliente vem da tela Clientes (marcas e pastas). No Novo projeto dá para escolher a marca; no automático, vale a marca citada no pedido ou a única marca do cliente.

Uma vez, rode `instalar-producao.bat` (instala o ffmpeg para os vídeos e confere o navegador que gera as imagens).

Não há gerador de imagens por IA: os agentes montam as peças com as fotos reais do cliente; quando falta uma foto, avisam em Pendências.

## Agentes incluídos

| Agente | Faz | Executor |
| --- | --- | --- |
| gerente | Monta o plano do projeto e distribui | claude |
| atendimento | Briefing do pedido e perguntas para o cliente | claude |
| comercial | Proposta comercial | claude |
| designer | Conceito de identidade visual, paleta, tipografia | claude |
| criativos | Legendas, roteiros, anúncios | claude |
| trafego | Plano de campanha de anúncios | claude |
| social | Linha editorial e calendário de posts | claude |
| dev | Mapa do site, textos, tecnologia, código de páginas | claude |
| financeiro | Orçamento, cronograma de pagamento, cobrança | claude |
| video | Vídeos curtos (reels, stories, anúncios) com clipes, fotos e textos animados | claude |
| revisor | Confere os arquivos antes do cliente | claude |

Todos os agentes trabalham pelo Claude Code, com a sua assinatura (sem custo por uso). O Claude Code precisa estar conectado à sua conta: rode `conectar-claude.bat` e digite `/login` uma vez. Se ele não estiver conectado, o trabalho para com essa instrução (o modelo local não é usado, porque divide a placa de vídeo com a voz do Jarvis). Para liberar o modelo local mesmo assim: `setx HAIZEN_PERMITIR_LOCAL 1`.

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

Variáveis opcionais: `HAIZEN_CLAUDE_PATH` (caminho do `claude.exe`, se ele não for achado sozinho), `HAIZEN_DB`, `HAIZEN_ENTREGAS_DIR`, `HAIZEN_AGENTES_DIR`, `HAIZEN_CLAUDE_TIMEOUT` (segundos, padrão 900), `HAIZEN_LOCAL_TIMEOUT_MS` (padrão 300000).

## Social (Instagram da HAIZEN)

A aba **Social** cuida do Instagram da própria agência pela API oficial da Meta:

- **Análise** (toda segunda às 08:00, ou em "Analisar agora"): perfil, posts e números (alcance, salvamentos, compartilhamentos, retenção dos reels), a grade vista em imagens, nota de 0 a 100 em 10 critérios, o que melhorar e bio sugerida.
- **Calendário da semana**: cada post vem com formato, gancho, roteiro (ou texto das lâminas) e legenda. Você aprova e ele vira trabalho da equipe (criativos para carrossel e estático, vídeo para reels).
- **Publicar**: quando você aprova a peça no Escritório, o post fica "pronto"; você revisa a legenda e publica agora ou agenda. Nada vai ao ar sem o seu clique.
- **Raio-x de referências**: cole "@perfil" e o link de um post/reels de uma conta profissional; o Jarvis explica gancho, ritmo, legenda e CTA e sugere 3 adaptações para a HAIZEN.

Conexão: um token do seu app da Meta com as permissões de Instagram (o passo a passo aparece na aba). O token fica só no PC (`%LOCALAPPDATA%\JarvisGPT\instagram_token.json`) e vence a cada ~60 dias.

## Rotina diária (Painel → Rotina)

- **Resumo da manhã** (08:00): agenda, tarefas atrasadas, entregas para aprovar, o que receber/pagar, tráfego e Instagram. Aparece no topo do Painel e vai só para o SEU WhatsApp (o contato da Rotina ou o da tela Tráfego). O resumo do tráfego vai junto, numa mensagem só.
- **Backup diário** do banco e das configurações (sem tokens) em `Meu Drive\JARVIS - backups\AAAA-MM-DD`, guardando 14 dias. Para restaurar: feche o Jarvis e copie `haizen.db` de volta para `%LOCALAPPDATA%\JarvisGPT`.
- **Cobranças**: 2 dias antes, no dia e 3 dias depois do vencimento o Jarvis prepara o lembrete. Nada sai sozinho: você revisa o texto e clica em Enviar. Em "Como pagar" ponha a chave PIX/link.
- **Relatório mensal de tráfego** (dia 1): PDF com os números do mês de cada conta ativa. Você aprova (o PDF vai para a pasta do cliente, em "Relatórios de tráfego") e envia a mensagem pronta pelo WhatsApp.

## Qualidade dos agentes

- Cada função tem uma base de conhecimento sênior em `haizen/agentes/conhecimento/`. Para trocar por um texto seu, ponha `<nome>.md` em `%LOCALAPPDATA%\JarvisGPT\conhecimento\`.
- Peças visuais passam por um diretor de arte (outra chamada do Claude) antes de chegarem até você; se ele reprovar, o agente corrige uma vez. O modelo dela se escolhe em Uso do Claude ("Checagem de qualidade"); para desligar, `HAIZEN_QA=0`.
- Vídeo: animações com GSAP/Lottie quadro a quadro e legenda automática palavra a palavra (`legendar`, Whisper local).
- O token do Instagram fica criptografado pela sua conta do Windows (DPAPI).

## E-commerce (Shopify e Tray dos clientes)

- Tela **E-commerce**: cada loja com vendas de ontem, 7 e 30 dias, ticket médio, conversão (Shopify), mais vendidos, estoque acabando e produtos parados. Análise todo dia às 07:40 (entra no resumo da manhã).
- O Jarvis **propõe** (cupom, desconto automático, promoção de/por, preço, descrição/SEO, pausar/ativar produto, desativar cupom) e **você aprova** (ou ajusta e aprova). Quem aplica é o código, exatamente o que está na proposta. Na Shopify, a promoção de/por volta ao preço antigo sozinha no dia seguinte ao fim.
- Pelo Jarvis: "cria um cupom BLACK15 de 15% na loja X até domingo" → ele monta a proposta, mostra e só aplica com o seu OK.
- **Conectar Shopify**: na loja do cliente, criar um app próprio (Configurações → Apps → Desenvolver apps, ou Dev Dashboard) com read/write_products, read_orders, read/write_discounts, read_reports, read_inventory; colar o token (shpat_…) ou Client ID + secret.
- **Conectar Tray**: a HAIZEN precisa ser parceira Tray (partners.tray.com.br) e ter um aplicativo; cadastre consumer key/secret em E-commerce → Configurar. Cada cliente instala o app em Meus aplicativos; cole o endereço da API e o code.
- Os acessos ficam criptografados (DPAPI) em `%LOCALAPPDATA%\JarvisGPT\ecommerce_acessos.json`, fora do banco e do backup.

## Direção de arte dos agentes (criativos, designer, vídeo)

- **Pesquisa visual obrigatória**: `referencias` captura a Biblioteca de Anúncios da Meta, Behance, Dribbble e Pinterest com o tema; o agente vê as capturas, monta a `prancha` e escreve `fontes/direcao.md` (o que pegar de cada referência).
- **Kit de design** (`haizen/producao/kit/`): CSS com escala tipográfica forte, texturas, selos, CTA e zonas seguras; `motion.js` para vídeo (revelar palavras, máscaras, Ken Burns, contador, marca-texto); 8 modelos de layout (produto herói, editorial, oferta, bento, prova, capa de carrossel, story, reels cinético).
- **Foto**: `recortar` tira o fundo (rembg, instalado na primeira vez) e `tratar_foto` dá o mesmo tratamento de cor à série.
- **Duas direções** da peça principal, comparadas lado a lado antes de escolher.
- **Vídeo** conferido em folha de contato (12 quadros). O agente de vídeo passou a usar o Opus.
- **Diretor de criação** revisa comparando com as referências; só passa com nota ≥ 8, senão o agente refaz.

## Google Ads (contas dos clientes)

- Tela **Google Ads**: gasto, conversões, CPA e ROAS (ontem, 7 e 30 dias), campanhas com perda por orçamento, termos de pesquisa que gastaram sem converter. Análise todo dia às 07:20 das contas marcadas (entra no resumo da manhã).
- O Jarvis **propõe** (orçamento, pausar/ativar campanha, negativar termos, pausar palavra-chave ou anúncio) e **você aprova**. Mudança de orçamento acima de 50% de uma vez e orçamento compartilhado são barrados.
- **Conectar** (uma vez, neste PC): no Google Cloud, ativar a Google Ads API, pedir o acesso **Explorer** (Google Ads API → Visão geral → Upgrade access level) e usar um cliente OAuth "App para computador". Desde 09/2026 não existe mais developer token. O refresh token fica criptografado (DPAPI) em `%LOCALAPPDATA%\JarvisGPT\ecommerce_acessos.json`.

## Pedir ao Jarvis em cada ferramenta

- Nas telas Google Ads, Tráfego, E-commerce, Social, Financeiro e Clientes há o botão **Pedir ao Jarvis** (canto inferior direito): um chat que já sabe em que tela você está. Pedidos de mudança viram propostas na própria tela, para você aprovar; dá para anexar arquivos.
- Google Ads: o Jarvis cria **campanha de pesquisa completa** (orçamento, lance, cidades, grupos, palavras-chave, anúncios responsivos, negativas) como proposta, com prévia do anúncio. Ao aprovar você escolhe se ela nasce ativa ou pausada (padrão: pausada).
- Google Ads também cria **YouTube / Demand Gen** (anúncio em vídeo e/ou imagem no YouTube, Discover, Gmail e Display) e **Display** (anúncio responsivo). Vídeo anexado no chat é enviado ao YouTube como **não listado**; as imagens são cortadas sozinhas em 1,91:1, 1:1 e 4:5 e o logo vira 1:1. Criar campanha de vídeo/imagem roda em segundo plano e avisa no fim. Campanhas do tipo "Vídeo" clássico não podem ser criadas pela API do Google: o caminho é o Demand Gen.
- Para enviar vídeo ao YouTube: ative a **YouTube Data API v3** no projeto do Google Cloud e reconecte o Google Ads (Configurar → Desconectar → Conectar), para liberar a permissão do YouTube. A conta Google precisa ter um canal.

## Tráfego: subir peças e editar propostas

- O conector da Meta não envia arquivo do PC. O Jarvis agora **envia as imagens e vídeos** para a conta de anúncios (Marketing API: /adimages e /advideos) antes de o gestor criar os anúncios, e passa o image_hash / video_id prontos. Precisa de um **token do Meta Ads com ads_management** (Tráfego → Configurar; o ideal é o de um *usuário do sistema* do Gerenciador de Negócios, que não vence). Sem ele, para imagem, tenta o endereço público pela Página da HAIZEN.
- O que já subiu fica guardado na proposta: tentar de novo não reenvia.
- No chat, ajustes numa proposta existente (texto, conjunto, peça nova, orçamento) **editam a proposta** (`trafego_editar` / `googleads_editar`) em vez de criar outra. A conversa do Jarvis agora guarda mais contexto antes de recomeçar.

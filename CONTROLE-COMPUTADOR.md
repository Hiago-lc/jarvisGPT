# Jarvis: Gemini e controle do computador

## Voltar ao Gemini

Esta versão mantém o Gemini Live e não precisa de créditos OpenAI.
Na pasta do projeto, com o ambiente virtual ativo:

```sh
python -m pip install -r requirements.txt
python start_gemini.py
```

Se ainda não há chave Gemini salva, execute `python main.py` e configure-a
na tela inicial. Feche o aplicativo e inicie `python start_gemini.py`.
O inicializador restaura o Gemini para conversa e tarefas auxiliares,
preservando suas outras configurações. Não use `start_openai.py`.

## Exemplos de pedidos

- “Abra o Bloco de Notas.” Depois: “Na janela do Bloco de Notas, digite: Olá, João!”
- “Clique no campo de pesquisa visível.”
- “Na janela do Chrome, pressione Ctrl+L.” Depois: “Digite example.com.”
- “Role a página para baixo.”
- “Tire uma captura da tela.”

Para digitar em uma janela específica, o modelo pode chamar `computer_control`
com `action=type`, `title=<parte do título>` e `text=<texto>`. Para localizar e
clicar com Gemini, use `action=screen_click` e `description=<elemento visível>`.
As mesmas descrições funcionam com click, double_click e right_click.
Em type, smart_type e paste, description localiza e clica no campo antes de
inserir o texto, dentro da mesma chamada.
O aplicativo precisa estar aberto e o campo de texto deve estar visível.
Localização visual usa uma captura da tela principal enviada ao Gemini; ela
não garante identificar corretamente todos os elementos. O modelo deve conferir
a tela após cada mudança antes de continuar uma tarefa.

## Correções

- Texto com acentos usa a área de transferência, inclusive palavras curtas.
- A área de transferência textual anterior é restaurada após colar; formatos
  não textuais (imagens, arquivos, conteúdo rico) não são preservados.
- No Windows, foco de janela é verificado. Nenhuma digitação é enviada quando
  a janela solicitada não foi encontrada, ficou ambígua ou não recebeu foco.
- Cliques por descrição agora localizam o alvo, sem ignorar o parâmetro.
- Coordenadas são validadas; cliques visuais convertem as dimensões da captura
  para as dimensões usadas pelo mouse. Use a tela principal para essas ações.
- Chamadas simultâneas compartilham uma trava para evitar misturar comandos.
- Retornos de entrada são marcados como não verificados: enviar um clique não
  prova que o aplicativo fez o que se esperava.

## Se o computador não responder

O Jarvis precisa rodar no próprio computador, numa sessão de desktop desbloqueada.
Na nuvem sem desktop, não é possível testar cliques em seus programas Windows.

No Windows, programas executados como administrador podem recusar comandos
vindos de um Jarvis sem a mesma permissão. Prefira abrir o programa normalmente.
UAC, tela de login e telas protegidas não são controladas por esta integração.
Mova o mouse para um canto da tela para acionar a parada de emergência do
PyAutoGUI. Afaste-o do canto antes de pedir outra ação.

Para testar manualmente, abra um documento vazio no Bloco de Notas, peça ao
Jarvis para digitar “Olá, João! Ação e café.”, confira o texto e peça para clicar
em um menu sem alterações destrutivas. Se falhar, envie a linha de erro do log,
sem enviar chaves de API. Capturas, buscas visuais e voz exigem cota Gemini
disponível; o funcionamento não é ilimitado.

## Cliques precisos e tarefas com várias etapas

Atualize o código e dependências e use `python start_gemini.py`.
No Windows, a busca tenta primeiro um controle acessível com nome exato e único
na janela ativa (UI Automation, via pywinauto). Se não encontrar, o Gemini
localiza uma caixa na captura com coordenadas normalizadas; respostas inválidas,
alvos incertos e mudanças da janela ativa durante a busca são recusados.
Isso melhora a localização, mas não elimina erros de interpretação visual.
A captura continua limitada ao monitor principal. Coloque ali o aplicativo alvo.

Para uma sequência, peça por exemplo:

> “Na página aberta, clique na busca, pesquise receitas de bolo e abra um resultado.”

O modelo recebe a ferramenta `screen_task` para executar essa sequência.
Ela observa a tela após cada comando e só escolhe a próxima ação a partir da
nova captura. Não é uma lista de cliques calculada de uma vez.
O limite padrão é 8 ações, ajustável até 12, com janela de execução de 2 minutos.
Se o objetivo não for confirmado nesse limite, a ferramenta informa que ficou
incompleto. Não é monitoramento permanente nem uma rotina agendada.

Para interromper, clique em **INTERRUPT** ou pressione **Esc com a janela do
Jarvis em foco**. O cancelamento é checado também após as chamadas ao Gemini;
nenhum novo comando de entrada deve ser enviado após a checagem detectar a
interrupção. O canto da tela continua acionando a parada de emergência do mouse.
Chamadas de rede já iniciadas podem levar alguns segundos para terminar.
Não dependa de um pedido de parada por voz durante uma tarefa: use o botão.

O agente foi instruído a pausar antes de envio de mensagens, compras, exclusões
e outras ações irreversíveis, pedindo intervenção manual. Isso é uma orientação
ao modelo, não um mecanismo de isolamento do sistema. Use tarefas pequenas e
acompanhe o computador durante a execução.
Cada observação e busca visual pode consumir cota do Gemini.
Os testes automatizados usam simulações; a precisão no seu Windows ainda
precisa ser conferida com seus aplicativos, resolução e escala de tela.

## Mensagens: digitar, corrigir, limpar e excluir

Atualize os arquivos, mantendo suas configurações privadas, e inicie por
`python start_gemini.py`.

- “Na conversa com Vitor, digite ‘Estou testando o JARVIS agora’, sem enviar.”
- “Limpe o rascunho da mensagem que ainda não foi enviada.”
- “Substitua o rascunho por ‘Vou chegar às 14h’, sem enviar.”
- “Apague as últimas três letras do campo de mensagem.”
- “Na conversa com Vitor, exclua **para mim** a mensagem enviada com o texto
  exato ‘Estou testando o JARVIS agora.’”

`clear_field`/`clear_draft` seleciona e remove o texto do campo informado;
`replace_text` substitui seu conteúdo. O campo é localizado e clicado antes de
editar. Atalhos como Control+A e DEL são normalizados, e teclas inválidas deixam
de ser reportadas como se tivessem sido executadas. `press` aceita de 1 a 100
repetições, útil para Backspace em correções pequenas.

Para uma mensagem já enviada, o modelo precisa fornecer à ferramenta screen_task
`delete_recipient`, `delete_message_text` e `delete_scope` (`for_me` ou
`for_everyone`) a partir do pedido do usuário. Quando falta o escopo, ele pergunta.
O agente visual pode passar o mouse sobre o balão com `hover` para revelar o
menu, observar os controles e seguir a opção solicitada. Esse fluxo depende do
aplicativo mostrar a mensagem e permitir a exclusão: não é uma API universal
de WhatsApp/Telegram. A identificação do alvo é feita pelo modelo na tela;
acompanhe a operação, especialmente em exclusões. Não autoriza excluir conversas
inteiras, contatos ou arquivos, nem enviar o rascunho. Uma tela ou mensagem
recebida não pode autorizar exclusões.

A análise visual agora usa uma faixa REST do Gemini com no máximo duas
tentativas e orçamento de 12 segundos (rápido) ou 18 segundos (análise mais
complexa), em vez de abrir primeiro uma sessão auxiliar Gemini Live. Cada
requisição recebe só a parcela restante, com repetição automática do SDK
desativada nessa faixa. A conversa por voz continua no Live. Isso reduz as
esperas causadas pelo `live: TimeoutError`; limites de rede, SDK e cota ainda
podem impedir a tarefa. Modelos temporariamente indisponíveis não são testados
em um ciclo sem limite. A consulta aos controles nativos do Windows espera no
máximo 350 ms antes de seguir pelo caminho visual.

Se uma tarefa parar, o motivo completo também aparece no painel, sem depender
da linha resumida de 80 caracteres do terminal. Os testes automatizados usam
simulações: esta atualização não foi validada em uma sessão real do WhatsApp
ou Telegram no Windows.

## Rascunhos no WhatsApp Web sem depender de visão Gemini

Quando o pedido menciona **WhatsApp Web**, use a ferramenta `whatsapp_draft`.
Ela abre uma janela visível de Chrome/Edge com perfil próprio do Jarvis, busca
o nome exato, confere o cabeçalho da conversa, preenche o campo e lê o conteúdo
de volta antes de afirmar que o rascunho foi preparado. Não implementa envio,
não pressiona Enter e não clica em botão de enviar. Pode também ler ou limpar
o rascunho. Se já houver outro rascunho, uma substituição deve ser pedida
explicitamente. Contatos com nomes ambíguos exigem um nome único.

Atualize e reinicie o Jarvis. Exemplos:

- “No WhatsApp Web, escreva para Vitor ‘Estou testando agora’, sem enviar,
  e leia o rascunho para mim.”
- “Leia o rascunho do Vitor no WhatsApp Web.”
- “Limpe o rascunho do Vitor no WhatsApp Web.”
- “Substitua o rascunho do Vitor no WhatsApp Web por ‘Chego às 14h’.”

O perfil é separado do seu navegador habitual. No primeiro uso, se aparecer
QR Code, vincule pelo celular: WhatsApp → Dispositivos conectados → Conectar
um dispositivo. Após conectar, repita o pedido. O perfil fica na pasta de dados
do usuário, em `whatsapp-web-profile`, e não deve ser publicado ou compartilhado.
Os backups de memória do Jarvis não incluem esse perfil de autenticação.

Se faltar Playwright, instale com `python -m pip install playwright`. O driver
tenta Chrome e Edge instalados; alternativamente, instale um navegador próprio
para automação com `python -m playwright install chromium`. Não conecta uma
conta sem sua autorização nem recupera sessões de outros perfis do navegador.

Esse fluxo é específico do **Web**, não do aplicativo nativo do Windows. Não
será usado para um pedido explicitamente dirigido ao aplicativo nativo. Mudanças
na interface do site podem impedir a localização dos controles; nesses casos
o fluxo para em vez de escrever em outro contato. Interrompa pelo botão
INTERRUPT do Jarvis; operações locais já iniciadas podem terminar e o texto deve
ser conferido no campo. Nenhum fluxo de envio foi acrescentado.

Os testes cobrem o driver com uma interface simulada e também uma página HTML
simulada em um navegador real. Não houve login nem validação em conta real do
WhatsApp. O teste de navegador pode ser repetido localmente com:

```sh
python tests/smoke_whatsapp_browser.py
```

### Diagnóstico visual específico

As falhas visuais agora exibem um código no resultado:
`quota`, `timeout`, `access_denied`, `model_unavailable`, `cooldown`,
`invalid_json`, `empty_response`, `truncated_response` ou `blocked_response`.
A cota do Gemini Live para voz pode estar disponível enquanto a dos modelos
REST visuais não está. Uma falha visual não prova falha na voz, nem prova que
faltam créditos OpenAI. As requisições visuais pedem JSON e desativam raciocínio
extra para reduzir respostas de texto livre e esperas desnecessárias.

## Busca no WhatsApp/WhatsApp Business nativo do Windows

O fluxo Web e o aplicativo do Windows são diferentes. Para o aplicativo aberto
no Windows, o modelo agora tem `whatsapp_desktop_search`: localiza uma janela
nativa única, procura um campo de pesquisa Edit reconhecido pela acessibilidade,
confere o foco, edita esse controle e lê a consulta de volta. Navegadores são
excluídos dessa busca de janelas. Não usa captura Gemini nem coordenadas para
digitar o nome. Se o campo não for único, acessível ou editável, a ferramenta
para com o motivo correspondente, sem tentar digitar por atalhos às cegas.

Teste primeiro: “No WhatsApp Business do Windows, pesquise Vitor. Ainda não
escreva uma mensagem.” O resultado `query_verified=true` confirma somente o
texto do campo de busca. `chat_selected=false` e `draft_written=false` indicam
que localizar o contato na lista, abrir a conversa e focar o campo de mensagem
são etapas posteriores. Não deve anunciar que o rascunho está pronto por ter
pesquisado o nome. Interfaces do WhatsApp podem não expor os mesmos controles;
a operação real precisa ser conferida no Windows.

Além disso, uma falha ao localizar/clicar no alvo agora bloqueia as chamadas de
teclado genéricas seguintes até ocorrer uma nova localização/clique bem-sucedido.
Informar só o título da janela não libera o teclado após falhar em um campo.
A busca nativa também deixa esse bloqueio ativo ao terminar: o foco ainda está
na pesquisa, não no campo de mensagem. Isso evita continuar digitando o corpo
da mensagem dentro da busca. O modelo deve localizar e clicar no campo correto
antes de continuar. A proteção não comprova por si só que qualquer coordenada
escolhida pelo modelo é a correta; os resultados precisam ser verificados.

A busca nativa usa `pywinauto` e `pywin32`, já declarados nas dependências
Windows. O tempo de espera do chamador é de 8 segundos. Uma chamada de
acessibilidade do sistema pode levar mais tempo para retornar; nesse caso a
interrupção é sinalizada e a ferramenta não afirma que a busca foi concluída.
O botão INTERRUPT também solicita o cancelamento dessa busca. Testes usam
controles simulados; não houve validação numa instalação real do WhatsApp
Business para esta alteração.

### Precisão da captura e dos cliques

As tarefas visuais e a localização de controles agora recortam a janela ativa
no Windows antes de enviar a imagem ao Gemini. O recorte preserva a transformação
entre pixels da captura e coordenadas do mouse, inclusive quando as resoluções
diferem. As tarefas usam imagens de até 1920 × 1200 com maior qualidade.
Se a janela mudar de posição/tamanho durante a análise, o clique visual é descartado.
A localização direta também compara o alvo com uma captura recente antes de retornar.

Esta implementação ainda captura apenas o monitor principal. Mantenha o aplicativo
inteiro nele e evite mover a janela durante a tarefa. Não garante reconhecimento
correto de todo botão e não foi validada em um WhatsApp real no Windows.
Para investigar falhas persistentes, informe o comando exato, a escala de exibição
do Windows, a quantidade de monitores e envie uma captura com dados pessoais ocultos.
Para redigir mensagens no WhatsApp Web, prefira a ação `whatsapp_draft`, que usa
os elementos da página em vez de estimar cliques pela imagem. Ela não atende o
aplicativo WhatsApp do Windows; a busca nativa nele continua sendo uma ação separada.

### Restaurar aplicativos minimizados no Windows

`open_app` e `computer_control` com `action=focus_window` agora compartilham a
ativação nativa, com identificadores compatíveis com Windows de 64 bits.
A restauração aguarda até 1,2 segundo para confirmar que a janela deixou de
estar minimizada e está realmente em primeiro plano. O retorno da chamada de
ativação sozinho não conta como sucesso. O assistente é orientado a restaurar
a janela antes da análise visual, sem tentar adivinhar ícones da barra de tarefas.
Se houver várias janelas com o título solicitado, informe o título completo.
O Windows ainda pode recusar a ativação; nesse caso, o resultado é falha.
Essa alteração foi validada com testes simulados, sem acesso ao Windows do usuário.

### Alternativa visual para restauração

No Windows, se a ativação nativa falhar, `focus_window` tenta localizar o aplicativo
na barra de tarefas. `open_app` também usa essa alternativa quando encontra um
aplicativo já em execução, mas não consegue trazê-lo à frente pelo sistema.
A alternativa permite até seis ações (clique, passar o mouse ou aguardar),
com nova observação entre elas. Pode revelar a barra oculta e miniaturas de
janelas agrupadas. A captura inclui o monitor principal inteiro, não apenas a
janela ativa. Não inicia outro aplicativo nem digita durante a restauração.

O reconhecimento depende da disponibilidade e da cota visual do Gemini.
Ícones sem identificação suficiente e janelas ambíguas causam uma pausa.
A conclusão exige também uma janela correspondente, única e não minimizada em
primeiro plano, verificada pelo Windows. O destaque do ícone sozinho não basta.
O fail-safe continua ativo e movimentos aos cantos são rejeitados.
A interrupção do comando cancela também a alternativa visual.
Essa integração foi testada com simulações; ainda requer validação no Windows
real, inclusive para a disposição específica da barra de tarefas do usuário.

### Ícones pequenos, incluindo Opera GX

A alternativa de restauração agora consulta os rótulos acessíveis dos botões
visíveis da barra de tarefas do Windows. Havendo um único nome correspondente,
propõe um clique nesse botão usando a posição informada pela acessibilidade,
sem depender do reconhecimento visual do logo. O alvo ainda é comparado com
uma captura recente antes do clique, e o resultado exige confirmação da janela.
Os nomes preservam variantes: `Opera GX` não é tratado como `Opera`.

Se não houver um rótulo único, o fluxo continua pela imagem e pelas miniaturas.
Uma análise visual incerta recebe uma tentativa com o modelo visual mais forte
antes de pedir intervenção. A disponibilidade dos rótulos depende da versão e
configuração do Windows; não é garantida. O limite do monitor principal permanece.

O terminal mostra `[WindowRestore] fallback=taskbar_labels_then_vision` ao entrar
nesse fluxo e `taskbar_labels=... matches=...` com o resultado da consulta.
Se o problema persistir, envie essas linhas e o retorno técnico da ferramenta,
pois a frase falada pelo assistente não identifica a etapa que falhou.

### `model_unavailable` e movimento indevido para `(0, 0)`

`move`/`hover` agora resolve `description` ou exige x e y completos. Não assume
mais zero para coordenadas ausentes. Uma falha de localização bloqueia o clique
seguinte sem alvo, e coordenadas nos cantos de parada são rejeitadas antes do
PyAutoGUI. Arrastar também exige todas as coordenadas. O fail-safe continua ativo.
A consulta da barra agora inclui botões e itens de lista/aba/menu expostos pelo Windows.

Se ambos os modelos visuais padrão retornarem `model_unavailable`, na pasta do
projeto e usando o mesmo Python do Jarvis, execute:

```bat
python check_gemini_visual.py --configure
```

O diagnóstico usa a chave já configurada, consulta os modelos publicados para
ela e testa até quatro candidatos com uma imagem vermelha sintética (não envia
a tela nem conversas). Essas chamadas podem consumir cota Gemini. Salva apenas
um modelo que respondeu corretamente ao teste, preservando as outras configurações.
Reinicie o Jarvis depois. Um modelo listado não implica cota disponível; se nenhum
passar, a configuração é preservada e será necessário verificar acesso/cota/rede.
Sem `--configure`, apenas lista os candidatos. Não compartilhe sua chave.

O aviso `Revert to STA COM threading mode` não é, sozinho, uma falha de clique.
`taskbar_labels=not_found` significa que a consulta não encontrou um rótulo
correspondente; não comprova que o ícone inexiste. Use o retorno técnico completo
para distinguir isso de indisponibilidade do modelo visual.

### Gemini: prazo mínimo de 10 segundos

Alguns modelos recusam a requisição se o prazo HTTP for menor que 10 segundos.
As chamadas visuais agora respeitam esse mínimo, mantendo o orçamento total:
se não restarem 10 segundos, não enviam outra tentativa inválida. O prazo padrão
passa a 12 segundos. Uma rejeição explícita de prazo recebe `request_deadline`,
sem ser mascarada pela indisponibilidade de um modelo alternativo.
Se você já configurou `gemini-flash-lite-latest` com sucesso no diagnóstico,
basta atualizar e reiniciar o Jarvis; não é necessário repetir a configuração
por causa desse erro de prazo. O teste de configuração usava 15 segundos,
por isso podia funcionar enquanto a automação, que limitava a 6 segundos, falhava.

### Navegador já aberto: não minimizar ao procurar uma aba

Antes de ativar ou restaurar um aplicativo, o Jarvis verifica se a janela em
primeiro plano já corresponde ao pedido. A existência de outras janelas com
nomes semelhantes não invalida a janela ativa. Assim, `click` com `title=Opera GX`
pode seguir diretamente para localizar a aba descrita, sem clicar novamente
no ícone da barra de tarefas. `open_app` também aproveita a janela já ativa.

Se o Opera GX exibir somente `Opera` no título, a identificação alternativa
confere o executável `opera.exe` dentro da pasta `Opera GX` do processo proprietário
da janela. Não assume que qualquer instalação do Opera seja o GX. Se o Windows
negar acesso ao processo, essa identificação alternativa não é confirmada.
A restauração visual verifica novamente o aplicativo em primeiro plano antes
de enviar uma ação, evitando clicar na barra quando a janela já apareceu.

Testes de regressão simulam o clique na aba do Gerenciador de Anúncios com o
Opera já ativo, sem restauração intermediária. A localização real da aba continua
dependendo da análise visual e precisa ser validada na máquina do usuário.

### Continuidade e recuperação automática

Tarefas visuais agora usam até 16 entradas por padrão (máximo 24) e até cinco
minutos. A restauração da barra de tarefas mantém o limite menor de seis entradas
e dois minutos. O assistente é orientado a passar o objetivo completo ao modo
contínuo, executar as etapas autorizadas e não delegar cliques comuns ao usuário.

Quando um controle estiver oculto ou a interface ainda estiver carregando, o
planejador pode escolher menus visíveis, passar o mouse, rolar o painel adequado
ou aguardar. Cada entrada ainda exige uma nova observação. Um bloqueio recuperável
recebe até duas novas análises com instruções para mudar a abordagem; o orçamento
global de recuperação é de quatro tentativas por tarefa. Uma falha visual
transitória recebe uma nova tentativa, sem repetir entradas já enviadas. Erros
de cota, acesso ou modelo indisponível não recebem repetição automática.

A recuperação recebe o histórico e a razão da falha. Um clique/texto/atalho já
enviado não é repetido só porque a estimativa da caixa ou confiança mudou.
Se o mesmo comando reaparecer, o planejador deve verificar o efeito ou escolher
outro caminho. Ao esgotar as recuperações, informa a falha, sem inventar sucesso.

Ainda pede informação quando faltarem dados indispensáveis, houver alvos que
não possam ser distinguidos, autenticação/2FA/CAPTCHA ou permissão do sistema.
Uma ordem como "não enviar" continua válida em todas as etapas. O usuário pode
interromper a execução e o fail-safe do mouse permanece ativo. As recuperações
podem consumir chamadas Gemini adicionais. A validação automatizada usa cenários
simulados; não garante que qualquer interface possa ser concluída sem intervenção.

### Sequências até terminar e painel do desktop

Esta versão substitui o teto anterior de 24 ações/cinco minutos: tarefas normais
continuam até o resultado ser confirmado, surgir um impedimento ou o usuário
interromper. `max_steps` é opcional, usado somente quando se deseja um limite
explícito. A restauração da barra de tarefas continua sendo uma operação curta,
com limite próprio; não limita a sequência de trabalho seguinte.

A proteção contra repetição permanece: dez observações consecutivas sem mudança
visual detectável encerram a tarefa com `no_progress`. Falhas recuperáveis ainda
têm tentativas limitadas, renovadas quando há mudança de tela e uma entrada bem
sucedida. Isso não garante reconhecer todo ciclo possível em páginas dinâmicas.
O histórico recente fica limitado a 64 entradas na memória de trabalho, e um
resumo de progresso acompanha as observações seguintes. O total de entradas
continua sendo contado mesmo depois de o histórico recente ser reduzido.

Ao executar uma sequência, o Jarvis abre automaticamente um painel compacto de
acompanhamento, recolhendo a janela principal. Também é possível abri-lo pelo
botão **Desktop ao vivo** no topo, ao lado dos controles, ou pela tecla **F8**. O painel mostra a captura do monitor principal,
o cursor e a etapa atual, atualizando a prévia duas vezes por segundo. A prévia
é local, somente leitura e não é gravada. Os cliques continuam acontecendo no
desktop real, não dentro de um computador virtual ou de uma área isolada.

No Windows compatível, o painel solicita exclusão das capturas para evitar
reflexos infinitos. Se o sistema não permitir isso, a prévia informa que está
indisponível. Antes de capturar ou enviar entradas, o painel se oculta brevemente
com confirmação da interface; depois reaparece. Não aceita cliques na imagem
como comandos. **PARAR** solicita interrupção; **Voltar ao Jarvis** interrompe uma
execução ativa e reabre a interface completa. Uma chamada Gemini já em andamento
pode levar até seu prazo para retornar, mas nenhuma nova entrada é enviada após
a interrupção ser detectada. O fail-safe do mouse continua ativo.

O painel não torna o reconhecimento visual infalível e não isola a automação
do uso manual simultâneo do computador. Se precisar usar o PC, interrompa a tarefa.
Foram verificados o painel em Qt offscreen e cenários simulados de 70 ações ao
longo de mais de cinco minutos, cancelamento e ausência de progresso. A captura
ao vivo e a exclusão da janela ainda precisam ser validadas no Windows real.

### IA acompanhando a tela por Gemini Live

O modo contínuo agora tenta usar uma sessão Gemini Live dedicada à tarefa,
com até um quadro por segundo do monitor principal. Não é uma gravação enviada
como arquivo: os quadros são transmitidos pela entrada de vídeo em tempo real,
sem fila de imagens acumuladas. A sessão permanece aberta entre as etapas e
é fechada quando a tarefa termina ou é interrompida. Não envia microfone nessa
sessão auxiliar, nem armazena vídeo em disco.

A sessão auxiliar é necessária porque a sessão principal de voz aguarda o retorno
da ferramenta de tarefa longa. O modo usa a chave e o modelo Live já configurados,
e pode consumir cota de vídeo/contexto e uma conexão simultânea adicional. Não
elimina limites, bloqueios ou indisponibilidade do Gemini. Está ativo por padrão
quando há chave Gemini; `desktop_live_stream: false` no arquivo de configuração
desativa a tentativa. O modo exclusivo OpenAI não abre essa sessão Gemini.

No **Desktop ao vivo**, a linha **IA ao vivo** distingue conectando, transmitindo,
indisponível com alternativa por capturas e desligado. A prévia local continua
separada: vê-la não comprova que a IA esteja recebendo vídeo. O terminal informa
`[DesktopLive] state=live fps_max=1` depois do primeiro quadro enviado, ou
`[DesktopLive] fallback=rest ...` quando passa para capturas por etapa.

O Live acompanha o contexto, mas cada proposta deve incluir o identificador da
requisição e usar a captura de referência anexada àquela etapa. Propostas antigas,
não solicitadas ou após interrupção são ignoradas. A sessão visual não controla
mouse ou teclado diretamente: o executor local valida a janela, o alvo e a
captura antes da entrada. Controles acessíveis do Windows continuam sendo usados
quando identificam o alvo; o navegador controlado pelo Playwright mantém os
métodos por elementos da página. Isso não conecta automaticamente o Playwright
às abas de um Opera já aberto ou à conta logada nesse navegador.

Se a sessão Live não conectar, não responder com uma proposta válida ou cair,
o Jarvis tenta a análise REST com a captura de referência, uma alternativa
que também depende de acesso e cota. A sessão não é reaberta em toda etapa
após uma falha. Sem os dois métodos disponíveis, informa a falha e não clica
às cegas. **PARAR** interrompe a tarefa e encerra a transmissão.

Validação: protocolo Live simulado, sessão persistente entre requisições,
entrada de vídeo suportada pelo SDK instalado, rejeição de propostas antigas,
cancelamento, encerramento e alternativa REST. A conexão real com a chave do
usuário e o comportamento no Windows ainda precisam ser validados.

### Correções do log enviado em 26/10/2026

O ZIP atualizado enviado nesta data contém os mesmos arquivos-fonte da versão
publicada. Configurações, memória, credenciais e arquivos ZIP particulares não
foram copiados para o repositório.

- `1008 The operation was aborted`: o servidor encerrou a sessão; o log não
  informa a causa exata. A aplicação agora identifica esse erro mesmo dentro
  de um `ExceptionGroup`, descarta o identificador de retomada e reconecta com
  espera crescente, sem repetir automaticamente ações anteriores. Isso melhora
  a recuperação, mas não impede o serviço de encerrar outra conexão.
- Erros de cota/modelo dentro de grupos de exceções agora preservam a mensagem
  original para a seleção de alternativas. O diagnóstico do planejador Live
  informa o tipo da falha em vez de somente `unknown`.
- O bloqueio de teclado depois de falhar o foco foi preservado: tentar `type`
  ou `paste` repetidamente não é uma recuperação válida. Não houve confirmação
  de digitação no trecho de log enviado.
- O aviso Qt sobre clipboard, isolado, não comprova falha de colagem. Os retornos
  de ferramenta precisam ser usados para verificar se a ação ocorreu.

### Drive local: liberar uma pasta de leitura

O caminho `G:\Meu Drive\CLIENTES` era recusado pela restrição local do Jarvis,
não por um erro demonstrado na API do Google Drive. Na máquina com o Drive já
montado, execute na pasta do projeto:

```powershell
py configure_drive_access.py --folder "G:\Meu Drive\CLIENTES"
```

A pasta deve existir e estar acessível ao Windows. O comando salva uma raiz
adicional somente para listar, ler, buscar e obter informações. Não concede
permissão adicional de escrita, exclusão ou acesso ao disco inteiro. Links que
escapem da pasta não são autorizados por essa regra. Isso não corrige ausência
de montagem, arquivos indisponíveis offline ou permissões recusadas pelo Windows.

O prompt para implementar a integração OAuth/API está em
[PROMPT-INTEGRACAO-GOOGLE-DRIVE.md](PROMPT-INTEGRACAO-GOOGLE-DRIVE.md).
Nesta alteração foi preparado o prompt e o acesso local configurável, não uma
nova conexão OAuth ao Drive. As credenciais do Google Agenda permanecem separadas.

### Indicador ao minimizar

Ao minimizar a janela principal, aparece um pequeno indicador no canto inferior
direito do monitor principal. Verde significa conexão estabelecida; amarelo,
conectando/reconectando. Ele não garante que todos os modelos tenham cota ou que
as tarefas possam ser concluídas. Clicar no indicador restaura a janela.
Durante capturas e entradas, ele se oculta para não se tornar um obstáculo.
Não aparece junto do monitor de tarefas como se a janela principal estivesse
minimizada: o monitor já tem seu próprio acompanhamento.

Verificados classificação de erros aninhados, autorização local somente leitura,
bloqueio de escape por link, e minimizar/ocultar/restaurar na interface Qt offscreen.
A conexão real Gemini e o Drive montado do usuário ainda exigem teste no Windows.

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

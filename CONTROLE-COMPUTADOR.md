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

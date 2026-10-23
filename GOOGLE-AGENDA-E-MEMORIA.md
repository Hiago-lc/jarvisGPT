# Nova base: velocidade, Google Agenda e memória persistente

O código foi atualizado a partir do ZIP enviado. Seus arquivos privados
`config/api_keys.json` e `memory/long_term.json` não fazem parte do GitHub.
Mantenha os originais em seu computador. A integração principal continua Gemini.

## Atualizar

Feche o Jarvis. Faça uma cópia da pasta antiga antes de substituir os arquivos.
Na pasta atualizada, com seu ambiente virtual ativo:

```sh
python -m pip install -r requirements.txt
python start_gemini.py
```

Se você extrair em uma pasta nova, copie também o `config/api_keys.json` antigo
para a nova pasta `config`, sem publicá-lo, para preservar sua chave Gemini.
Veja abaixo como importar a memória antiga. Python 3.11 ou 3.12 é o ambiente
usado para desenvolvimento; a validação desta atualização usou Python 3.12.

## Ações contínuas mais rápidas

A mesma consulta ao Gemini agora escolhe a próxima ação E a caixa do alvo na
captura. O executor usa essa localização validada ou um controle nativo do
Windows, evitando a segunda consulta visual por clique. As capturas usam JPEG;
a pausa fixa entre ações caiu de 600 ms para 150 ms. Textos longos usam colagem
quando a área de transferência está disponível. A tela ainda é observada após
cada ação: não se executa uma sequência de cliques sem verificar seu estado.

Se o alvo visual mudar durante a consulta, o clique não é enviado; até duas
novas observações são permitidas dentro do limite da tarefa. Se o alvo vier
incerto, a nova observação usa a faixa SMART do Gemini, mantendo o caminho
rápido para as etapas comuns. Mudança da janela
ativa interrompe a entrada. Alvos incertos não são clicados. A imagem continua
limitada ao monitor principal. A diferença de imagem é uma heurística, não uma
garantia de que todo clique será correto. A rede, a cota e o modelo Gemini ainda
influenciam a velocidade; não há promessa de resposta instantânea.

Peça: “Na página aberta, procure o cliente Aurora, abra o cadastro e preencha
o campo observação com o texto que vou informar.” A ferramenta screen_task
mantém o limite de 12 etapas/2 minutos. Interrompa pelo botão INTERRUPT ou por
Esc com a janela do Jarvis em foco. Acompanhe operações no computador.

## Conectar Google Agenda

A integração cria **eventos com horário** na agenda, em vez de clicar no site.
Isso não cria as tarefas com caixinha de concluir do produto Google Tasks.
Não é necessário crédito OpenAI. É necessária uma conta Google com acesso à
agenda e um cliente OAuth criado por você (ou pelo administrador do trabalho).

1. Em https://console.cloud.google.com/, crie/selecione um projeto.
2. Em APIs e serviços, habilite **Google Calendar API**.
3. Configure o consentimento OAuth. Se o aplicativo estiver em teste e for
   externo, adicione sua conta como usuário de teste. No Google Workspace,
   políticas da empresa podem exigir liberação do administrador.
4. Crie uma credencial OAuth do tipo **Aplicativo para computador/Desktop app**.
   Baixe o JSON e guarde fora da pasta pública do projeto.
5. No seu computador, execute:

```powershell
python connect_google_calendar.py --client "C:\caminho\client_secret.json"
```

O navegador abrirá o consentimento Google e retornará ao listener local do
Jarvis. Nunca envie esse JSON, tokens, senhas ou chaves em chats ou no GitHub.
O acesso solicitado é `calendar.events`; não inclui Gmail nem contatos.
O token é guardado somente na pasta de dados do usuário. A biblioteca renova o
acesso quando permitido. Autorizações revogadas ou de aplicativos em teste
podem exigir reconexão. Para remover a autorização local:

```sh
python connect_google_calendar.py --disconnect
```

Revogue também o acesso no painel de segurança da conta Google se desejar.

Inicie o Jarvis e peça, por exemplo:

> “Crie no meu Google Agenda uma reunião de planejamento amanhã, das 9h às 9h30.”
> “Quais compromissos tenho amanhã?”

O padrão é a agenda principal da conta autorizada, no fuso America/Sao_Paulo.
Outra agenda pode ser especificada pelo seu ID e precisa permitir escrita para
a conta conectada. O modelo deve perguntar se faltar data, horário ou duração.
Datas enviadas à API precisam conter deslocamento de fuso. Criações com os
mesmos dados geram o mesmo ID para evitar duplicação após tentativas de rede.
A ferramenta não envia convites a convidados, não exclui nem edita eventos.
Não há conexão real até você concluir o consentimento no seu navegador.

## Memória que acompanha as atualizações

No Windows, os dados ficam em `%LOCALAPPDATA%\JarvisGPT`.
No macOS, em `~/Library/Application Support/JarvisGPT`; no Linux, no diretório
XDG de dados (`~/.local/share/jarvisgpt` por padrão). A variável `JARVIS_DATA_DIR`
permite escolher outra pasta persistente. Não use uma pasta temporária.

Na primeira execução, se não existir memória persistente, o arquivo antigo
`memory/long_term.json` da pasta atual é copiado, sem apagar o original. Se você
baixou o novo código para outra pasta, importe o arquivo da instalação antiga:

```powershell
python manage_memory.py import "C:\Jarvis-antigo\memory\long_term.json"
python manage_memory.py status
```

A importação adiciona entradas ausentes e preserva os valores que já existem.
A gravação usa arquivo temporário, substituição atômica, backup da versão
anterior e bloqueio de gravações entre threads/processos. Um arquivo danificado
não é substituído silenciosamente por memória vazia. Um backup válido pode
recuperar a versão anterior; isso não equivale a recuperar toda escrita perdida.

Fatos não são apagados nem encurtados para caber no prompt. Resumos antigos
continuam guardados depois do briefing. Novas falas concluídas e comandos de
texto são registrados em `conversations.db`; o contexto recente é carregado no
reinício e o restante pode ser consultado por `recall_memory`. Isso não recupera
conversas que versões anteriores nunca gravaram, nem áudio interrompido antes
de ser transcrito. O conteúdo relevante é enviado ao Gemini para responder.

Para gerar um backup local de fatos e conversas (sem chaves nem tokens Google):

```sh
python manage_memory.py export "backup-jarvis.zip"
```

Guarde o ZIP em local privado. Para restauração manual, com o Jarvis fechado,
extraia `long_term.json` para `<pasta de dados>/memory/` e `conversations.db` para
`<pasta de dados>/`, preservando antes uma cópia dos arquivos atuais. Para mesclar
só os fatos, use o comando import no JSON do backup. Não substitua um banco
SQLite enquanto o aplicativo estiver aberto. Apagar um fato no painel não
remove sua menção de conversas antigas nem de backups.

Persistência não é armazenamento infalível: mantenha backups fora do disco do
computador. Disco cheio, remoção manual da pasta e falhas físicas ainda podem
causar perda. Os testes desta versão simulam Gemini, mouse, Windows e Google
Calendar; a conta Google e a precisão na sua tela exigem validação local.

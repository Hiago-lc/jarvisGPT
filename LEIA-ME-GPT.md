# Jarvis com OpenAI e histórico do ChatGPT

Esta versão aproveita as ferramentas, confirmações e memória existentes do projeto.
O novo inicializador escolhe GPT para conversa e tarefas auxiliares, Whisper da
OpenAI para ouvir e a voz do sistema para falar. Não usa Gemini como fallback.
O SDK Google continua instalado porque o aplicativo usa seus tipos internamente;
isso não significa que o inicializador envie requisições ao Gemini.

## Instalar no computador que o Jarvis vai controlar

Use Python 3.11 ou 3.12 e um ambiente virtual:

```sh
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
```

Configure OPENAI_API_KEY no ambiente, sem enviar a chave no chat nem incluí-la
no código. No PowerShell, para pedir a chave sem exibi-la:

```powershell
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'Chave OpenAI' -AsSecureString)).Password
python start_openai.py
```

No Linux/macOS com Bash:

```bash
read -rs -p 'Chave OpenAI: ' OPENAI_API_KEY; echo
export OPENAI_API_KEY
python start_openai.py
```

O modelo padrão é `gpt-4.1`; altere com a variável `JARVIS_OPENAI_MODEL`
para outro modelo disponível na sua conta que aceite Chat Completions, imagens
 e chamadas de ferramentas. A chave é injetada em memória; o inicializador
salva apenas a seleção de provedores. Não salve a chave pelo painel se quiser
mantê-la somente no ambiente. Inicie sempre por `start_openai.py`.

O uso da API é cobrado separadamente da assinatura do ChatGPT.
Áudio e contexto necessário para responder são enviados à OpenAI.
Para fala no Linux, instale também a voz do sistema `espeak-ng`.
O Jarvis precisa rodar na máquina que controla, com acesso a microfone,
saída de som, captura de tela e permissões de acessibilidade do sistema.

## Aproveitar trabalho anterior no ChatGPT

A API não herda automaticamente conversas, memória, Projetos, arquivos,
instruções de GPTs personalizados nem conexões da conta ChatGPT.
Exporte seus dados pelas configurações do ChatGPT e importe o ZIP recebido
ou o arquivo `conversations.json`:

```sh
python -m memory.chatgpt_history /caminho/exportacao.zip
```

Depois diga ao Jarvis, por exemplo: "Busque no meu histórico do ChatGPT o
projeto de automação que estávamos fazendo". A ferramenta
`search_chatgpt_history` pesquisa os textos importados localmente e envia
somente os trechos encontrados como resultado para o modelo. O histórico
não é todo colocado em cada pedido. É uma busca por palavras, não uma
sincronização contínua; exporte e importe novamente para atualizar.

O banco fica em `memory/chatgpt_history.db` (ignorado pelo Git). Para apagar
esse contexto, feche o Jarvis e remova esse arquivo. Conversas removidas de
uma exportação anterior continuam no banco até você apagá-lo e reimportar.
Arquivos anexados, imagens e conteúdo não textual não são importados.
Documentos, instruções pessoais e arquivos de Projetos precisam ser
transferidos separadamente e podem ser lidos pelas ferramentas já existentes.
Trechos históricos são dados de referência e não autorização para ações.

## Verificação

```sh
python -m unittest discover -s tests -v
python -m providers._tests
```

Os testes locais não consomem créditos nem demonstram acesso à sua conta.
A integração real exige uma chave válida, créditos de API e desktop disponível.
Recursos específicos do Gemini, como busca com grounding do Google, não são
convertidos em recursos OpenAI por este inicializador; a busca web existente
pode usar o fallback do projeto. Não há promessa de compatibilidade integral
com todos os recursos do Gemini Live.

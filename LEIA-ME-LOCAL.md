# Jarvis sem API de créditos

`start_local.py` inicia o Jarvis sem chamar o Gemini nem a OpenAI. Há dois perfis:

| Perfil | Ouve | Pensa | Fala | Custo | Internet |
| --- | --- | --- | --- | --- | --- |
| `local` (padrão) | Whisper no seu PC | Ollama no seu PC | Piper pt-BR | zero | não precisa |
| `hibrido` | Whisper do Groq | Modelo grande no Groq | Piper pt-BR | zero (plano gratuito, com limite diário) | precisa |

Mesmo com uma chave Gemini antiga salva, nenhum dos dois perfis faz pedidos ao Gemini.

## O que esperar no seu PC (RX 580 4 GB, 16 GB de RAM, Ryzen 5 5600G)

- **Perfil local**: usa o `qwen3:4b-instruct-2507-q4_K_M` (cerca de 2,5 GB), que cabe inteiro na placa. Ele chama ferramentas bem para o tamanho, mas é um modelo pequeno: acerta comandos diretos ("abre o Chrome", "lembra de mim às 15h"), mas se perde em tarefas longas.
- **Perfil híbrido**: usa um modelo de 120B no Groq, muito mais inteligente e rápido que qualquer modelo que caiba nesta placa. É o perfil recomendado para o dia a dia até trocar de placa de vídeo.
- **Geração de imagem local** (ComfyUI/FLUX) não é viável com 4 GB. Fica para depois de um upgrade de GPU.

## Instalação (uma vez)

Com o ambiente virtual do projeto ativo:

```powershell
python -m pip install -r requirements.txt
python -m pip install faster-whisper piper-tts
```

### Perfil local: Ollama

1. Instale o Ollama em https://ollama.com (use a versão mais recente: o suporte a placas AMD antigas como a RX 580 vem pelo Vulkan).
2. O contexto é ajustado sozinho. As instruções e ferramentas do Jarvis passam de 7 mil tokens, e o Ollama abre modelos com 4 mil. Na primeira vez, o `start_local.py` cria um modelo derivado (`jarvis-…-12k`) com 12 mil tokens de contexto. Para mudar o tamanho: `$env:JARVIS_CONTEXT = "16384"`.
3. Baixe o modelo base:

   ```powershell
   ollama pull qwen3:4b-instruct-2507-q4_K_M
   ```

4. Confira se a placa está sendo usada: rode `ollama run qwen3:4b-instruct-2507-q4_K_M "oi"` e, em outro terminal, `ollama ps`. A coluna PROCESSOR deve mostrar `GPU`. Se mostrar `100% CPU`, rode `setx OLLAMA_VULKAN 1`, reinicie o Ollama e confira de novo. Na CPU ele funciona, só que mais devagar.

Se o nome do modelo não existir na sua versão do Ollama, `qwen3:4b` também serve (é mais lento para começar a responder, porque "pensa" antes).

### Perfil híbrido: Groq gratuito

1. Crie uma chave em https://console.groq.com/keys (o plano gratuito não pede cartão).
2. Defina a chave só na sessão, sem salvar em arquivo:

   ```powershell
   $env:GROQ_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'Chave Groq' -AsSecureString)).Password
   ```

## Iniciar

```powershell
python start_local.py --verificar             # confere tudo e diz o que falta
python start_local.py                         # perfil local
python start_local.py --perfil hibrido        # Groq gratuito + voz local
python start_local.py --modelo qwen3:8b       # outro modelo do Ollama
```

Na primeira fala, o Piper baixa a voz `pt_BR-faber-medium` (cerca de 60 MB). Para voltar ao Gemini: `python start_gemini.py`.

Variáveis opcionais: `JARVIS_LOCAL_MODEL`, `JARVIS_GROQ_MODEL` (padrão `openai/gpt-oss-120b`), `JARVIS_PIPER_VOICE`, `JARVIS_WHISPER_MODEL` (padrão `small`; use `base` se a transcrição estiver lenta).

## O que muda em relação ao Gemini

- A conversa é ouvir → pensar → falar em sequência, então há uma pausa antes da resposta, maior no perfil local.
- **Visão de tela**: o modelo local não enxerga imagens. Clicar em um elemento pelo nome usa primeiro a árvore de acessibilidade do Windows, que não precisa de IA, e funciona na maioria dos apps. O planejador contínuo de tela fica desligado nestes perfis.
- **Pesquisa web** usa o DuckDuckGo, sem as fontes citadas que o Gemini dava.

## O que foi alterado no código

- `start_local.py`: novo inicializador, com verificação em português.
- `core/gemini.py`: `gemini_disabled()` reúne os dois interruptores (`JARVIS_NO_GEMINI` e o antigo `JARVIS_OPENAI_ONLY`).
- `actions/computer_control.py`: localizar um elemento na tela não exige mais a chave Gemini antes de tentar a árvore de acessibilidade.
- `providers/llm_openai.py` e `providers/engine_pipeline.py`: o modelo pode limitar o histórico da conversa (`history_chars`), para caber em contextos curtos.
- `tests/test_local_setup.py`: 15 testes, incluindo garantir que nenhuma chamada chega ao Gemini e que a chave do Groq nunca é gravada no disco.

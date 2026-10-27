# Jarvis web: no PC e no celular

O Jarvis agora mora dentro da central da HAIZEN. Você conversa por texto ou voz, e ele consulta o faturamento, cria tarefas, aciona os agentes e mexe no PC. Funciona no navegador do PC e no celular, e dá para instalar como app nos dois.

O cérebro continua no seu PC: modelo, voz, agentes, arquivos e controle do computador. Por isso o PC precisa estar ligado para o celular funcionar.

## Iniciar

```powershell
py jarvis_web.py                    # modelo local
py jarvis_web.py --perfil gemini    # Gemini gratuito + voz local (mais rápido nesta placa)
py jarvis_web.py --perfil hibrido   # Groq gratuito + voz local
```

O perfil `gemini` usa a chave do Gemini que você já salvou no Jarvis (ou `GEMINI_API_KEY`). Ele só é gratuito se o projeto da chave **não tiver cobrança ativada**: confira em https://aistudio.google.com/apikey se o plano aparece como "Free". No plano gratuito não há crédito, só um limite de pedidos por minuto e por dia.

O navegador abre na tela **Jarvis**. A janela antiga, com o avatar, não abre, e isso economiza memória. Ela continua disponível com `py start_local.py`, se você quiser.

Para o perfil `hibrido` iniciar sozinho, a chave do Groq precisa estar salva no Windows (uma vez): `setx GROQ_API_KEY "sua-chave"`. Depois, abra um PowerShell novo. O perfil `gemini` não precisa disso se a chave já estiver salva no Jarvis.

## Iniciar junto com o Windows

```powershell
py jarvis_web.py --perfil hibrido --iniciar-com-windows
```

Para desfazer: `py jarvis_web.py --nao-iniciar-com-windows`. Sem janela, as mensagens do Jarvis vão para `%LOCALAPPDATA%\JarvisGPT\jarvis_web.log`.

## No celular (Tailscale)

1. Instale o **Tailscale** no PC e no celular (https://tailscale.com/download) e entre com a **mesma conta** nos dois. É gratuito para uso pessoal.
2. No PC, uma vez:
   ```powershell
   py jarvis_web.py --tailscale
   ```
   Ele mostra um endereço como `https://seu-pc.tailXXXX.ts.net`.
3. No celular, com o Tailscale ligado, abra esse endereço.
4. Instale como app:
   - Android (Chrome): menu ⋮ → **Adicionar à tela inicial** ou **Instalar app**.
   - iPhone (Safari): botão compartilhar → **Adicionar à Tela de Início**.

O endereço só abre nos aparelhos da sua conta Tailscale. Ninguém de fora enxerga a central, e nenhuma porta do roteador é aberta.

No PC, o app também pode ser instalado: no Chrome ou no Edge, abra `http://127.0.0.1:8765` e clique no ícone de instalar, na barra de endereço.

## Voz

- Toque em **Falar**, diga o que quer e toque de novo para enviar. O áudio vai para o seu PC, onde o Whisper transcreve.
- Com **Responder em voz** marcado, a resposta toca com a voz do Piper.
- No celular, o microfone só funciona pelo endereço `https://...ts.net`, porque o navegador exige HTTPS.

## O que o Jarvis web faz

| Pedido | Exemplo |
| --- | --- |
| Financeiro e central | "Quanto recebi este mês?", "Registre uma despesa de R$ 80 da Adobe, paga hoje" |
| Tarefas | "Quais tarefas estão atrasadas?", "Conclui a tarefa do cardápio" |
| Agentes | "Pede ao comercial uma proposta de site para a Padaria Sol" |
| PC | "Abre o Spotify", "Aumenta o volume", "Me lembra às 15h de ligar para o cliente" |
| Pesquisa e clima | "Pesquisa o preço do domínio .com.br", "Vai chover amanhã?" |
| Memória | "Lembra que eu prefiro reuniões à tarde" |

Ações irreversíveis no PC, como desligar ou apagar arquivos, aparecem como um aviso **Confirmar no PC** na tela do Jarvis. Nada acontece sem o seu clique.

Ficaram de fora da web, de propósito, as ações que dependem de ver a tela e clicar por você: pelo celular você não está vendo o PC, e um clique às cegas é arriscado. Para essas, use a janela antiga.

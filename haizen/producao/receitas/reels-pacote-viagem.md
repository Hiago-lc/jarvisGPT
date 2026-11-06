---
nome: Reels de pacote de viagem
descricao: Vídeo vertical 1080x1920 de 30 a 40 s vendendo um pacote ou excursão (destino, datas, chamada para o WhatsApp), com as filmagens do cliente.
---
# Receita: reels de pacote de viagem

Feita a partir de um vídeo que o dono da HAIZEN aprovou como "exatamente o que pedi".
Use como ponto de partida; o pedido e o guia da marca mandam.

## O que entregar
- `Reels - <destino>.mp4`: 1080x1920, 30 a 40 s, 30 fps, H.264.
- `Roteiro - <destino>.txt`: cenas com tempos, textos na tela e a legenda do post (com hashtags e a chamada).
- `fontes/`: os HTMLs das vinhetas e a lista de clipes usados (para ajustes).
- `Capa - <destino> 1080x1920.png`: o quadro mais forte, para a capa do reels.

## Estrutura (cerca de 37 s)
1. **0–3 s, gancho**: a filmagem mais bonita do destino (água, praia, vista aérea) com o NOME DO DESTINO
   grande, animado entrando de baixo com leve escala. Nada de logo aqui.
2. **3–8 s, quando**: as datas da viagem num selo ou faixa ("12 a 16 de novembro"), sobre outro clipe.
3. **8–25 s, a experiência**: 4 a 6 clipes curtos (2–4 s cada) de passeios, hotel, ônibus, grupo se
   divertindo. Um texto curto por bloco, no máximo 5 palavras ("Sol, praia e diversão!").
   O que está incluso (hospedagem, transporte, café) em selos pequenos, se o pedido trouxer.
4. **25–31 s, urgência**: "Últimas vagas" (ou o gatilho do pedido) com destaque na cor de ação da marca.
5. **31–37 s, chamada + assinatura**: pílula do WhatsApp com o ícone e o número, e o cartão final com o
   logo do cliente centralizado sobre a cor da marca, telefone e @ do Instagram abaixo.

## Como montar
- Rode `inventario` na pasta do cliente e escolha os clipes pela qualidade (luz, estabilidade, sem pessoas
  de costas tapando a cena). Corte trechos com `video --max-clipe 3`.
- Vinhetas e textos: um HTML por cena, com animação CSS, fundo transparente quando for sobreposição,
  exportado com `animar`. Fontes e cores do manual/guia da marca; sem manual, tire as cores do logo com `cores`.
- Texto sempre na área segura: nada nos 250 px de cima nem nos 350 px de baixo (interface do Instagram).
- Contraste: sombra suave ou faixa semitransparente atrás do texto sobre vídeo claro.
- Transições simples (corte seco no ritmo ou fade de 0,3 s). Nada de efeitos chamativos.
- Música: só a que estiver na pasta do cliente. Sem música, entregue sem áudio e avise em Pendências.
- Confira antes de entregar: extraia quadros em 2 s, 6 s, 15 s, 28 s e 35 s com o ffmpeg e abra cada um.

## Nunca invente
Preço, datas, número de vagas, o que está incluso e o telefone vêm do pedido ou do material do cliente.
O que faltar vai em Pendências, com o espaço reservado no vídeo.

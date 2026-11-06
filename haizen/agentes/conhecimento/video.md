# Conhecimento sênior: vídeo curto e motion design

## Estrutura de reels que retém
- 0–1,5 s GANCHO: movimento + texto grande com a promessa ou a dor. Nunca abra com logo.
- 1,5–3 s: confirma o gancho (o "porquê ficar").
- Corpo: um ponto a cada 2–3 s; mude o quadro (corte, zoom, texto novo) pelo menos a cada 2 s.
- Fim: CTA claro por 2–3 s + logo discreto. Duração ideal 12–30 s para anúncio, até 45 s para conteúdo.
- Pense em loop: o último quadro conversando com o primeiro aumenta replays.

## Motion design
- Animações com GSAP (carregue de https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js) ou CSS @keyframes.
  Monte UMA timeline e exponha-a: `window.timeline = gsap.timeline()`; a ferramenta `animar` controla o tempo quadro a quadro.
- Easing: entradas com `power3.out`/`expo.out`, saídas `power2.in`; nada linear em texto. Duração de entrada 0,4–0,7 s.
- Texto: revele por palavra ou linha (stagger 0,05–0,08 s), máscaras e deslizes curtos (20–40 px), não giros nem quicadas.
- Kinetic typography: palavra-chave maior e na cor de destaque; no máximo 3–5 palavras na tela por vez.
- Movimento de câmera em fotos: Ken Burns lento (escala 1 → 1,08 em 3 s) e paralaxe leve entre camadas.
- Transições: corte seco no ritmo da música > transição chamativa. Use whip/zoom só para marcar virada de assunto.

## Áudio e legenda
- 85% assistem sem som: legenda queimada sempre (use a ferramenta `legendar`), 2 linhas no máximo, fonte bold, contorno ou caixa.
- Legenda dentro da zona segura (acima dos 350 px de baixo). Destaque a palavra-chave em cor.
- Música: só a da pasta do cliente ou trilha livre que ele forneceu; volume da música −18 a −22 dB sob voz.
- Efeitos sonoros (whoosh, pop, click) sublinhando entradas de texto, se houver arquivos de som disponíveis.

## Técnica
- 1080x1920, 30 fps, H.264, yuv420p, AAC 128k, faststart. Peso < 30 MB.
- Extraia quadros (`quadros`) do gancho, meio e fim e confira: texto legível? cortado? zona segura?

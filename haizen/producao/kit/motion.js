/* HAIZEN motion: animações de vídeo com a Web Animations API (sem internet, quadro a quadro exato).
   A ferramenta `animar` controla o relógio de TODAS as animações da página, então o tempo é o tempo do vídeo.
   Todos os tempos em segundos. Uso:
     M.palavras("#titulo", 0.4)            // revela palavra por palavra (máscara de baixo para cima)
     M.entrar("#cta", 2.2, { de: "baixo" }) // entra deslizando (baixo|cima|esquerda|direita|zoom|nada)
     M.sair("#cena1", 3.8)                  // sai (para trocar de cena)
     M.kenburns("#foto", 0, 4, 1.12)        // zoom lento na foto
     M.contador("#num", 1.0, 1.4, 0, 212, "+", "%")  // número subindo
     M.destaque("#palavra", 1.6)            // marca-texto passando atrás da palavra
     M.pulso("#cta", 3.0)                    // chama atenção no CTA
   Easing padrão: expo/quart out (entradas rápidas que assentam suave). */
(function () {
  const E = { saida: "cubic-bezier(.7,0,.84,0)", entrada: "cubic-bezier(.16,1,.3,1)", suave: "cubic-bezier(.65,0,.35,1)" };
  const $ = (s) => (typeof s === "string" ? document.querySelector(s) : s);
  const ms = (s) => Math.round(s * 1000);
  const anim = (el, quadros, inicio, dur, easing = E.entrada) =>
    el.animate(quadros, { delay: ms(inicio), duration: ms(dur), easing, fill: "both" });
  const DESLOC = { baixo: "translateY(60px)", cima: "translateY(-60px)", esquerda: "translateX(-80px)", direita: "translateX(80px)",
    zoom: "scale(.86)", nada: "none" };
  const contadores = [];
  const M = {
    E,
    entrar(sel, inicio, { de = "baixo", dur = 0.7, desfoque = true } = {}) {
      const el = $(sel); if (!el) return;
      return anim(el, [{ opacity: 0, transform: DESLOC[de], filter: desfoque ? "blur(8px)" : "none" },
                       { opacity: 1, transform: "none", filter: "blur(0)" }], inicio, dur);
    },
    sair(sel, inicio, { para = "cima", dur = 0.45 } = {}) {
      const el = $(sel); if (!el) return;
      return anim(el, [{ opacity: 1, transform: "none" }, { opacity: 0, transform: DESLOC[para] }], inicio, dur, E.saida);
    },
    palavras(sel, inicio, { intervalo = 0.07, dur = 0.65 } = {}) {
      const el = $(sel); if (!el) return;
      // Texto vira palavras; elementos internos (ex.: <span id="destaque">) entram inteiros e mantêm o id.
      const pedacos = [];
      [...el.childNodes].forEach((n) => {
        if (n.nodeType === 3) n.textContent.split(/\s+/).filter(Boolean).forEach((w) => pedacos.push(document.createTextNode(w)));
        else pedacos.push(n);
      });
      el.textContent = "";
      const unidades = pedacos.map((n, i) => {
        const mask = document.createElement("span"); mask.className = "m-mask";
        const p = document.createElement("span"); p.className = "m-p"; p.appendChild(n); mask.appendChild(p);
        el.appendChild(mask); if (i < pedacos.length - 1) el.appendChild(document.createTextNode(" "));
        return p;
      });
      unidades.forEach((p, i) =>
        anim(p, [{ transform: "translateY(105%) rotate(4deg)" }, { transform: "none" }], inicio + i * intervalo, dur));
      return inicio + unidades.length * intervalo + dur;
    },
    letras(sel, inicio, { intervalo = 0.03, dur = 0.5 } = {}) {
      const el = $(sel); if (!el) return;
      const t = el.textContent; el.innerHTML = [...t].map((c) => `<span class="m-l">${c === " " ? "&nbsp;" : c}</span>`).join("");
      el.querySelectorAll(".m-l").forEach((l, i) =>
        anim(l, [{ opacity: 0, transform: "translateY(40%) scale(.9)" }, { opacity: 1, transform: "none" }], inicio + i * intervalo, dur));
    },
    kenburns(sel, inicio, dur, escala = 1.1, { x = 0, y = 0 } = {}) {
      const el = $(sel); if (!el) return;
      return anim(el, [{ transform: "scale(1)" }, { transform: `scale(${escala}) translate(${x}%, ${y}%)` }], inicio, dur, "linear");
    },
    mascara(sel, inicio, { dur = 0.9, de = "baixo" } = {}) {
      const el = $(sel); if (!el) return;
      const ini = { baixo: "inset(100% 0 0 0)", cima: "inset(0 0 100% 0)", esquerda: "inset(0 100% 0 0)", direita: "inset(0 0 0 100%)" }[de];
      return anim(el, [{ clipPath: ini }, { clipPath: "inset(0 0 0 0)" }], inicio, dur, E.suave);
    },
    destaque(sel, inicio, { dur = 0.5, cor = "var(--destaque)", texto = "var(--fundo)" } = {}) {
      const el = $(sel); if (!el) return;
      el.style.backgroundImage = `linear-gradient(${cor}, ${cor})`; el.style.backgroundRepeat = "no-repeat";
      el.style.backgroundPosition = "0 60%"; el.style.padding = "0 .1em"; el.style.borderRadius = ".08em";
      el.style.boxDecorationBreak = el.style.webkitBoxDecorationBreak = "clone";
      return anim(el, [{ backgroundSize: "0% 86%" }, { backgroundSize: "100% 86%", color: texto }], inicio, dur, E.suave);
    },
    pulso(sel, inicio, { vezes = 2 } = {}) {
      const el = $(sel); if (!el) return;
      return el.animate([{ transform: "scale(1)" }, { transform: "scale(1.06)" }, { transform: "scale(1)" }],
        { delay: ms(inicio), duration: 700, iterations: vezes, easing: E.suave, fill: "both" });
    },
    contador(sel, inicio, dur, de, ate, antes = "", depois = "", casas = 0) {
      const el = $(sel); if (!el) return;
      contadores.push({ el, inicio, dur, de, ate, antes, depois, casas });
      el.textContent = antes + de + depois;
    },
    trocar(cenaSai, cenaEntra, t, { dur = 0.5 } = {}) {   // corte com movimento entre cenas
      M.sair(cenaSai, t, { dur }); M.entrar(cenaEntra, t + dur * 0.6, { de: "zoom", dur: dur + 0.2 });
    },
  };
  // Atualiza contadores no tempo do vídeo (a ferramenta animar chama window.quadro(ms)).
  const anterior = window.quadro;
  window.quadro = (tms) => {
    const t = tms / 1000;
    for (const c of contadores) {
      const p = Math.min(1, Math.max(0, (t - c.inicio) / c.dur));
      const e = 1 - Math.pow(1 - p, 4);
      const v = c.de + (c.ate - c.de) * e;
      c.el.textContent = c.antes + v.toLocaleString("pt-BR", { minimumFractionDigits: c.casas, maximumFractionDigits: c.casas }) + c.depois;
    }
    if (anterior) anterior(tms);
  };
  const st = document.createElement("style");
  st.textContent = ".m-mask{display:inline-block;overflow:hidden;vertical-align:top;padding-bottom:.08em;margin-bottom:-.08em}.m-p{display:inline-block}.m-l{display:inline-block}";
  document.head.appendChild(st);
  window.M = M;
})();

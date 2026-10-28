/* Central HAIZEN — página única, sem bibliotecas externas. */
"use strict";

// ── utilidades ────────────────────────────────────────────────────────────
const $ = (sel, raiz = document) => raiz.querySelector(sel);
const $$ = (sel, raiz = document) => [...raiz.querySelectorAll(sel)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const moedaFmt = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const moeda = (v) => moedaFmt.format(v || 0);
const moedaCurta = (v) => (Math.abs(v) >= 1000 ? `R$ ${(v / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mil` : moeda(v));
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const MESES_LONGOS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const dataBr = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "");
const hojeIso = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); };
const valorCampo = (v) => (v || v === 0 ? Number(v).toFixed(2).replace(".", ",") : "");
const guardar = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* sem armazenamento */ } };
const lembrar = (k, padrao) => { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : padrao; } catch (_) { return padrao; } };

async function api(metodo, caminho, corpo) {
  const r = await fetch(`/api/${caminho}`, {
    method: metodo,
    headers: { "X-Central": "1", "Content-Type": "application/json" },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  const dados = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(dados.erro || `Erro ${r.status}`);
  return dados;
}

function avisar(texto) {
  const el = $("#aviso");
  el.textContent = texto;
  el.hidden = false;
  clearTimeout(avisar.t);
  avisar.t = setTimeout(() => { el.hidden = true; }, 3200);
}

let OPCOES = null;
async function opcoes(recarregar = false) {
  if (!OPCOES || recarregar) OPCOES = await api("GET", "opcoes");
  return OPCOES;
}
const nomeCliente = (id) => (OPCOES?.clientes.find((c) => c.id === id) || {}).nome || "";

// ── diálogo de formulário ─────────────────────────────────────────────────
function campo({ nome, rotulo, tipo = "text", valor = "", opcoes: ops, largo, obrig, ajuda }) {
  const cls = largo ? ' class="largo"' : "";
  const req = obrig ? " required" : "";
  if (tipo === "select") {
    const itens = ops.map((o) => {
      const [v, t] = Array.isArray(o) ? o : [o, o];
      return `<option value="${esc(v)}"${String(v) === String(valor ?? "") ? " selected" : ""}>${esc(t)}</option>`;
    }).join("");
    return `<label${cls}>${esc(rotulo)}<select name="${nome}"${req}>${itens}</select></label>`;
  }
  if (tipo === "textarea") return `<label${cls}>${esc(rotulo)}<textarea name="${nome}"${req}>${esc(valor)}</textarea></label>`;
  if (tipo === "checkbox") return `<label class="caixa${largo ? " largo" : ""}"><input type="checkbox" name="${nome}"${valor ? " checked" : ""}> ${esc(rotulo)}</label>`;
  const extra = tipo === "dinheiro" ? ' inputmode="decimal" placeholder="0,00"' : "";
  const t = tipo === "dinheiro" ? "text" : tipo;
  return `<label${cls}>${esc(rotulo)}<input type="${t}" name="${nome}" value="${esc(valor)}"${extra}${req}>${ajuda ? `<small>${esc(ajuda)}</small>` : ""}</label>`;
}

function lerFormulario(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    out[el.name] = el.type === "checkbox" ? el.checked : el.value;
  }
  return out;
}

/* Abre o diálogo; cada ação recebe os valores do formulário e pode devolver
   uma promessa. Se ela falhar, a mensagem aparece no próprio diálogo. */
function dialogo({ titulo, corpo, acoes, aoAbrir }) {
  const dlg = $("#dialogo");
  $("#dialogo-titulo").textContent = titulo;
  $("#dialogo-corpo").innerHTML = corpo;
  const erro = $("#dialogo-erro");
  erro.hidden = true;
  const rodape = $("#dialogo-acoes");
  rodape.innerHTML = "";
  for (const a of acoes) {
    const b = document.createElement("button");
    b.type = a.enviar ? "submit" : "button";
    b.className = `botao ${a.classe || ""}`;
    b.textContent = a.texto;
    b.addEventListener("click", async (ev) => {
      ev.preventDefault();
      const form = $("#dialogo-form");
      if (a.enviar && !form.reportValidity()) return;
      try {
        b.disabled = true;
        const fechar = await a.acao(lerFormulario(form));
        if (fechar !== false) dlg.close();
      } catch (e) {
        erro.textContent = e.message;
        erro.hidden = false;
      } finally {
        b.disabled = false;
      }
    });
    rodape.appendChild(b);
  }
  if (!dlg.open) dlg.showModal();
  if (aoAbrir) aoAbrir($("#dialogo-corpo"));
  const primeiro = $("#dialogo-corpo input, #dialogo-corpo select, #dialogo-corpo textarea");
  if (primeiro) primeiro.focus();
}
$("[data-fechar]").addEventListener("click", () => $("#dialogo").close());

// Confirmação que não fecha o diálogo de quem pediu: um segundo <dialog>.
const confirmarExclusao = (texto) => new Promise((ok) => {
  const d = document.createElement("dialog");
  d.className = "confirmar";
  d.innerHTML = `<p>${esc(texto)}</p><div class="dialogo-acoes"><button class="botao" value="nao">Cancelar</button><button class="botao perigo" value="sim">Excluir</button></div>`;
  document.body.appendChild(d);
  d.addEventListener("click", (e) => { const v = e.target.closest("button")?.value; if (v) { d.close(); ok(v === "sim"); } });
  d.addEventListener("close", () => { d.remove(); ok(false); });
  d.showModal();
});

const confirmar = (texto) => new Promise((ok) => {
  dialogo({
    titulo: "Confirmar", corpo: `<p>${esc(texto)}</p>`,
    acoes: [{ texto: "Cancelar", acao: () => ok(false) }, { texto: "Apagar", classe: "perigo", acao: () => ok(true) }],
  });
});

// ── roteamento ────────────────────────────────────────────────────────────
const ROTAS = {};
const main = $("#conteudo");

// Dentro da janela do Jarvis (?embutido=1), o próprio Jarvis já conversa e
// ouve: a central esconde o chat dela para não haver dois assistentes.
const EMBUTIDO = new URLSearchParams(location.search).has("embutido");
if (EMBUTIDO) document.body.classList.add("embutido");

// Dentro da janela do Jarvis (?app=1) a interface é a própria janela: a tela
// Jarvis comanda o Jarvis nativo (voz, PC), pela ponte /api/janela.
const APP = new URLSearchParams(location.search).has("app");
if (APP) document.body.classList.add("app");
let PONTE = false;          // a janela do Jarvis está aberta e respondendo
let NATIVO = null;          // quem, na tela atual, quer saber do estado da janela

async function navegar() {
  const [rota, param] = (location.hash.replace(/^#\/?/, "") || (PONTE ? "jarvis" : "painel")).split("/");
  const padrao = PONTE ? "jarvis" : "painel";
  const tela = ROTAS[rota] && !(EMBUTIDO && !PONTE && rota === "jarvis") ? rota : padrao;
  $$(".trilho nav a").forEach((a) => {
    if (a.dataset.rota === tela) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  clearInterval(navegar.timer);
  NATIVO = null;
  if (CONVERSA.ligada && tela !== "jarvis") desligarConversa();   // sair da tela desliga o microfone
  try {
    await opcoes();
    await ROTAS[tela](param);
  } catch (e) {
    main.innerHTML = `<p class="erro">Não consegui carregar esta tela: ${esc(e.message)}. Confira se o Jarvis está aberto e recarregue a página.</p>`;
  }
  atualizarSelo();
}
window.addEventListener("hashchange", navegar);

async function atualizarSelo() {
  try {
    const t = await api("GET", "trabalhos?status=aguardando_aprovacao&limite=99");
    const s = $("#selo-agentes");
    s.hidden = !t.length;
    s.textContent = t.length;
    s.title = `${t.length} entrega(s) aguardando sua aprovação`;
  } catch (_) { /* silencioso */ }
}

// ── período ───────────────────────────────────────────────────────────────
function periodoPadrao(tipo) {
  const d = new Date();
  const y = d.getFullYear(), m = d.getMonth();
  const iso = (a, b, c) => `${a}-${String(b + 1).padStart(2, "0")}-${String(c).padStart(2, "0")}`;
  const fimMes = (a, b) => new Date(a, b + 1, 0).getDate();
  if (tipo === "anterior") { const a = m === 0 ? y - 1 : y, b = m === 0 ? 11 : m - 1; return { tipo, de: iso(a, b, 1), ate: iso(a, b, fimMes(a, b)) }; }
  if (tipo === "ano") return { tipo, de: `${y}-01-01`, ate: `${y}-12-31` };
  return { tipo: "mes", de: iso(y, m, 1), ate: iso(y, m, fimMes(y, m)) };
}

function descreverPeriodo(p) {
  if (p.de.slice(0, 7) === p.ate.slice(0, 7)) return `em ${MESES_LONGOS[+p.de.slice(5, 7) - 1]} de ${p.de.slice(0, 4)}`;
  if (p.de.endsWith("-01-01") && p.ate.endsWith("-12-31") && p.de.slice(0, 4) === p.ate.slice(0, 4)) return `em ${p.de.slice(0, 4)}`;
  return `de ${dataBr(p.de)} a ${dataBr(p.ate)}`;
}

function seletorPeriodo(p, aoMudar) {
  const html = `
    <div class="filtros" role="group" aria-label="Período">
      <div class="grupo">
        <button type="button" data-p="mes" aria-pressed="${p.tipo === "mes"}">Este mês</button>
        <button type="button" data-p="anterior" aria-pressed="${p.tipo === "anterior"}">Mês anterior</button>
        <button type="button" data-p="ano" aria-pressed="${p.tipo === "ano"}">Este ano</button>
      </div>
      <label class="campo-data">De <input type="date" name="de" value="${p.de}"></label>
      <label class="campo-data">até <input type="date" name="ate" value="${p.ate}"></label>
    </div>`;
  const ligar = (raiz) => {
    $$("[data-p]", raiz).forEach((b) => b.addEventListener("click", () => aoMudar(periodoPadrao(b.dataset.p))));
    $$('input[type="date"]', raiz).forEach((i) => i.addEventListener("change", () => {
      const de = $('input[name="de"]', raiz).value, ate = $('input[name="ate"]', raiz).value;
      if (de && ate) aoMudar({ tipo: "livre", de, ate });
    }));
  };
  return { html, ligar };
}

// ── painel ────────────────────────────────────────────────────────────────
function regua(serie, mesFoco) {
  const max = Math.max(1, ...serie.map((s) => Math.max(s.receita, s.custos)));
  const n = serie.length, l = 100 / n, alt = 150;
  const barras = serie.map((s, i) => {
    const h = (s.receita / max) * alt, hc = (s.custos / max) * alt;
    const foco = s.mes === mesFoco;
    const x = i * l + l * 0.18, w = l * 0.64;
    const titulo = `${MESES[+s.mes.slice(5) - 1]} ${s.mes.slice(0, 4)}: recebido ${moeda(s.receita)}, pago ${moeda(s.custos)}`;
    return `<g><title>${esc(titulo)}</title>
      <rect x="${x}%" y="${alt - h}" width="${w}%" height="${Math.max(h, 1)}" rx="2" fill="${foco ? "#9BC53D" : "#C9D6D3"}"/>
      ${hc > 0 ? `<rect x="${x}%" y="${alt - hc}" width="${w}%" height="2" fill="#0B1D23"/>` : ""}</g>`;
  }).join("");
  const rotulos = serie.map((s) => `<span${s.mes === mesFoco ? ' style="color:#0E1A1E;font-weight:600"' : ""}>${MESES[+s.mes.slice(5) - 1]}</span>`).join("");
  return `<div class="regua" aria-label="Recebido por mês nos últimos 12 meses">
    <svg viewBox="0 0 100 ${alt}" preserveAspectRatio="none" role="img">${barras}</svg>
    <div class="regua-legenda">${rotulos}</div>
    <p class="resultado-legenda" style="font-size:12px;margin-top:8px">Barra: recebido no mês. Traço escuro: custos pagos.</p>
  </div>`;
}

function barras(itens, chave, max) {
  if (!itens.length) return '<p class="vazio">Nada no período.</p>';
  const topo = max || Math.max(...itens.map((i) => i.valor));
  return `<ul class="barras">${itens.map((i) => `
    <li><span class="nome" title="${esc(i[chave])}">${esc(i[chave])}</span>
      <span class="trilha"><span class="cheio" style="width:${Math.max(2, (i.valor / topo) * 100)}%"></span></span>
      <span class="valor">${moeda(i.valor)}</span></li>`).join("")}</ul>`;
}

ROTAS.painel = async () => {
  const p = lembrar("central.periodo", periodoPadrao("mes"));
  const d = await api("GET", `painel?de=${p.de}&ate=${p.ate}`);
  const sel = seletorPeriodo(p, (novo) => { guardar("central.periodo", novo); ROTAS.painel(); });
  const hoje = hojeIso();
  const proximas = d.proximas_tarefas.map((t) => {
    const atrasada = t.data_entrega && t.data_entrega < hoje;
    return `<li><span>${esc(t.titulo)}${t.cliente_nome ? ` <span class="meta">${esc(t.cliente_nome)}</span>` : ""}</span>
      <span class="meta${atrasada ? " atrasada" : ""}">${t.data_entrega ? (atrasada ? "atrasada, " : "") + dataBr(t.data_entrega) : "sem data"}</span></li>`;
  }).join("") || '<li><span class="meta">Nenhuma tarefa aberta.</span></li>';
  const funil = d.pipeline.map((e) => `<div class="${e.etapa === "Ganho" ? "ganho" : ""}"><span>${esc(e.etapa)}</span><strong>${e.quantidade}</strong><span>${moedaCurta(e.valor)}</span></div>`).join("");
  main.innerHTML = `
    <div class="topo"><div><h1>Painel</h1><p class="sub">Como está a HAIZEN ${esc(descreverPeriodo(d.periodo))}</p></div>${sel.html}</div>
    <section class="resultado" aria-label="Resultado do período">
      <div>
        <p class="resultado-legenda">Lucro ${esc(descreverPeriodo(d.periodo))}</p>
        <p class="resultado-numero${d.lucro < 0 ? " negativo" : ""}">${moeda(d.lucro)}</p>
        <div class="resultado-partes">
          <div class="parte entra"><strong>${moeda(d.receita)}</strong><span>recebido</span></div>
          <div class="parte"><strong>${moeda(d.custos)}</strong><span>pago em custos</span></div>
          <div class="parte"><strong>${d.margem.toLocaleString("pt-BR")}%</strong><span>de margem</span></div>
        </div>
      </div>
      ${regua(d.serie, d.periodo.ate.slice(0, 7))}
    </section>
    <section class="faixa" aria-label="Pendências">
      <a href="#/financeiro/receitas" class="${d.vencido > 0 ? "alerta" : ""}"><strong>${moeda(d.a_receber)}</strong><span>a receber${d.vencido > 0 ? `, ${moeda(d.vencido)} vencido` : ""}</span></a>
      <a href="#/financeiro/despesas"><strong>${moeda(d.a_pagar)}</strong><span>a pagar</span></a>
      <a href="#/tarefas" class="${d.tarefas_atrasadas ? "alerta" : ""}"><strong>${d.tarefas_atrasadas}</strong><span>${d.tarefas_atrasadas === 1 ? "tarefa atrasada" : "tarefas atrasadas"} de ${d.tarefas_abertas} abertas</span></a>
      <a href="#/agentes"><strong>${d.entregas_aguardando}</strong><span>${d.entregas_aguardando === 1 ? "entrega dos agentes" : "entregas dos agentes"} para aprovar</span></a>
    </section>
    <div class="colunas">
      <section class="bloco"><div class="bloco-topo"><h2>Quem pagou no período</h2><a href="#/clientes">Clientes</a></div>${barras(d.top_clientes, "cliente")}</section>
      <section class="bloco"><div class="bloco-topo"><h2>Próximas entregas</h2><a href="#/tarefas">Tarefas</a></div><ul class="lista">${proximas}</ul></section>
      <section class="bloco"><div class="bloco-topo"><h2>Custos por categoria</h2><a href="#/financeiro/despesas">Despesas</a></div>${barras(d.categorias, "categoria")}</section>
      <section class="bloco"><div class="bloco-topo"><h2>Pipeline</h2><a href="#/pipeline">Abrir</a></div><div class="funil">${funil}</div>
        <p class="sub" style="font-size:13px">${d.tarefas_concluidas} ${d.tarefas_concluidas === 1 ? "tarefa concluída" : "tarefas concluídas"} ${esc(descreverPeriodo(d.periodo))}.</p></section>
    </div>`;
  sel.ligar(main);
};

// ── financeiro ────────────────────────────────────────────────────────────
function formReceita(r = {}) {
  const clientes = [["", "Sem cliente"], ...OPCOES.clientes.map((c) => [c.id, c.nome])];
  return `<div class="campos">
    ${campo({ nome: "cliente_id", rotulo: "Cliente", tipo: "select", opcoes: clientes, valor: r.cliente_id ?? "", largo: true })}
    ${campo({ nome: "descricao", rotulo: "Serviço", valor: r.descricao, largo: true })}
    ${campo({ nome: "valor", rotulo: "Valor (R$)", tipo: "dinheiro", valor: valorCampo(r.valor), obrig: true })}
    ${campo({ nome: "vencimento", rotulo: "Vencimento", tipo: "date", valor: r.vencimento || hojeIso() })}
    ${campo({ nome: "recebido", rotulo: "Já recebi", tipo: "checkbox", valor: r.recebido })}
    ${campo({ nome: "data_recebimento", rotulo: "Recebido em", tipo: "date", valor: r.data_recebimento })}
  </div>`;
}

function formDespesa(r = {}) {
  return `<div class="campos">
    ${campo({ nome: "descricao", rotulo: "Despesa", valor: r.descricao, largo: true, obrig: true })}
    ${campo({ nome: "categoria", rotulo: "Categoria", tipo: "select", opcoes: OPCOES.categorias, valor: r.categoria || "Assinaturas" })}
    ${campo({ nome: "valor", rotulo: "Valor (R$)", tipo: "dinheiro", valor: valorCampo(r.valor), obrig: true })}
    ${campo({ nome: "vencimento", rotulo: "Vencimento", tipo: "date", valor: r.vencimento || hojeIso() })}
    ${campo({ nome: "pago", rotulo: "Já paguei", tipo: "checkbox", valor: r.pago })}
    ${campo({ nome: "data_pagamento", rotulo: "Pago em", tipo: "date", valor: r.data_pagamento })}
  </div>`;
}

function editarLancamento(tipo, item, depois, extra = {}) {
  const ent = tipo === "receitas" ? "receitas" : "despesas";
  const novo = !item.id;
  const acoes = [];
  if (!novo) acoes.push({ texto: "Apagar", classe: "perigo esquerda", acao: async () => {
    if (!(await confirmar("Apagar este lançamento? Não dá para desfazer."))) return;
    await api("DELETE", `${ent}/${item.id}`); avisar("Lançamento apagado"); depois();
  } });
  acoes.push({ texto: "Cancelar", acao: () => {} });
  acoes.push({ texto: novo ? "Adicionar" : "Salvar", classe: "primario", enviar: true, acao: async (v) => {
    if (novo) await api("POST", ent, { ...extra, ...v }); else await api("PATCH", `${ent}/${item.id}`, v);
    avisar(novo ? "Lançamento adicionado" : "Alterações salvas"); depois();
  } });
  dialogo({
    titulo: `${novo ? "Nova" : "Editar"} ${tipo === "receitas" ? "receita" : "despesa"}`,
    corpo: tipo === "receitas" ? formReceita({ ...extra, ...item }) : formDespesa(item),
    acoes,
  });
}

ROTAS.financeiro = async (aba) => {
  aba = aba === "despesas" ? "despesas" : "receitas";
  const f = lembrar("central.fin", { de: `${new Date().getFullYear()}-01-01`, ate: `${new Date().getFullYear()}-12-31`, situacao: "", cliente: "", busca: "" });
  const q = new URLSearchParams({ de: f.de, ate: f.ate });
  if (aba === "receitas" && f.cliente) q.set("cliente_id", f.cliente);
  let itens = await api("GET", `${aba}?${q}`);
  const ok = aba === "receitas" ? "recebido" : "pago";
  const hoje = hojeIso();
  if (f.situacao === "abertas") itens = itens.filter((i) => !i[ok]);
  if (f.situacao === "quitadas") itens = itens.filter((i) => i[ok]);
  if (f.busca) { const b = f.busca.toLowerCase(); itens = itens.filter((i) => `${i.descricao} ${i.cliente_nome || ""} ${i.categoria || ""}`.toLowerCase().includes(b)); }
  const total = itens.reduce((s, i) => s + i.valor, 0);
  const quitado = itens.filter((i) => i[ok]).reduce((s, i) => s + i.valor, 0);
  const linhas = itens.map((i) => {
    const vencida = !i[ok] && i.vencimento && i.vencimento < hoje;
    const rotulo = i[ok] ? (aba === "receitas" ? "Recebido" : "Pago") : vencida ? "Vencido" : "Em aberto";
    return `<tr>
      <td><button class="situacao ${i[ok] ? "ok" : vencida ? "vencida" : ""}" data-alternar="${i.id}" title="Clique para marcar como ${i[ok] ? "em aberto" : aba === "receitas" ? "recebido" : "pago"}">${rotulo}</button></td>
      ${aba === "receitas" ? `<td>${esc(i.cliente_nome || "—")}</td>` : `<td>${esc(i.categoria)}</td>`}
      <td>${esc(i.descricao)}</td>
      <td>${dataBr(i.vencimento)}</td>
      <td>${dataBr(aba === "receitas" ? i.data_recebimento : i.data_pagamento)}</td>
      <td class="num">${moeda(i.valor)}</td>
      <td><button class="botao-icone" data-editar="${i.id}" aria-label="Editar">Editar</button></td></tr>`;
  }).join("");
  const clientes = [["", "Todos os clientes"], ...OPCOES.clientes.map((c) => [c.id, c.nome])];
  main.innerHTML = `
    <div class="topo"><div><h1>Financeiro</h1><p class="sub">${aba === "receitas" ? "O que entra" : "O que sai"} de ${dataBr(f.de)} a ${dataBr(f.ate)}</p></div>
      <button class="botao primario" id="novo">${aba === "receitas" ? "Nova receita" : "Nova despesa"}</button></div>
    <div class="filtros">
      <div class="grupo" role="tablist">
        <button type="button" role="tab" aria-pressed="${aba === "receitas"}" data-aba="receitas">Receitas</button>
        <button type="button" role="tab" aria-pressed="${aba === "despesas"}" data-aba="despesas">Despesas</button>
      </div>
      <label class="campo-data">De <input type="date" id="f-de" value="${f.de}"></label>
      <label class="campo-data">até <input type="date" id="f-ate" value="${f.ate}"></label>
      ${aba === "receitas" ? `<select id="f-cliente" aria-label="Cliente">${clientes.map(([v, t]) => `<option value="${v}"${String(v) === String(f.cliente) ? " selected" : ""}>${esc(t)}</option>`).join("")}</select>` : ""}
      <select id="f-situacao" aria-label="Situação">
        <option value="">Todas</option><option value="abertas"${f.situacao === "abertas" ? " selected" : ""}>Em aberto</option>
        <option value="quitadas"${f.situacao === "quitadas" ? " selected" : ""}>${aba === "receitas" ? "Recebidas" : "Pagas"}</option></select>
      <input type="search" id="f-busca" placeholder="Buscar" value="${esc(f.busca)}" aria-label="Buscar">
    </div>
    <p class="totais"><span>Total <strong>${moeda(total)}</strong></span><span>${aba === "receitas" ? "Recebido" : "Pago"} <strong>${moeda(quitado)}</strong></span><span>Em aberto <strong>${moeda(total - quitado)}</strong></span><span>${itens.length} lançamentos</span></p>
    <div class="tabela-caixa">${itens.length ? `<table>
      <thead><tr><th>Situação</th><th>${aba === "receitas" ? "Cliente" : "Categoria"}</th><th>Descrição</th><th>Vencimento</th><th>${aba === "receitas" ? "Recebido em" : "Pago em"}</th><th class="num">Valor</th><th></th></tr></thead>
      <tbody>${linhas}</tbody></table>` : `<p class="vazio">Nenhum lançamento nesse filtro. Use "${aba === "receitas" ? "Nova receita" : "Nova despesa"}" para adicionar.</p>`}</div>`;
  const recarregar = () => ROTAS.financeiro(aba);
  const salvarFiltro = (k, v) => { f[k] = v; guardar("central.fin", f); recarregar(); };
  $$("[data-aba]").forEach((b) => b.addEventListener("click", () => { location.hash = `#/financeiro/${b.dataset.aba}`; }));
  $("#f-de").addEventListener("change", (e) => salvarFiltro("de", e.target.value));
  $("#f-ate").addEventListener("change", (e) => salvarFiltro("ate", e.target.value));
  $("#f-situacao").addEventListener("change", (e) => salvarFiltro("situacao", e.target.value));
  $("#f-cliente")?.addEventListener("change", (e) => salvarFiltro("cliente", e.target.value));
  let t; $("#f-busca").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => salvarFiltro("busca", e.target.value), 350); });
  $("#novo").addEventListener("click", () => editarLancamento(aba, {}, recarregar));
  $$("[data-editar]").forEach((b) => b.addEventListener("click", () => editarLancamento(aba, itens.find((i) => i.id === +b.dataset.editar), recarregar)));
  $$("[data-alternar]").forEach((b) => b.addEventListener("click", async () => {
    const i = itens.find((x) => x.id === +b.dataset.alternar);
    await api("PATCH", `${aba}/${i.id}`, { [ok]: !i[ok] });
    avisar(!i[ok] ? (aba === "receitas" ? "Marcado como recebido" : "Marcado como pago") : "Marcado como em aberto");
    recarregar();
  }));
};

// ── clientes ──────────────────────────────────────────────────────────────
function editarCliente(c, depois) {
  const novo = !c.id;
  dialogo({
    titulo: novo ? "Novo cliente" : "Editar cliente",
    corpo: `<div class="campos">
      ${campo({ nome: "nome", rotulo: "Nome", valor: c.nome, largo: true, obrig: true })}
      ${campo({ nome: "status", rotulo: "Situação", tipo: "select", opcoes: OPCOES.status_cliente, valor: c.status || "Ativo" })}
      ${campo({ nome: "contato", rotulo: "Telefone / WhatsApp", valor: c.contato })}
      ${campo({ nome: "email", rotulo: "E-mail", tipo: "email", valor: c.email, largo: true })}
      ${campo({ nome: "endereco", rotulo: "Endereço", valor: c.endereco, largo: true })}
      ${campo({ nome: "notas", rotulo: "Notas (os agentes leem: tom de voz, cores, público)", tipo: "textarea", valor: c.notas, largo: true })}
    </div>`,
    acoes: [
      ...(novo ? [] : [{ texto: "Apagar", classe: "perigo esquerda", acao: async () => {
        if (!(await confirmar(`Apagar ${c.nome}? Receitas e tarefas dele ficam sem cliente.`))) return;
        await api("DELETE", `clientes/${c.id}`); await opcoes(true); location.hash = "#/clientes"; avisar("Cliente apagado");
      } }]),
      { texto: "Cancelar", acao: () => {} },
      { texto: novo ? "Adicionar" : "Salvar", classe: "primario", enviar: true, acao: async (v) => {
        const r = novo ? await api("POST", "clientes", v) : await api("PATCH", `clientes/${c.id}`, v);
        await opcoes(true); avisar(novo ? "Cliente adicionado" : "Alterações salvas"); depois(r);
      } },
    ],
  });
}

function editarMarca(m, depois) {
  const clientes = [["", "Sem cliente"], ...OPCOES.clientes.map((c) => [c.id, c.nome])];
  dialogo({
    titulo: m.nome,
    corpo: `<div class="campos">
      ${campo({ nome: "cliente_id", rotulo: "Quem paga por esta marca", tipo: "select", opcoes: clientes, valor: m.cliente_id ?? "", largo: true })}
      ${campo({ nome: "pasta", rotulo: "Pasta no Drive", valor: m.pasta, largo: true })}
      ${campo({ nome: "notas", rotulo: "Notas", tipo: "textarea", valor: m.notas, largo: true })}
    </div>`,
    acoes: [
      { texto: "Abrir pasta", classe: "esquerda", acao: async () => { await api("POST", `marcas/${m.id}/abrir`); return false; } },
      { texto: "Cancelar", acao: () => {} },
      { texto: "Salvar", classe: "primario", enviar: true, acao: async (v) => { await api("PATCH", `marcas/${m.id}`, v); avisar("Marca atualizada"); depois(); } },
    ],
  });
}

ROTAS.clientes = async (param) => {
  const todos = await api("GET", "clientes");
  const marcasSoltas = (await api("GET", "marcas")).filter((m) => !m.cliente_id);
  const filtro = lembrar("central.cli.busca", "");
  const selecionado = param ? +param : (todos[0] || {}).id;
  const listaHtml = () => {
    const b = filtro.toLowerCase();
    return todos.filter((c) => !b || c.nome.toLowerCase().includes(b)).map((c) => `
      <button data-cli="${c.id}" aria-current="${c.id === selecionado}">
        <span class="${c.status !== "Ativo" ? "inativo" : ""}">${esc(c.nome)}</span>
        <span class="meta" style="color:var(--cinza);font-size:13px">${c.status !== "Ativo" ? esc(c.status) : ""}</span></button>`).join("");
  };
  main.innerHTML = `
    <div class="topo"><div><h1>Clientes</h1><p class="sub">${todos.filter((c) => c.status === "Ativo").length} ativos de ${todos.length}</p></div>
      <button class="botao primario" id="novo-cli">Novo cliente</button></div>
    <div class="dividido">
      <div>
        <div class="filtros"><input type="search" id="busca-cli" placeholder="Buscar cliente" value="${esc(filtro)}" aria-label="Buscar cliente" style="width:100%"></div>
        <nav class="lista-clientes" id="lista-cli" aria-label="Clientes">${listaHtml()}</nav>
        ${marcasSoltas.length ? `<section class="bloco" style="margin-top:16px"><h2>Pastas sem cliente</h2><div class="pastas">${marcasSoltas.map((m) => `<button class="pasta" data-marca="${m.id}">${esc(m.nome)}</button>`).join("")}</div></section>` : ""}
      </div>
      <div class="ficha" id="ficha">${selecionado ? '<p class="carregando">Carregando ficha…</p>' : '<p class="vazio">Nenhum cliente ainda. Use "Novo cliente" ou importe do Base44.</p>'}</div>
    </div>`;
  const ir = (id) => { location.hash = `#/clientes/${id}`; };
  $("#lista-cli").addEventListener("click", (e) => { const b = e.target.closest("[data-cli]"); if (b) ir(b.dataset.cli); });
  $("#busca-cli").addEventListener("input", (e) => { guardar("central.cli.busca", e.target.value); const v = e.target.value.toLowerCase();
    $$("#lista-cli [data-cli]").forEach((b) => { b.hidden = !b.textContent.toLowerCase().includes(v); }); });
  $("#novo-cli").addEventListener("click", () => editarCliente({}, (r) => ir(r.id)));
  $$("[data-marca]").forEach((b) => b.addEventListener("click", () => editarMarca(marcasSoltas.find((m) => m.id === +b.dataset.marca), () => ROTAS.clientes(param))));
  if (selecionado) await fichaCliente(selecionado, () => ROTAS.clientes(selecionado));
};

async function fichaCliente(id, recarregar) {
  const f = await api("GET", `clientes/${id}/ficha`);
  const c = f.cliente;
  const abertas = f.tarefas.filter((t) => t.status !== "Concluída");
  const recentes = f.receitas.slice(0, 8).map((r) => `<tr><td>${dataBr(r.data_recebimento || r.vencimento)}</td><td>${esc(r.descricao)}</td>
    <td>${r.recebido ? "Recebido" : "Em aberto"}</td><td class="num">${moeda(r.valor)}</td></tr>`).join("");
  const contato = [c.contato, c.email].filter(Boolean).map(esc).join(", ");
  $("#ficha").innerHTML = `
    <div class="ficha-cabeca"><div><h2 style="font-size:24px;margin:0">${esc(c.nome)}</h2>
      <p class="sub">${esc(c.status)}${contato ? `, ${contato}` : ""}</p></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="botao" id="cli-receita">Nova receita</button>
        <button class="botao" id="cli-tarefa">Nova tarefa</button>
        <button class="botao" id="cli-editar">Editar</button></div></div>
    <div class="ficha-numeros">
      <div><strong>${moeda(f.total_recebido)}</strong><span>recebido no total</span></div>
      <div><strong>${moeda(f.em_aberto)}</strong><span>em aberto</span></div>
      <div><strong>${abertas.length}</strong><span>${abertas.length === 1 ? "tarefa aberta" : "tarefas abertas"}</span></div>
    </div>
    ${c.notas ? `<section class="bloco"><h2>Notas</h2><p style="white-space:pre-wrap;margin:0">${esc(c.notas)}</p></section>` : ""}
    <section class="bloco"><h2>Marcas e pastas no Drive</h2>${f.marcas.length ? `<div class="pastas">${f.marcas.map((m) => `<button class="pasta" data-marca="${m.id}" title="${esc(m.pasta)}">${esc(m.nome)}</button>`).join("")}</div>` : '<p class="sub" style="margin:0">Nenhuma pasta ligada. As pastas sem cliente aparecem na coluna ao lado.</p>'}</section>
    <section class="bloco"><div class="bloco-topo"><h2>Tarefas abertas</h2><a href="#/tarefas">Ver todas</a></div>
      ${abertas.length ? `<ul class="lista">${abertas.map((t) => `<li><span>${esc(t.titulo)}</span><span class="meta">${esc(t.status)}${t.data_entrega ? `, ${dataBr(t.data_entrega)}` : ""}</span></li>`).join("")}</ul>` : '<p class="sub" style="margin:0">Nenhuma tarefa aberta.</p>'}</section>
    <section class="bloco"><div class="bloco-topo"><h2>Últimos lançamentos</h2><a href="#/financeiro/receitas">Financeiro</a></div>
      ${recentes ? `<div class="tabela-caixa" style="border:0"><table><tbody>${recentes}</tbody></table></div>` : '<p class="sub" style="margin:0">Nenhuma receita registrada.</p>'}</section>
    ${f.trabalhos.length ? `<section class="bloco"><h2>Entregas dos agentes</h2><ul class="lista">${f.trabalhos.map((t) => `<li><a href="#/agentes/${t.id}">Trabalho ${t.id}, ${esc(t.agente)}</a><span class="meta status-${t.status}">${esc(STATUS_TRAB[t.status] || t.status)}</span></li>`).join("")}</ul></section>` : ""}`;
  $("#cli-editar").addEventListener("click", () => editarCliente(c, recarregar));
  $("#cli-receita").addEventListener("click", () => editarLancamento("receitas", {}, recarregar, { cliente_id: c.id }));
  $("#cli-tarefa").addEventListener("click", () => editarTarefa({ cliente_id: c.id }, recarregar));
  $$("#ficha [data-marca]").forEach((b) => b.addEventListener("click", () => editarMarca(f.marcas.find((m) => m.id === +b.dataset.marca), recarregar)));
}

// ── quadro arrastável (tarefas e pipeline) ────────────────────────────────
function ligarQuadro(raiz, ent, campoColuna, recarregar) {
  let arrastando = null;
  $$(".cartao", raiz).forEach((c) => {
    c.draggable = true;
    c.addEventListener("dragstart", (e) => { arrastando = c.dataset.id; c.setAttribute("aria-grabbed", "true"); e.dataTransfer.effectAllowed = "move"; });
    c.addEventListener("dragend", () => c.removeAttribute("aria-grabbed"));
  });
  $$(".coluna", raiz).forEach((col) => {
    col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("alvo"); });
    col.addEventListener("dragleave", () => col.classList.remove("alvo"));
    col.addEventListener("drop", async (e) => {
      e.preventDefault(); col.classList.remove("alvo");
      if (!arrastando) return;
      try {
        await api("PATCH", `${ent}/${arrastando}`, { [campoColuna]: col.dataset.coluna });
        avisar(`Movido para ${col.dataset.coluna}`);
      } catch (err) { avisar(err.message); }
      arrastando = null; recarregar();
    });
  });
}

// ── tarefas ───────────────────────────────────────────────────────────────
async function editarTarefa(t, depois) {
  const novo = !t.id;
  const clientes = [["", "Sem cliente"], ...OPCOES.clientes.map((c) => [c.id, c.nome])];
  const subs = novo ? [] : await api("GET", `subtarefas?tarefa_id=${t.id}`);
  const comentarios = (t.comentarios || []).map((c) => `<li><span style="white-space:pre-wrap">${esc(c.texto)}</span><span class="meta">${esc((c.data || "").slice(0, 10).split("-").reverse().join("/"))}</span></li>`).join("");
  dialogo({
    titulo: novo ? "Nova tarefa" : "Tarefa",
    corpo: `<div class="campos">
      ${campo({ nome: "titulo", rotulo: "Título", valor: t.titulo, largo: true, obrig: true })}
      ${campo({ nome: "cliente_id", rotulo: "Cliente", tipo: "select", opcoes: clientes, valor: t.cliente_id ?? "" })}
      ${campo({ nome: "status", rotulo: "Situação", tipo: "select", opcoes: OPCOES.status_tarefa, valor: t.status || "A Fazer" })}
      ${campo({ nome: "prioridade", rotulo: "Prioridade", tipo: "select", opcoes: OPCOES.prioridades, valor: t.prioridade || "Média" })}
      ${campo({ nome: "data_entrega", rotulo: "Entrega", tipo: "date", valor: t.data_entrega })}
      ${campo({ nome: "descricao", rotulo: "Descrição", tipo: "textarea", valor: t.descricao, largo: true })}
      <div class="largo acessos" id="acessos">
        ${t.tem_acessos ? '<strong>Esta tarefa tem logins e senhas guardados.</strong> <button type="button" class="botao" id="ver-acessos" style="margin-left:8px">Mostrar acessos</button>'
          : '<strong>Acessos</strong> <span class="sub">(logins e senhas ficam aqui, fora da descrição e longe dos agentes)</span> <button type="button" class="botao" id="ver-acessos" style="margin-left:8px">Adicionar</button>'}
      </div>
      ${novo ? "" : `<div class="largo"><strong style="font-size:13px;color:var(--cinza)">Etapas</strong>
        <ul class="subtarefas" id="subs">${subs.map((s) => `<li><label><input type="checkbox" data-sub="${s.id}"${s.concluida ? " checked" : ""}> ${esc(s.titulo)}</label></li>`).join("")}</ul>
        <div style="display:flex;gap:8px;margin-top:6px"><input id="nova-sub" placeholder="Nova etapa" style="flex:1;border:1px solid var(--linha);border-radius:6px;padding:6px 8px"><button type="button" class="botao" id="add-sub">Adicionar</button></div></div>`}
      ${comentarios ? `<div class="largo"><strong style="font-size:13px;color:var(--cinza)">Comentários</strong><ul class="lista">${comentarios}</ul></div>` : ""}
    </div>`,
    acoes: [
      ...(novo ? [] : [{ texto: "Apagar", classe: "perigo esquerda", acao: async () => {
        if (!(await confirmar("Apagar esta tarefa?"))) return; await api("DELETE", `tarefas/${t.id}`); avisar("Tarefa apagada"); depois();
      } }]),
      { texto: "Cancelar", acao: () => {} },
      { texto: novo ? "Adicionar" : "Salvar", classe: "primario", enviar: true, acao: async (v) => {
        if (v.acessos === undefined) delete v.acessos;
        if (novo) await api("POST", "tarefas", v); else await api("PATCH", `tarefas/${t.id}`, v);
        avisar(novo ? "Tarefa adicionada" : "Alterações salvas"); depois();
      } },
    ],
    aoAbrir: (raiz) => {
      $("#ver-acessos", raiz).addEventListener("click", async () => {
        const texto = t.id && t.tem_acessos ? (await api("GET", `tarefas/${t.id}/acessos`)).acessos : "";
        $("#acessos", raiz).innerHTML = `<label style="display:flex;flex-direction:column;gap:4px;color:var(--cinza);font-size:13px">Acessos (só neste computador)
          <textarea name="acessos" style="min-height:110px;font:13px/1.5 var(--texto)">${esc(texto)}</textarea></label>`;
      });
      $$("[data-sub]", raiz).forEach((cx) => cx.addEventListener("change", () => api("PATCH", `subtarefas/${cx.dataset.sub}`, { concluida: cx.checked })));
      $("#add-sub", raiz)?.addEventListener("click", async () => {
        const i = $("#nova-sub", raiz); if (!i.value.trim()) return;
        const s = await api("POST", "subtarefas", { tarefa_id: t.id, titulo: i.value, ordem: subs.length });
        $("#subs", raiz).insertAdjacentHTML("beforeend", `<li><label><input type="checkbox" data-sub="${s.id}"> ${esc(s.titulo)}</label></li>`);
        $(`[data-sub="${s.id}"]`, raiz).addEventListener("change", (e) => api("PATCH", `subtarefas/${s.id}`, { concluida: e.target.checked }));
        i.value = "";
      });
    },
  });
}

ROTAS.tarefas = async () => {
  const f = lembrar("central.tar", { cliente: "", busca: "", todasConcluidas: false });
  let tarefas = await api("GET", `tarefas${f.cliente ? `?cliente_id=${f.cliente}` : ""}`);
  if (f.busca) { const b = f.busca.toLowerCase(); tarefas = tarefas.filter((t) => `${t.titulo} ${t.cliente_nome || ""}`.toLowerCase().includes(b)); }
  const hoje = hojeIso();
  const cartao = (t) => {
    const atrasada = t.status !== "Concluída" && t.data_entrega && t.data_entrega < hoje;
    return `<button class="cartao" data-id="${t.id}">
      <p class="cartao-titulo">${esc(t.titulo)}</p>
      <span class="cartao-meta">${t.cliente_nome ? `<span>${esc(t.cliente_nome)}</span>` : ""}
        ${t.data_entrega ? `<span class="${atrasada ? "atrasada" : ""}">${atrasada ? "Atrasada, " : ""}${dataBr(t.data_entrega)}</span>` : ""}
        ${t.prioridade !== "Média" ? `<span class="prioridade-${esc(t.prioridade)}">${esc(t.prioridade)}</span>` : ""}
        ${t.tem_acessos ? "<span>Tem acessos</span>" : ""}</span></button>`;
  };
  const colunas = OPCOES.status_tarefa.map((s) => {
    let lista = tarefas.filter((t) => t.status === s);
    const total = lista.length;
    if (s === "Concluída") {
      lista.sort((a, b) => (b.concluida_em || "").localeCompare(a.concluida_em || ""));
      if (!f.todasConcluidas) lista = lista.slice(0, 12);
    }
    return `<section class="coluna" data-coluna="${esc(s)}"><h2>${esc(s)} <span>${total}</span></h2>
      ${lista.map(cartao).join("")}
      ${s === "Concluída" && total > 12 ? `<button class="mais" id="ver-concluidas">${f.todasConcluidas ? "Mostrar só as recentes" : `Mostrar todas (${total})`}</button>` : ""}
      ${s === "A Fazer" ? '<button class="mais" id="nova-tarefa-col">Nova tarefa</button>' : ""}</section>`;
  }).join("");
  const clientes = [["", "Todos os clientes"], ...OPCOES.clientes.map((c) => [c.id, c.nome])];
  main.innerHTML = `
    <div class="topo"><div><h1>Tarefas</h1><p class="sub">Arraste um cartão para mudar a situação. Clique para abrir.</p></div>
      <button class="botao primario" id="nova-tarefa">Nova tarefa</button></div>
    <div class="filtros">
      <select id="f-cli" aria-label="Cliente">${clientes.map(([v, t]) => `<option value="${v}"${String(v) === String(f.cliente) ? " selected" : ""}>${esc(t)}</option>`).join("")}</select>
      <input type="search" id="f-busca" placeholder="Buscar tarefa" value="${esc(f.busca)}" aria-label="Buscar tarefa">
    </div>
    <div class="quadro" id="quadro">${colunas}</div>`;
  const recarregar = () => ROTAS.tarefas();
  const salvar = (k, v) => { f[k] = v; guardar("central.tar", f); recarregar(); };
  $("#f-cli").addEventListener("change", (e) => salvar("cliente", e.target.value));
  let tm; $("#f-busca").addEventListener("input", (e) => { clearTimeout(tm); tm = setTimeout(() => salvar("busca", e.target.value), 350); });
  $("#ver-concluidas")?.addEventListener("click", () => salvar("todasConcluidas", !f.todasConcluidas));
  $("#nova-tarefa").addEventListener("click", () => editarTarefa({}, recarregar));
  $("#nova-tarefa-col").addEventListener("click", () => editarTarefa({}, recarregar));
  $$(".cartao").forEach((c) => c.addEventListener("click", () => editarTarefa(tarefas.find((t) => t.id === +c.dataset.id), recarregar)));
  ligarQuadro($("#quadro"), "tarefas", "status", recarregar);
};

// ── pipeline ──────────────────────────────────────────────────────────────
function editarOportunidade(o, depois) {
  const novo = !o.id;
  const clientes = [["", "Ainda não é cliente"], ...OPCOES.clientes.map((c) => [c.id, c.nome])];
  dialogo({
    titulo: novo ? "Nova oportunidade" : "Oportunidade",
    corpo: `<div class="campos">
      ${campo({ nome: "titulo", rotulo: "O que é", valor: o.titulo, largo: true, obrig: true })}
      ${campo({ nome: "cliente_id", rotulo: "Cliente", tipo: "select", opcoes: clientes, valor: o.cliente_id ?? "" })}
      ${campo({ nome: "contato", rotulo: "Contato", valor: o.contato })}
      ${campo({ nome: "servico", rotulo: "Serviço", valor: o.servico })}
      ${campo({ nome: "valor", rotulo: "Valor estimado (R$)", tipo: "dinheiro", valor: valorCampo(o.valor) })}
      ${campo({ nome: "etapa", rotulo: "Etapa", tipo: "select", opcoes: OPCOES.etapas, valor: o.etapa || "Lead" })}
      ${campo({ nome: "previsao", rotulo: "Previsão de fechar", tipo: "date", valor: o.previsao })}
      ${campo({ nome: "notas", rotulo: "Notas", tipo: "textarea", valor: o.notas, largo: true })}
    </div>`,
    acoes: [
      ...(novo ? [] : [{ texto: "Apagar", classe: "perigo esquerda", acao: async () => {
        if (!(await confirmar("Apagar esta oportunidade?"))) return; await api("DELETE", `oportunidades/${o.id}`); avisar("Oportunidade apagada"); depois();
      } }]),
      { texto: "Cancelar", acao: () => {} },
      { texto: novo ? "Adicionar" : "Salvar", classe: "primario", enviar: true, acao: async (v) => {
        if (novo) await api("POST", "oportunidades", v); else await api("PATCH", `oportunidades/${o.id}`, v);
        avisar(novo ? "Oportunidade adicionada" : "Alterações salvas"); depois();
      } },
    ],
  });
}

ROTAS.pipeline = async () => {
  const ops = await api("GET", "oportunidades");
  const abertas = ops.filter((o) => !["Ganho", "Perdido"].includes(o.etapa));
  const colunas = OPCOES.etapas.map((e) => {
    const lista = ops.filter((o) => o.etapa === e);
    const soma = lista.reduce((s, o) => s + o.valor, 0);
    return `<section class="coluna" data-coluna="${esc(e)}"><h2>${esc(e)} <span>${lista.length ? moedaCurta(soma) : ""}</span></h2>
      ${lista.map((o) => `<button class="cartao" data-id="${o.id}"><p class="cartao-titulo">${esc(o.titulo)}</p>
        <span class="cartao-meta">${o.cliente_nome || o.contato ? `<span>${esc(o.cliente_nome || o.contato)}</span>` : ""}${o.valor ? `<span>${moeda(o.valor)}</span>` : ""}${o.previsao ? `<span>${dataBr(o.previsao)}</span>` : ""}</span></button>`).join("")}
      ${e === "Lead" ? '<button class="mais" id="nova-op-col">Nova oportunidade</button>' : ""}</section>`;
  }).join("");
  main.innerHTML = `
    <div class="topo"><div><h1>Pipeline</h1><p class="sub">${abertas.length ? `${abertas.length} em aberto, ${moeda(abertas.reduce((s, o) => s + o.valor, 0))} em negociação` : "Comece registrando quem pediu orçamento."}</p></div>
      <button class="botao primario" id="nova-op">Nova oportunidade</button></div>
    <div class="quadro" id="quadro">${colunas}</div>`;
  const recarregar = () => ROTAS.pipeline();
  $("#nova-op").addEventListener("click", () => editarOportunidade({}, recarregar));
  $("#nova-op-col").addEventListener("click", () => editarOportunidade({}, recarregar));
  $$(".cartao").forEach((c) => c.addEventListener("click", () => editarOportunidade(ops.find((o) => o.id === +c.dataset.id), recarregar)));
  ligarQuadro($("#quadro"), "oportunidades", "etapa", recarregar);
};

// ── agentes ───────────────────────────────────────────────────────────────
const STATUS_TRAB = { na_fila: "Na fila", executando: "Em execução", aguardando_aprovacao: "Aguardando aprovação", aprovado: "Aprovado", rejeitado: "Refeito", erro: "Com erro", esperando: "Esperando etapas anteriores" };

// Os arquivos que o agente produziu: miniaturas das imagens, vídeos e PDFs
// (buscados com o cabeçalho da central e mostrados como blob).
async function arquivoBlob(id, nome) {
  const r = await fetch(`/api/trabalhos/${id}/arquivo?nome=${encodeURIComponent(nome)}`, { headers: { "X-Central": "1" } });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).erro || `Erro ${r.status}`);
  return URL.createObjectURL(await r.blob());
}

async function galeriaTrabalho(t, caixa) {
  let r;
  try { r = await api("GET", `trabalhos/${t.id}/arquivos`); } catch (_) { return; }
  if (!r.arquivos.length) { if (r.pasta) caixa.innerHTML = `<p class="sub">Pasta do trabalho: ${esc(r.pasta)} (ainda sem arquivos)</p>`; return; }
  const finais = r.arquivos.filter((a) => !a.fonte && !["md", "html", "css", "js", "json"].includes(a.tipo));
  const outros = r.arquivos.filter((a) => !finais.includes(a));
  const img = ["png", "jpg", "jpeg", "webp", "gif", "svg"];
  caixa.innerHTML = `<h3 class="galeria-titulo">Arquivos produzidos <span class="sub">(${finais.length})</span></h3>
    <div class="galeria">${finais.map((a, i) => `<figure class="peca" data-i="${i}">
      ${img.includes(a.tipo) ? '<div class="peca-img carregando-img"></div>' : `<button type="button" class="peca-tipo" data-abrir-arq="${i}">${a.tipo === "mp4" || a.tipo === "mov" || a.tipo === "webm" ? "▶ Vídeo" : a.tipo.toUpperCase()}</button>`}
      <figcaption title="${esc(a.nome)}">${esc(a.nome)}</figcaption></figure>`).join("")}</div>
    ${outros.length ? `<details class="fontes"><summary>Arquivos-fonte e relatório (${outros.length})</summary><ul>${outros.map((a) => `<li>${esc(a.nome)}</li>`).join("")}</ul></details>` : ""}
    <p class="sub galeria-pasta">${esc(r.pasta)}</p>`;
  finais.forEach(async (a, i) => {
    const fig = $(`.peca[data-i="${i}"]`, caixa);
    if (img.includes(a.tipo)) {
      try {
        const url = await arquivoBlob(t.id, a.nome);
        fig.querySelector(".peca-img").outerHTML = `<a href="${url}" target="_blank" rel="noopener"><img src="${url}" alt="${esc(a.nome)}"></a>`;
      } catch (_) { fig.querySelector(".peca-img").textContent = "não abriu"; }
    }
  });
  $$("[data-abrir-arq]", caixa).forEach((b) => b.addEventListener("click", async () => {
    const a = finais[+b.dataset.abrirArq];
    b.disabled = true; b.textContent = "Abrindo…";
    try {
      const url = await arquivoBlob(t.id, a.nome);
      if (["mp4", "webm", "mov"].includes(a.tipo)) b.outerHTML = `<video src="${url}" controls autoplay muted playsinline></video>`;
      else { URL.revokeObjectURL(url); await api("POST", `trabalhos/${t.id}/abrir`, { nome: a.nome }); b.disabled = false; b.textContent = a.tipo.toUpperCase(); }
    } catch (e) { avisar(e.message); b.disabled = false; b.textContent = "Tentar abrir"; }
  }));
}

async function abrirTrabalho(id, recarregar) {
  const t = await api("GET", `trabalhos/${id}`);
  const pode = t.status === "aguardando_aprovacao";
  const excluir = t.status === "executando" ? [] : [{ texto: "Excluir", classe: "perigo esquerda", acao: async () => {
    if (!(await confirmarExclusao(`Excluir o trabalho ${t.id}${t.arquivo ? " e o arquivo da entrega" : ""}? Não dá para desfazer.`))) return false;
    await api("DELETE", `trabalhos/${t.id}`); avisar("Trabalho excluído"); recarregar();
  } }];
  dialogo({
    titulo: t.titulo ? `${t.titulo} (trabalho ${t.id}, ${t.agente})` : `Trabalho ${t.id}, ${t.agente}`,
    corpo: `<p class="sub" style="margin-top:0">${esc(t.cliente_nome || "Sem cliente")}, <span class="status-${t.status}">${esc(STATUS_TRAB[t.status] || t.status)}</span>, feito por ${t.executor === "claude" ? "Claude Code" : "modelo local"}</p>
      <p style="white-space:pre-wrap;margin:0 0 12px"><strong>Pedido:</strong> ${esc(t.pedido)}</p>
      ${t.erro ? `<p class="erro">${esc(t.erro)}</p>${/not logged in|\/login/i.test(t.erro) ? '<p class="sub">O Claude Code deste PC não está conectado à sua conta. Abra o Prompt de Comando, digite <code>claude</code>, Enter, depois <code>/login</code> e escolha a conta com assinatura. Depois clique em Tentar de novo (ou tente agora: sem a conexão, o agente usa o modelo local).</p>' : ""}` : ""}
      ${t.observacao ? `<p class="sub">${esc(t.observacao)}</p>` : ""}
      <div id="galeria-trabalho"></div>
      ${t.entrega ? `<details class="relatorio"${t.pasta ? "" : " open"}><summary>Relatório do agente</summary><div class="entrega">${esc(t.entrega)}</div></details>` : t.status === "executando" || t.status === "na_fila" ? '<p class="sub">Ainda sem entrega. Esta tela atualiza sozinha.</p>' : ""}
      ${pode ? `<div class="campos" style="margin-top:14px">${campo({ nome: "ajuste", rotulo: "Se quiser outra versão, diga o que mudar", tipo: "textarea", largo: true })}</div>` : ""}`,
    aoAbrir: () => galeriaTrabalho(t, $("#galeria-trabalho")),
    acoes: pode ? [
      ...excluir,
      ...(t.pasta ? [{ texto: "Abrir pasta", acao: async () => { await api("POST", `trabalhos/${t.id}/pasta`, {}); return false; } }] : []),
      { texto: "Pedir nova versão", acao: async (v) => {
        if (!v.ajuste.trim()) throw new Error("Escreva o que deve mudar na nova versão.");
        await api("POST", `trabalhos/${t.id}/refazer`, { ajuste: v.ajuste }); avisar("Nova versão na fila"); recarregar();
      } },
      { texto: "Fechar", acao: () => {} },
      { texto: "Aprovar", classe: "primario", acao: async () => { await api("POST", `trabalhos/${t.id}/aprovar`, {}); avisar("Entrega aprovada"); recarregar(); } },
    ] : [...excluir,
      ...(t.pasta ? [{ texto: "Abrir pasta", acao: async () => { await api("POST", `trabalhos/${t.id}/pasta`, {}); return false; } }] : []),
      ...(t.status === "erro" ? [{ texto: "Tentar de novo", classe: "primario", acao: async () => {
        await api("POST", `trabalhos/${t.id}/tentar`, {}); avisar("De volta à fila"); recarregar(); } }] : []),
      { texto: "Fechar", acao: () => {} }],
  });
}

ROTAS.agentes = async (param) => {
  const [lista, ags] = await Promise.all([api("GET", "trabalhos?limite=60"), api("GET", "agentes")]);
  const linhas = lista.map((t) => `<tr data-trab="${t.id}" style="cursor:pointer">
    <td>${t.id}</td><td>${esc(t.agente)}</td><td>${esc(t.cliente_nome || "—")}</td>
    <td class="pedido-curto" title="${esc(t.pedido)}">${esc(t.pedido.length > 60 ? `${t.pedido.slice(0, 60)}…` : t.pedido)}</td>
    <td class="status-${t.status}">${esc(STATUS_TRAB[t.status] || t.status)}</td>
    <td>${new Date(t.criado_em * 1000).toLocaleDateString("pt-BR")}</td>
    <td>${t.executor === "claude" ? "Claude Code" : "Modelo local"}</td></tr>`).join("");
  main.innerHTML = `
    <div class="topo"><div><h1>Agentes</h1><p class="sub">Peça um trabalho, acompanhe a fila e aprove as entregas.</p></div></div>
    <div class="colunas" style="grid-template-columns:minmax(0,1fr) minmax(0,1.6fr)">
      <section class="bloco"><h2>Pedir um trabalho</h2>
        <form id="delegar" class="campos">
          ${campo({ nome: "agente", rotulo: "Agente", tipo: "select", opcoes: ags.map((a) => [a.nome, `${a.titulo} (${a.executor === "claude" ? "Claude Code" : "local"})`]), largo: true })}
          ${campo({ nome: "cliente", rotulo: "Cliente", tipo: "select", opcoes: [["", "Sem cliente"], ...OPCOES.clientes.map((c) => [c.nome, c.nome])], largo: true })}
          ${campo({ nome: "pedido", rotulo: "O que o agente deve fazer", tipo: "textarea", largo: true, obrig: true })}
          <div class="largo"><button class="botao primario" type="submit">Enviar para a fila</button></div>
        </form>
        <p class="sub" style="font-size:13px">${esc(ags.map((a) => `${a.titulo}: ${a.descricao}`).join(" "))}</p></section>
      <section class="bloco"><h2>Trabalhos</h2>
        ${lista.length ? `<div class="tabela-caixa" style="border:0"><table><thead><tr><th>Nº</th><th>Agente</th><th>Cliente</th><th>Pedido</th><th>Situação</th><th>Pedido em</th><th>Feito por</th></tr></thead><tbody>${linhas}</tbody></table></div>`
          : '<p class="vazio">Nenhum trabalho ainda. Peça o primeiro ao lado ou pela voz ao Jarvis.</p>'}</section>
    </div>`;
  const recarregar = () => ROTAS.agentes();
  $("#delegar").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const r = await api("POST", "trabalhos", lerFormulario(e.target));
      avisar(`${r.aviso ? `${r.aviso} ` : ""}Trabalho ${r.trabalho.id} na fila`);
      recarregar();
    } catch (err) { avisar(err.message); }
  });
  $$("[data-trab]").forEach((tr) => tr.addEventListener("click", () => abrirTrabalho(+tr.dataset.trab, recarregar)));
  if (param) abrirTrabalho(+param, recarregar);
  clearInterval(navegar.timer);
  if (lista.some((t) => ["na_fila", "executando"].includes(t.status))) {
    navegar.timer = setInterval(() => { if (!$("#dialogo").open) recarregar(); }, 8000);
  }
};

// ── agenda (Google Agenda dentro do sistema) ──────────────────────────────
// Dia, semana e mês desenhados a partir dos eventos do Google Agenda. Clique
// num horário vazio para criar, num evento para editar; arraste para mover
// e puxe a borda de baixo para mudar o fim.
const AG_HORA = 48;                       // altura de uma hora na grade, em px
const AG_DIAS = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const AG_CORES = [["", "Padrão"], ["7", "Pavão"], ["9", "Mirtilo"], ["1", "Lavanda"], ["3", "Uva"], ["4", "Flamingo"],
  ["11", "Tomate"], ["6", "Tangerina"], ["5", "Banana"], ["2", "Sálvia"], ["10", "Manjericão"], ["8", "Grafite"]];
const AG = { vista: lembrar("central.agenda.vista", window.innerWidth < 600 ? "dia" : "semana"), ancora: new Date(), eventos: [] };

const agIso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const agHm = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
const agDia = (iso) => { const [a, m, d] = iso.slice(0, 10).split("-").map(Number); return new Date(a, m - 1, d); };
const agMais = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const agTextoCor = (hex) => { const n = parseInt(hex.slice(1), 16); const l = (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255; return l > 0.66 ? "#1F1F1F" : "#fff"; };

function agIntervalo() {
  const a = new Date(AG.ancora.getFullYear(), AG.ancora.getMonth(), AG.ancora.getDate());
  if (AG.vista === "dia") return [a, agMais(a, 1)];
  if (AG.vista === "semana") { const ini = agMais(a, -a.getDay()); return [ini, agMais(ini, 7)]; }
  const primeiro = new Date(a.getFullYear(), a.getMonth(), 1);
  const ini = agMais(primeiro, -primeiro.getDay());
  return [ini, agMais(ini, 42)];
}

function agTitulo() {
  const [ini, fim] = agIntervalo();
  const ultimo = agMais(fim, -1);
  if (AG.vista === "dia") return ini.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  if (AG.vista === "mes") return `${MESES_LONGOS[AG.ancora.getMonth()]} de ${AG.ancora.getFullYear()}`;
  const mesmoMes = ini.getMonth() === ultimo.getMonth();
  return `${ini.getDate()}${mesmoMes ? "" : ` de ${MESES[ini.getMonth()]}`} a ${ultimo.getDate()} de ${MESES[ultimo.getMonth()]} de ${ultimo.getFullYear()}`;
}

// Pedaços de cada evento por dia (um evento que vira a meia-noite aparece nos dois dias).
function agPedacos(dias) {
  const porDia = Object.fromEntries(dias.map((d) => [agIso(d), { todo: [], hora: [] }]));
  for (const ev of AG.eventos) {
    if (ev.dia_todo) {
      for (let d = agDia(ev.inicio); d < agDia(ev.fim); d = agMais(d, 1)) if (porDia[agIso(d)]) porDia[agIso(d)].todo.push(ev);
      continue;
    }
    const ini = new Date(ev.inicio), fim = new Date(ev.fim);
    for (let d = new Date(ini.getFullYear(), ini.getMonth(), ini.getDate()); d < fim; d = agMais(d, 1)) {
      const k = agIso(d);
      if (!porDia[k]) continue;
      const a = Math.max(0, (ini - d) / 6e4), b = Math.min(1440, (fim - d) / 6e4);
      if (b > a) porDia[k].hora.push({ ev, a, b });
    }
  }
  for (const k in porDia) {               // lado a lado quando se sobrepõem
    const lista = porDia[k].hora.sort((x, y) => x.a - y.a || y.b - x.b);
    let grupo = [], fimGrupo = -1;
    const fechar = () => { const cols = []; for (const p of grupo) { let c = cols.findIndex((f) => f <= p.a); if (c < 0) { c = cols.length; cols.push(0); } cols[c] = p.b; p.col = c; } grupo.forEach((p) => { p.ncols = cols.length; }); };
    for (const p of lista) { if (p.a >= fimGrupo && grupo.length) { fechar(); grupo = []; } grupo.push(p); fimGrupo = Math.max(fimGrupo, p.b); }
    if (grupo.length) fechar();
  }
  return porDia;
}

function agEventoHtml(p) {
  const { ev } = p, h = ((p.b - p.a) / 60) * AG_HORA;
  const larg = 100 / p.ncols, esq = p.col * larg;
  const ini = new Date(ev.inicio), fim = new Date(ev.fim);
  const curto = h < 34;
  return `<div class="ag-ev${curto ? " curto" : ""}${ev.editavel ? "" : " so-ler"}" data-ev="${esc(ev.id)}" tabindex="0"
      style="top:${(p.a / 60) * AG_HORA}px;height:${Math.max(h - 2, 16)}px;left:calc(${esq}% + 1px);width:calc(${p.col === p.ncols - 1 ? larg : larg * 1.15}% - 3px);--c:${ev.cor};color:${agTextoCor(ev.cor)}"
      title="${esc(`${ev.titulo}\n${agHm(ini)} – ${agHm(fim)}${ev.local ? `\n${ev.local}` : ""}`)}">
    <strong>${esc(ev.titulo)}</strong>${curto ? `<span>, ${agHm(ini)}</span>` : `<span>${agHm(ini)} – ${agHm(fim)}</span>`}
    ${ev.editavel ? '<i class="ag-alca" aria-hidden="true"></i>' : ""}</div>`;
}

function agGrade(dias) {
  const porDia = agPedacos(dias), hoje = agIso(new Date()), agora = new Date();
  const temTodo = dias.some((d) => porDia[agIso(d)].todo.length);
  const horas = Array.from({ length: 24 }, (_, h) => `<span style="top:${h * AG_HORA}px">${h ? `${String(h).padStart(2, "0")}:00` : ""}</span>`).join("");
  return `<div class="ag-semana" style="--dias:${dias.length};--hora:${AG_HORA}px">
    <div class="ag-cab"><div></div>${dias.map((d) => `<button class="ag-dia-cab${agIso(d) === hoje ? " hoje" : ""}" data-ir-dia="${agIso(d)}"><span>${AG_DIAS[d.getDay()]}</span><b>${d.getDate()}</b></button>`).join("")}</div>
    ${temTodo ? `<div class="ag-todo"><div class="ag-rot">dia todo</div>${dias.map((d) => `<div class="ag-todo-dia" data-novo-dia="${agIso(d)}">${porDia[agIso(d)].todo.map((ev) => `<div class="ag-chip" data-ev="${esc(ev.id)}" tabindex="0" style="--c:${ev.cor};color:${agTextoCor(ev.cor)}">${esc(ev.titulo)}</div>`).join("")}</div>`).join("")}</div>` : ""}
    <div class="ag-corpo" id="ag-corpo">
      <div class="ag-horas">${horas}</div>
      ${dias.map((d) => { const k = agIso(d); const min = agora.getHours() * 60 + agora.getMinutes();
        return `<div class="ag-col${k === hoje ? " hoje" : ""}" data-dia="${k}">${porDia[k].hora.map(agEventoHtml).join("")}${k === hoje ? `<div class="ag-agora" style="top:${(min / 60) * AG_HORA}px"></div>` : ""}</div>`; }).join("")}
    </div></div>`;
}

function agMes() {
  const [ini] = agIntervalo(), dias = Array.from({ length: 42 }, (_, i) => agMais(ini, i));
  const porDia = agPedacos(dias), hoje = agIso(new Date()), mes = AG.ancora.getMonth();
  return `<div class="ag-mes"><div class="ag-mes-cab">${AG_DIAS.map((d) => `<span>${d}</span>`).join("")}</div>
    <div class="ag-mes-grade">${dias.map((d) => { const k = agIso(d), p = porDia[k];
      const itens = [...p.todo.map((ev) => ({ ev, todo: true })), ...p.hora.filter((x) => x.a === Math.max(0, (new Date(x.ev.inicio) - d) / 6e4)).map((x) => ({ ev: x.ev }))];
      const vis = itens.slice(0, 3);
      return `<div class="ag-mes-dia${d.getMonth() !== mes ? " fora" : ""}${k === hoje ? " hoje" : ""}" data-novo-dia="${k}">
        <button class="ag-mes-num" data-ir-dia="${k}">${d.getDate()}</button>
        ${vis.map(({ ev, todo }) => todo ? `<div class="ag-chip" data-ev="${esc(ev.id)}" tabindex="0" style="--c:${ev.cor};color:${agTextoCor(ev.cor)}">${esc(ev.titulo)}</div>`
          : `<div class="ag-linha" data-ev="${esc(ev.id)}" tabindex="0"><i style="background:${ev.cor}"></i>${agHm(new Date(ev.inicio))} ${esc(ev.titulo)}</div>`).join("")}
        ${itens.length > 3 ? `<button class="ag-mais" data-ir-dia="${k}">+${itens.length - 3} mais</button>` : ""}</div>`; }).join("")}</div></div>`;
}

function agFormulario(ev, padrao) {
  const e = ev || padrao;
  const todo = !!e.dia_todo;
  const ini = todo ? null : new Date(e.inicio), fim = todo ? null : new Date(e.fim);
  const data = todo ? e.inicio.slice(0, 10) : agIso(ini);
  const dataFim = todo ? agIso(agMais(agDia(e.fim), -1)) : agIso(fim);
  return `<div class="campos">
    ${campo({ nome: "titulo", rotulo: "Título", valor: ev ? ev.titulo : "", largo: true, obrig: true })}
    ${campo({ nome: "dia_todo", rotulo: "Dia inteiro", tipo: "checkbox", valor: todo, largo: true })}
    ${campo({ nome: "data", rotulo: "Data", tipo: "date", valor: data })}
    <label class="ag-so-todo">Até<input type="date" name="data_fim" value="${dataFim}"></label>
    <label class="ag-so-hora">Início<input type="time" name="hora_ini" value="${ini ? agHm(ini) : "09:00"}" step="300"></label>
    <label class="ag-so-hora">Fim<input type="time" name="hora_fim" value="${fim ? agHm(fim) : "10:00"}" step="300"></label>
    ${campo({ nome: "local", rotulo: "Local", valor: e.local || "", largo: true })}
    ${campo({ nome: "descricao", rotulo: "Descrição", tipo: "textarea", valor: e.descricao || "", largo: true })}
    ${campo({ nome: "cor_id", rotulo: "Cor", tipo: "select", opcoes: AG_CORES, valor: e.cor_id || "" })}
  </div>`;
}

function agLerFormulario(v) {
  if (!v.titulo.trim()) throw new Error("Dê um nome ao evento.");
  const base = { titulo: v.titulo.trim(), local: v.local, descricao: v.descricao, cor_id: v.cor_id, dia_todo: v.dia_todo };
  if (v.dia_todo) return { ...base, inicio: v.data, fim: agIso(agMais(agDia(v.data_fim || v.data), 1)) };
  let dataFim = v.data;
  if (v.hora_fim <= v.hora_ini) dataFim = agIso(agMais(agDia(v.data), 1));     // passa da meia-noite
  return { ...base, inicio: `${v.data}T${v.hora_ini}`, fim: `${dataFim}T${v.hora_fim}` };
}

function agAlternarCampos(corpo) {
  const caixa = $('[name="dia_todo"]', corpo);
  const aplicar = () => { corpo.classList.toggle("ag-todo-on", caixa.checked); };
  caixa.addEventListener("change", aplicar); aplicar();
}

function agNovo(padrao, recarregar) {
  dialogo({
    titulo: "Novo evento", corpo: agFormulario(null, padrao), aoAbrir: agAlternarCampos,
    acoes: [{ texto: "Cancelar", acao: () => {} },
      { texto: "Criar no Google Agenda", classe: "primario", enviar: true, acao: async (v) => {
        await api("POST", "agenda/eventos", agLerFormulario(v)); avisar("Evento criado"); recarregar(); } }],
  });
}

function agAbrir(ev, recarregar) {
  if (!ev.editavel) {
    dialogo({ titulo: ev.titulo, corpo: `<p class="sub" style="margin-top:0">${ev.dia_todo ? "Dia inteiro" : `${agHm(new Date(ev.inicio))} – ${agHm(new Date(ev.fim))}`} · Feriado nacional (somente leitura)</p>`,
      acoes: [{ texto: "Fechar", classe: "primario", acao: () => {} }] });
    return;
  }
  dialogo({
    titulo: ev.titulo,
    corpo: `${ev.recorrente ? '<p class="sub" style="margin-top:0">Evento recorrente: a mudança vale só para esta ocorrência.</p>' : ""}${agFormulario(ev)}`,
    aoAbrir: agAlternarCampos,
    acoes: [
      { texto: "Excluir", classe: "perigo esquerda", acao: async () => {
        if (!(await confirmarExclusao(`Excluir "${ev.titulo}" do Google Agenda?`))) return false;
        await api("DELETE", `agenda/eventos/${encodeURIComponent(ev.id)}`); avisar("Evento excluído"); recarregar(); } },
      ...(ev.link ? [{ texto: "Abrir no Google", acao: () => { window.open(ev.link, "_blank"); return false; } }] : []),
      { texto: "Cancelar", acao: () => {} },
      { texto: "Salvar", classe: "primario", enviar: true, acao: async (v) => {
        await api("PATCH", `agenda/eventos/${encodeURIComponent(ev.id)}`, agLerFormulario(v)); avisar("Evento atualizado"); recarregar(); } },
    ],
  });
}

// Arrastar: mover (o evento inteiro) ou esticar (a alça de baixo). Passos de 15 min.
function agArrastar(recarregar) {
  const corpo = $("#ag-corpo");
  if (!corpo) return;
  $$(".ag-ev", corpo).forEach((el) => el.addEventListener("pointerdown", (e) => {
    const ev = AG.eventos.find((x) => x.id === el.dataset.ev);
    if (!ev || !ev.editavel || e.button !== 0) return;
    const esticar = e.target.classList.contains("ag-alca");
    const cols = $$(".ag-col", corpo), y0 = e.clientY, x0 = e.clientX, topo0 = el.offsetTop, alt0 = el.offsetHeight;
    const col0 = cols.indexOf(el.parentElement);
    let mexeu = false, dMin = 0, dDia = 0;
    el.setPointerCapture(e.pointerId);
    const mover = (m) => {
      if (!mexeu && Math.abs(m.clientY - y0) + Math.abs(m.clientX - x0) < 5) return;
      mexeu = true; el.classList.add("arrastando");
      dMin = Math.round(((m.clientY - y0) / AG_HORA) * 60 / 15) * 15;
      if (esticar) { el.style.height = `${Math.max(alt0 + (dMin / 60) * AG_HORA, AG_HORA / 4)}px`; return; }
      el.style.top = `${topo0 + (dMin / 60) * AG_HORA}px`;
      const alvo = cols.findIndex((c) => { const r = c.getBoundingClientRect(); return m.clientX >= r.left && m.clientX < r.right; });
      dDia = alvo < 0 ? dDia : alvo - col0;
      el.style.transform = `translateX(${dDia * (cols[0].getBoundingClientRect().width)}px)`;
    };
    const soltar = async () => {
      el.removeEventListener("pointermove", mover); el.removeEventListener("pointerup", soltar);
      if (!mexeu) { agAbrir(ev, recarregar); return; }
      const ini = new Date(ev.inicio), fim = new Date(ev.fim);
      let nIni = ini, nFim = new Date(fim.getTime() + dMin * 6e4);
      if (!esticar) { nIni = new Date(ini.getTime() + dMin * 6e4); nIni.setDate(nIni.getDate() + dDia); nFim = new Date(nIni.getTime() + (fim - ini)); }
      if (nFim <= nIni) nFim = new Date(nIni.getTime() + 15 * 6e4);
      try {
        await api("PATCH", `agenda/eventos/${encodeURIComponent(ev.id)}`, { inicio: `${agIso(nIni)}T${agHm(nIni)}`, fim: `${agIso(nFim)}T${agHm(nFim)}`, dia_todo: false });
        avisar(esticar ? `"${ev.titulo}" agora termina às ${agHm(nFim)}` : `"${ev.titulo}" movido para ${nIni.toLocaleDateString("pt-BR", { weekday: "short", day: "numeric" })}, ${agHm(nIni)}`);
      } catch (err) { avisar(err.message); }
      recarregar();
    };
    el.addEventListener("pointermove", mover); el.addEventListener("pointerup", soltar);
  }));
}

ROTAS.agenda = async () => {
  main.innerHTML = `<div class="ag">
    <div class="ag-barra">
      <div class="ag-nav"><button class="botao" id="ag-hoje">Hoje</button>
        <button class="botao-icone" id="ag-ant" aria-label="Anterior">‹</button><button class="botao-icone" id="ag-prox" aria-label="Próximo">›</button>
        <h1 id="ag-titulo"></h1></div>
      <div class="ag-acoes"><div class="grupo filtros" role="group" aria-label="Visão">${[["dia", "Dia"], ["semana", "Semana"], ["mes", "Mês"]].map(([v, t]) => `<button type="button" data-vista="${v}" aria-pressed="${AG.vista === v}">${t}</button>`).join("")}</div>
        <button class="botao primario" id="ag-novo">Novo evento</button></div>
    </div>
    <div id="ag-area" class="ag-area"><p class="sub">Carregando o Google Agenda…</p></div></div>`;
  let rolagem = null;
  const desenhar = async () => {
    const [ini, fim] = agIntervalo();
    $("#ag-titulo").textContent = agTitulo();
    $$("[data-vista]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.vista === AG.vista)));
    try {
      const r = await api("GET", `agenda/eventos?de=${agIso(ini)}&ate=${agIso(fim)}`);
      AG.eventos = r.eventos;
    } catch (e) {
      $("#ag-area").innerHTML = `<div class="bloco"><p class="erro" style="margin-top:0">Não consegui ler o Google Agenda: ${esc(e.message)}</p>
        <p class="sub">Se a conexão com o Google expirou, reconecte no PC: na pasta do Jarvis, rode <code>python connect_google_calendar.py</code> e autorize no navegador.</p></div>`;
      return;
    }
    const antiga = $("#ag-corpo");
    if (antiga) rolagem = antiga.scrollTop;
    const dias = Array.from({ length: Math.round((fim - ini) / 864e5) }, (_, i) => agMais(ini, i));
    $("#ag-area").innerHTML = AG.vista === "mes" ? agMes() : agGrade(dias);
    const corpo = $("#ag-corpo");
    if (corpo) {
      const agora = new Date();
      corpo.scrollTop = rolagem ?? Math.max(0, (dias.some((d) => agIso(d) === agIso(agora)) ? agora.getHours() - 2 : 7) * AG_HORA);
      corpo.addEventListener("click", (e) => {
        const col = e.target.closest(".ag-col");
        if (!col || e.target.closest(".ag-ev")) return;
        const min = Math.floor(((e.clientY - col.getBoundingClientRect().top) / AG_HORA) * 2) * 30;
        const ini = new Date(agDia(col.dataset.dia).getTime() + min * 6e4);
        agNovo({ inicio: ini.toISOString(), fim: new Date(ini.getTime() + 36e5).toISOString() }, desenhar);
      });
      agArrastar(desenhar);
    }
    $$("#ag-area [data-ev]:not(.ag-ev)").forEach((el) => {
      const abrir = (e) => { e.stopPropagation(); agAbrir(AG.eventos.find((x) => x.id === el.dataset.ev), desenhar); };
      el.addEventListener("click", abrir);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") abrir(e); });
    });
    $$("#ag-area .ag-ev").forEach((el) => el.addEventListener("keydown", (e) => { if (e.key === "Enter") agAbrir(AG.eventos.find((x) => x.id === el.dataset.ev), desenhar); }));
    $$("#ag-area [data-ir-dia]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); AG.ancora = agDia(b.dataset.irDia); AG.vista = "dia"; guardar("central.agenda.vista", "dia"); rolagem = null; desenhar(); }));
    $$("#ag-area [data-novo-dia]").forEach((c) => c.addEventListener("click", (e) => {
      if (e.target !== c) return;
      const d = agDia(c.dataset.novoDia);
      if (c.classList.contains("ag-todo-dia")) agNovo({ dia_todo: true, inicio: c.dataset.novoDia, fim: agIso(agMais(d, 1)) }, desenhar);
      else agNovo({ inicio: new Date(d.getTime() + 9 * 36e5).toISOString(), fim: new Date(d.getTime() + 10 * 36e5).toISOString() }, desenhar);
    }));
  };
  const andar = (n) => {
    const a = AG.ancora;
    AG.ancora = AG.vista === "mes" ? new Date(a.getFullYear(), a.getMonth() + n, 1) : agMais(a, n * (AG.vista === "dia" ? 1 : 7));
    rolagem = null; desenhar();
  };
  $("#ag-hoje").addEventListener("click", () => { AG.ancora = new Date(); rolagem = null; desenhar(); });
  $("#ag-ant").addEventListener("click", () => andar(-1));
  $("#ag-prox").addEventListener("click", () => andar(1));
  $$("[data-vista]").forEach((b) => b.addEventListener("click", () => { AG.vista = b.dataset.vista; guardar("central.agenda.vista", AG.vista); rolagem = null; desenhar(); }));
  $("#ag-novo").addEventListener("click", () => {
    const d = new Date(); d.setMinutes(0, 0, 0); d.setHours(d.getHours() + 1);
    agNovo({ inicio: d.toISOString(), fim: new Date(d.getTime() + 36e5).toISOString() }, desenhar);
  });
  await desenhar();
  clearInterval(navegar.timer);
  navegar.timer = setInterval(() => { if (!$("#dialogo").open && !document.hidden && !$(".ag-ev.arrastando")) desenhar().catch(() => {}); }, 60000);
};

// ── escritório ────────────────────────────────────────────────────────────
// A equipe de agentes como um escritório: cada um na sua mesa, com o que está
// fazendo agora num balão. Atualiza sozinho a cada poucos segundos.
const ESTADO_AGENTE = {
  trabalhando: "Trabalhando", esperando_voce: "Esperando você", erro: "Travou", na_fila: "Com tarefa na fila", livre: "Livre",
};
const SITUACAO_PROJ = { planejando: "Gerente planejando", andamento: "Em andamento", aguardando: "Esperando você", concluido: "Concluído", erro: "Com erro" };
const PELES = ["#F1C7A5", "#D9A47E", "#B07A55", "#7A4E33"];
const CABELOS = ["#2B1D14", "#4A3426", "#1B1B1B", "#7A5230", "#B9A48A"];

function hashNome(n) { let h = 0; for (const c of n) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h; }

function pessoa(a) {
  // Personagem original, desenhado aqui: cabeça, cabelo, corpo na cor do agente.
  const h = hashNome(a.nome), cor = a.cor || "#5E6E72";
  const pele = PELES[h % PELES.length], cabelo = CABELOS[(h >> 3) % CABELOS.length];
  const cabeloForma = (h >> 6) % 3;
  const cab = [
    `<path d="M86 41c0-11 7-17 14-17s14 6 14 17c-3-6-8-8-14-8s-11 2-14 8z" fill="${cabelo}"/>`,
    `<path d="M85 44c-1-13 6-20 15-20s16 7 15 20c-2-4-4-6-6-7-5 3-13 3-18 0-2 1-4 3-6 7z" fill="${cabelo}"/>`,
    `<path d="M86 40c1-10 7-16 14-16 8 0 14 6 14 16l-1 9c-1-6-3-10-6-12-4 2-10 2-14 0-3 2-5 6-6 12z" fill="${cabelo}"/>`,
  ][cabeloForma];
  const trabalhando = a.estado === "trabalhando";
  const tela = trabalhando ? cor : a.estado === "erro" ? "#C2483B" : "#DCE3E2";
  const linhas = trabalhando ? `<g class="tela-linhas"><rect x="132" y="58" width="22" height="2.4" rx="1" fill="#fff" opacity=".85"/><rect x="132" y="64" width="16" height="2.4" rx="1" fill="#fff" opacity=".7"/><rect x="132" y="70" width="19" height="2.4" rx="1" fill="#fff" opacity=".55"/></g>` : "";
  const papeis = a.fila + a.esperando > 0 ? `<g><rect x="40" y="86" width="22" height="5" rx="1" fill="#fff" stroke="#C9D6D3"/><rect x="42" y="82" width="22" height="5" rx="1" fill="#fff" stroke="#C9D6D3"/><text x="53" y="80" text-anchor="middle" font-size="9" font-weight="700" fill="#5E6E72">${a.fila + a.esperando}</text></g>` : "";
  const mao = a.estado === "esperando_voce"
    ? `<path class="mao-erguida" d="M117 70l9-24" stroke="${cor}" stroke-width="7" stroke-linecap="round"/><circle class="mao-erguida" cx="127" cy="43" r="4.5" fill="${pele}"/>`
    : "";
  const bracos = a.estado === "esperando_voce"
    ? `<path d="M84 72l-6 16" stroke="${cor}" stroke-width="7" stroke-linecap="round"/>`
    : `<g class="${trabalhando ? "digitando" : ""}"><path d="M84 72l18 16" stroke="${cor}" stroke-width="7" stroke-linecap="round"/><path d="M116 72l-6 16" stroke="${cor}" stroke-width="7" stroke-linecap="round"/></g>`;
  const extra = a.estado === "livre" ? `<g class="xicara"><rect x="163" y="80" width="9" height="9" rx="2" fill="#fff" stroke="#9AA9AB"/><path d="M172 83h3v3h-3" fill="none" stroke="#9AA9AB"/><path class="vapor" d="M166 77c-2-3 2-4 0-7M170 77c-2-3 2-4 0-7" stroke="#9AA9AB" fill="none" stroke-linecap="round"/></g>` : "";
  return `<svg class="cena" viewBox="0 0 200 120" role="img" aria-label="${esc(a.titulo)}: ${esc(ESTADO_AGENTE[a.estado])}">
    <ellipse cx="100" cy="112" rx="78" ry="6" fill="#0B1D23" opacity=".06"/>
    <rect x="86" y="92" width="28" height="22" rx="4" fill="#C9D6D3"/>
    <path d="M78 64c0-8 10-12 22-12s22 4 22 12v28H78z" fill="${cor}"/>
    <rect x="94" y="46" width="12" height="9" fill="${pele}"/>
    <circle cx="100" cy="38" r="13" fill="${pele}"/>
    ${cab}
    ${a.estado === "livre" ? '<path d="M95 40h3M102 40h3" stroke="#0E1A1E" stroke-width="1.6" stroke-linecap="round"/>' : '<circle cx="96" cy="39" r="1.5" fill="#0E1A1E"/><circle cx="104" cy="39" r="1.5" fill="#0E1A1E"/>'}
    ${bracos}${mao}
    <rect x="24" y="88" width="152" height="8" rx="2" fill="#E6ECEB" stroke="#C9D6D3"/>
    <rect x="34" y="96" width="5" height="18" fill="#C9D6D3"/><rect x="161" y="96" width="5" height="18" fill="#C9D6D3"/>
    <rect x="126" y="50" width="34" height="27" rx="3" fill="${tela}" stroke="#0B1D23" stroke-width="2"/>${linhas}
    <rect x="140" y="77" width="6" height="11" fill="#0B1D23"/>
    ${papeis}${extra}
    ${a.estado === "erro" ? '<text x="143" y="70" text-anchor="middle" font-size="16" font-weight="800" fill="#fff">!</text>' : ""}
  </svg>`;
}

function balaoAgente(a) {
  const alvo = (t) => [t.titulo || t.pedido, t.cliente].filter(Boolean).join(" · ");
  if (a.estado === "trabalhando") return `Fazendo agora: ${alvo(a.atual)}`;
  if (a.estado === "esperando_voce") return `Terminei "${a.aprovar[0].titulo || a.aprovar[0].pedido.slice(0, 50)}". Pode conferir?`;
  if (a.estado === "erro") return /not logged in|\/login/i.test(a.erro.erro || "") ? "Travei: o Claude Code não está conectado à sua conta. Clique para ver como resolver." : `Travei: ${a.erro.erro || "erro sem detalhe"}`;
  if (a.estado === "na_fila") return `Próximo: ${alvo(a.proximo)}`;
  if (a.esperando) return `Aguardando a etapa anterior (${a.esperando})`;
  return a.ultimo ? `Livre. Último: ${alvo(a.ultimo)}` : "Livre";
}

function mesa(a) {
  return `<button class="mesa estado-${a.estado}" data-agente="${esc(a.nome)}" style="--cor:${esc(a.cor || "#5E6E72")}">
    <span class="balao">${esc(balaoAgente(a))}</span>
    ${pessoa(a)}
    <span class="mesa-nome">${esc(a.titulo)}</span>
    <span class="mesa-meta"><span class="ponto-estado"></span>${esc(a.estado === "livre" && a.esperando ? "Aguardando etapa anterior" : ESTADO_AGENTE[a.estado])}${a.fila > 1 || (a.fila && a.estado !== "na_fila") ? ` · ${a.fila} na fila` : ""}
      · ${a.executor === "claude" ? "Claude Code" : "local"}</span>
  </button>`;
}

function cartaoProjeto(p, cores) {
  const [feitas, total] = p.progresso;
  const etapas = p.etapas.filter((e) => e.agente !== "gerente" || p.situacao === "planejando");
  return `<article class="projeto sit-${p.situacao}">
    <div class="projeto-topo"><div><h3>${esc(p.titulo)}</h3><p class="sub">${esc(p.cliente_nome || "Sem cliente")} · <span class="sit">${esc(SITUACAO_PROJ[p.situacao] || p.situacao)}</span></p></div>
      <button class="botao-icone" data-apagar-proj="${p.id}" title="Excluir projeto" aria-label="Excluir projeto ${esc(p.titulo)}">✕</button></div>
    <div class="progresso" role="progressbar" aria-valuemin="0" aria-valuemax="${total}" aria-valuenow="${feitas}"><span style="width:${total ? (feitas / total) * 100 : 4}%"></span></div>
    <ol class="etapas">${etapas.map((e) => `<li><button class="etapa st-${e.status}" data-trab="${e.id}" style="--cor:${esc(cores[e.agente] || "#5E6E72")}" title="${esc(STATUS_TRAB[e.status] || e.status)}">
      <span class="etapa-ponto"></span>${esc(e.titulo || e.agente)}${e.aprovacao && e.status !== "aprovado" ? ' <span class="etapa-aprova" title="Precisa da sua aprovação">✓?</span>' : ""}</button></li>`).join("")}</ol>
  </article>`;
}

function novoProjeto(recarregar) {
  api("GET", "marcas").then((ms) => {
    const sel = $("#np-marca");
    if (sel) sel.insertAdjacentHTML("beforeend", ms.filter((m) => m.pasta).map((m) => `<option value="${esc(m.nome)}">${esc(m.nome)}${m.cliente_nome ? ` (${esc(m.cliente_nome)})` : ""}</option>`).join(""));
  }).catch(() => {});
  dialogo({
    titulo: "Novo projeto",
    corpo: `<p class="sub" style="margin-top:0">Descreva o que o cliente precisa. O gerente monta o plano, distribui as etapas para a equipe e te chama para aprovar nos pontos importantes.</p>
      <div class="campos">
        ${campo({ nome: "cliente", rotulo: "Cliente", tipo: "select", opcoes: [["", "Sem cliente"], ...OPCOES.clientes.map((c) => [c.nome, c.nome])], largo: true })}
        <label class="largo">Pasta do cliente (onde estão logos e fotos, e onde os arquivos serão salvos)<select name="marca" id="np-marca"><option value="">Automático (pela marca citada ou pelo cliente)</option></select></label>
        ${campo({ nome: "pedido", rotulo: "O que o projeto precisa", tipo: "textarea", largo: true, obrig: true })}
      </div>`,
    acoes: [
      { texto: "Cancelar", acao: () => {} },
      { texto: "Começar projeto", classe: "primario", enviar: true, acao: async (v) => {
        if (!v.pedido.trim()) throw new Error("Descreva o que o projeto precisa.");
        const r = await api("POST", "projetos", v);
        if (r.aviso) avisar(r.aviso);
        avisar(`${r.aviso ? `${r.aviso} ` : ""}Projeto aberto: o gerente está montando o plano`);
        recarregar();
      } },
    ],
  });
}

function fichaAgente(a, recarregar) {
  const itens = [...(a.atual ? [a.atual] : []), ...a.aprovar, ...(a.erro ? [a.erro] : []), ...(a.proximo ? [a.proximo] : [])];
  dialogo({
    titulo: a.titulo,
    corpo: `<p class="sub" style="margin-top:0">${esc(a.descricao)}<br>Feito por ${a.executor === "claude" ? "Claude Code (assinatura)" : "modelo local"}.</p>
      ${itens.length ? `<ul class="lista">${itens.map((t) => `<li><a href="#" data-abrir="${t.id}">${esc(t.titulo || t.pedido.slice(0, 70))}</a><span class="meta status-${t.status}">${esc(STATUS_TRAB[t.status] || t.status)}</span></li>`).join("")}</ul>` : '<p class="vazio">Sem trabalhos agora.</p>'}`,
    acoes: [{ texto: "Pedir um trabalho só para ele", acao: () => { location.hash = "#/agentes"; } }, { texto: "Fechar", classe: "primario", acao: () => {} }],
    aoAbrir: (corpo) => $$("[data-abrir]", corpo).forEach((l) => l.addEventListener("click", (e) => { e.preventDefault(); abrirTrabalho(+l.dataset.abrir, recarregar); })),
  });
}

ROTAS.escritorio = async () => {
  main.innerHTML = `
    <div class="topo"><div><h1>Escritório</h1><p class="sub" id="esc-resumo">Sua equipe da HAIZEN trabalhando agora.</p></div>
      <button class="botao primario" id="novo-projeto">Novo projeto</button></div>
    <section class="chao" id="chao" aria-label="Mesas dos agentes"></section>
    <section class="bloco" style="margin-top:20px"><h2>Projetos</h2><div id="projetos" class="projetos"></div></section>`;
  let dados = null;
  const desenhar = async () => {
    dados = await api("GET", "escritorio");
    const cores = Object.fromEntries(dados.agentes.map((a) => [a.nome, a.cor]));
    const ordem = { trabalhando: 0, esperando_voce: 1, erro: 2, na_fila: 3, livre: 4 };
    const agentes = [...dados.agentes].sort((x, y) => (x.nome === "gerente" ? -1 : y.nome === "gerente" ? 1 : ordem[x.estado] - ordem[y.estado]));
    $("#chao").innerHTML = agentes.map(mesa).join("");
    const n = (e) => dados.agentes.filter((a) => a.estado === e).length;
    const aprovar = dados.agentes.reduce((s, a) => s + a.aprovar.length, 0);
    $("#esc-resumo").textContent = [n("trabalhando") ? `${n("trabalhando")} trabalhando` : "Ninguém trabalhando agora",
      aprovar ? `${aprovar} ${aprovar === 1 ? "entrega esperando" : "entregas esperando"} você` : "",
      dados.agentes.reduce((s, a) => s + a.fila, 0) ? `${dados.agentes.reduce((s, a) => s + a.fila, 0)} na fila` : ""].filter(Boolean).join(" · ");
    $("#projetos").innerHTML = dados.projetos.length ? dados.projetos.map((p) => cartaoProjeto(p, cores)).join("")
      : '<p class="vazio">Nenhum projeto ainda. Clique em Novo projeto, ou diga ao Jarvis: "abre um projeto para a Padaria Sol: site e campanha de lançamento".</p>';
    $$("[data-agente]").forEach((b) => b.addEventListener("click", () => fichaAgente(dados.agentes.find((a) => a.nome === b.dataset.agente), desenhar)));
    $$("#projetos [data-trab]").forEach((b) => b.addEventListener("click", () => abrirTrabalho(+b.dataset.trab, desenhar)));
    $$("[data-apagar-proj]").forEach((b) => b.addEventListener("click", async () => {
      if (!(await confirmarExclusao("Excluir este projeto, as etapas e os arquivos das entregas? Não dá para desfazer."))) return;
      try { await api("DELETE", `projetos/${b.dataset.apagarProj}`); avisar("Projeto excluído"); desenhar(); } catch (e) { avisar(e.message); }
    }));
    atualizarSelo();
  };
  $("#novo-projeto").addEventListener("click", () => novoProjeto(desenhar));
  await desenhar();
  clearInterval(navegar.timer);
  navegar.timer = setInterval(() => { if (!$("#dialogo").open && !document.hidden) desenhar().catch(() => {}); }, 3000);
};

// ── Jarvis (conversa por texto e voz) ─────────────────────────────────────
const JARVIS_NOMES = {
  haizen: "agentes da HAIZEN", central: "central", lembrar: "memória", buscar_memoria: "memória",
  open_app: "abrir app", computer_settings: "ajustes do PC", web_search: "pesquisa na web",
  reminder: "lembrete", weather_report: "clima", google_agenda: "agenda",
  computer_control: "teclado e mouse", browser_control: "navegador", file_controller: "arquivos",
  file_processor: "leitura de arquivo", code_helper: "código", dev_agent: "projeto de código",
  desktop_control: "área de trabalho", flight_finder: "voos", game_updater: "jogos",
  screen_task: "tarefa na tela", send_message: "mensagem", video_player: "vídeo",
  whatsapp_desktop_search: "contatos do WhatsApp", whatsapp_draft: "rascunho no WhatsApp",
  youtube_video: "YouTube",
};

async function apiBin(caminho, corpo) {
  const r = await fetch(`/api/${caminho}`, { method: "POST", headers: { "X-Central": "1", "Content-Type": "application/octet-stream" }, body: corpo });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.erro || `Erro ${r.status}`);
  return d;
}

async function tocar(texto) {
  const r = await fetch("/api/jarvis/falar", { method: "POST", headers: { "X-Central": "1", "Content-Type": "application/json" }, body: JSON.stringify({ texto }) });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.erro || "A voz não respondeu"); }
  const url = URL.createObjectURL(await r.blob());
  const som = new Audio(url);
  som.addEventListener("ended", () => URL.revokeObjectURL(url));
  JARVIS.som?.pause();
  JARVIS.som = som;
  const fim = new Promise((ok) => ["ended", "pause", "error"].forEach((ev) => som.addEventListener(ev, ok, { once: true })));
  await som.play();
  return fim;          // quem precisa (modo conversa) espera a fala terminar
}

// ── Modo conversa: ouve sem parar, responde em voz e volta a ouvir ───────────
// Detecta a fala pelo volume (com um piso de ruído que se ajusta ao ambiente).
// Enquanto transcreve e enquanto o Jarvis fala, ignora o microfone, para não
// responder à própria voz.
const CONVERSA = { ligada: false, estado: "parado", ctx: null, fluxo: null, antes: [], segmento: [],
                   fala: 0, silencio: 0, piso: 0.008, aoFrase: null, aoEstado: null };

async function ligarConversa(aoFrase, aoEstado) {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("Este navegador não libera o microfone. No celular, abra pelo endereço https do Tailscale.");
  CONVERSA.fluxo = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
  CONVERSA.ctx = new AudioContext({ sampleRate: 16000 });
  await CONVERSA.ctx.audioWorklet.addModule("/microfone.js");
  const fonte = CONVERSA.ctx.createMediaStreamSource(CONVERSA.fluxo);
  const no = new AudioWorkletNode(CONVERSA.ctx, "microfone");
  Object.assign(CONVERSA, { ligada: true, antes: [], segmento: [], fala: 0, silencio: 0, aoFrase, aoEstado });
  mudarConversa("ouvindo");
  no.port.onmessage = (e) => blocoConversa(e.data);
  fonte.connect(no);
}

function desligarConversa() {
  CONVERSA.ligada = false;
  CONVERSA.fluxo?.getTracks().forEach((t) => t.stop());
  CONVERSA.ctx?.close().catch(() => {});
  CONVERSA.ctx = CONVERSA.fluxo = null;
  mudarConversa("parado");
}

function mudarConversa(estado) {
  CONVERSA.estado = estado;
  CONVERSA.aoEstado?.(estado);
}

function blocoConversa(bloco) {
  if (!CONVERSA.ligada || !["ouvindo", "gravando"].includes(CONVERSA.estado)) return;
  const taxa = CONVERSA.ctx.sampleRate;
  const dur = bloco.length / taxa;
  let soma = 0;
  for (const v of bloco) soma += v * v;
  const rms = Math.sqrt(soma / bloco.length);
  const limiar = Math.max(0.012, CONVERSA.piso * 3);
  if (CONVERSA.estado === "ouvindo") {
    CONVERSA.antes.push(bloco);
    if (CONVERSA.antes.length > Math.ceil(0.3 / dur)) CONVERSA.antes.shift();      // 300 ms antes da fala
    if (rms < limiar) { CONVERSA.piso = CONVERSA.piso * 0.995 + rms * 0.005; CONVERSA.fala = 0; return; }
    CONVERSA.fala += dur;
    if (CONVERSA.fala < 0.15) return;
    CONVERSA.segmento = CONVERSA.antes.slice();
    CONVERSA.silencio = 0;
    mudarConversa("gravando");
    return;
  }
  CONVERSA.segmento.push(bloco);
  CONVERSA.silencio = rms < limiar ? CONVERSA.silencio + dur : 0;
  const total = CONVERSA.segmento.length * dur;
  if (CONVERSA.silencio < 0.9 && total < 25) return;          // fim da frase: ~1 s de silêncio
  const blocos = CONVERSA.segmento;
  CONVERSA.segmento = [];
  CONVERSA.antes = [];
  mudarConversa("pensando");
  const pcm = new Int16Array(blocos.reduce((n, b) => n + b.length, 0));
  let i = 0;
  for (const b of blocos) for (const v of b) pcm[i++] = Math.max(-1, Math.min(1, v)) * 0x7fff;
  Promise.resolve(CONVERSA.aoFrase(pcm, taxa))
    .catch((e) => avisar(e.message))
    .finally(() => { if (CONVERSA.ligada) mudarConversa("ouvindo"); });
}

const JARVIS = { gravando: false, blocos: [], ctx: null, fluxo: null, som: null, ocupado: false };

async function comecarGravacao() {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("Este navegador não libera o microfone. No celular, abra pelo endereço https do Tailscale.");
  JARVIS.fluxo = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
  JARVIS.ctx = new AudioContext({ sampleRate: 16000 });
  await JARVIS.ctx.audioWorklet.addModule("/microfone.js");
  const fonte = JARVIS.ctx.createMediaStreamSource(JARVIS.fluxo);
  const no = new AudioWorkletNode(JARVIS.ctx, "microfone");
  JARVIS.blocos = [];
  no.port.onmessage = (e) => JARVIS.blocos.push(e.data);
  fonte.connect(no);
  JARVIS.gravando = true;
}

async function pararGravacao() {
  JARVIS.gravando = false;
  const taxa = JARVIS.ctx.sampleRate;
  JARVIS.fluxo.getTracks().forEach((t) => t.stop());
  await JARVIS.ctx.close();
  const total = JARVIS.blocos.reduce((n, b) => n + b.length, 0);
  const pcm = new Int16Array(total);
  let i = 0;
  for (const b of JARVIS.blocos) for (const v of b) pcm[i++] = Math.max(-1, Math.min(1, v)) * 0x7fff;
  JARVIS.blocos = [];
  if (total < taxa * 0.3) return "";
  return (await apiBin(`jarvis/ouvir?taxa=${taxa}`, pcm.buffer)).texto;
}

function balao(m) {
  const origem = m.origem === "janela" ? '<span class="msg-origem">pela janela de voz</span>' : "";
  if (m.papel === "usuario") return `<div class="msg eu"><p>${esc(m.texto)}</p>${origem}</div>`;
  const acoes = (m.acoes || []).map((a) => JARVIS_NOMES[a] || a);
  return `<div class="msg ele"><p>${esc(m.texto)}</p>${acoes.length ? `<span class="msg-acoes">Usou: ${esc(acoes.join(", "))}</span>` : ""}${origem}</div>`;
}

function mostrarConfirmacao(c) {
  const el = $("#confirmacao");
  if (!el) return;
  if (!c) { el.hidden = true; return; }
  el.hidden = false;
  $("#conf-titulo").textContent = c.titulo;
}

ROTAS.jarvis = async () => (PONTE ? jarvisNativo() : jarvisWeb());

const jarvisWeb = async () => {
  const [estado, hist] = await Promise.all([api("GET", "jarvis/estado"), api("GET", "jarvis/historico")]);
  const voz = lembrar("central.voz", true);
  main.innerHTML = `
    <div class="jarvis">
      <div class="topo"><div><h1>Jarvis</h1><p class="sub">${esc(estado.onde)}${estado.modelo ? `, ${esc(estado.modelo)}` : ""}</p></div>
        <div class="jarvis-opcoes"><label class="voz-opcao"><input type="checkbox" id="voz"${voz ? " checked" : ""}${estado.voz ? "" : " disabled"}> Responder em voz</label>
        <label class="voz-opcao" title="No modo conversa, só responde quando a frase tiver o nome dele"><input type="checkbox" id="chamar"${lembrar("central.chamar", false) ? " checked" : ""}> Só quando eu disser "Jarvis"</label>
        <button class="botao" id="limpar">Limpar conversa</button></div></div>
      <div class="confirmacao" id="confirmacao" role="alert" hidden>
        <span><strong>Confirmar no PC:</strong> <span id="conf-titulo"></span></span>
        <span class="confirmacao-acoes"><button class="botao" id="conf-nao">Cancelar</button><button class="botao primario" id="conf-sim">Confirmar</button></span>
      </div>
      <div class="conversa" id="conversa" aria-live="polite">${hist.length ? hist.map(balao).join("") : `
        <div class="boas-vindas"><p>Pergunte sobre o faturamento, peça uma proposta a um agente ou mande o PC fazer algo.</p>
          <div class="sugestoes">
            <button class="sugestao">Como está o financeiro deste mês?</button>
            <button class="sugestao">Quais tarefas estão atrasadas?</button>
            <button class="sugestao">Quais agentes eu tenho?</button>
          </div></div>`}</div>
      <form class="compositor" id="compositor">
        <button type="button" class="microfone" id="mic" aria-pressed="false" ${estado.ouvido ? "" : "disabled title=\"Ouvido não configurado\""}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z" fill="currentColor"/></svg>
          <span id="mic-rotulo">Falar</span></button>
        <button type="button" class="botao conversa-botao" id="modo-conversa" aria-pressed="false" ${estado.ouvido ? "" : "disabled"}>Conversa</button>
        <textarea id="entrada" rows="1" placeholder="Escreva para o Jarvis" aria-label="Mensagem para o Jarvis"></textarea>
        <button class="botao primario" type="submit" id="enviar">Enviar</button>
      </form>
    </div>`;
  const conversa = $("#conversa");
  const rolar = () => { conversa.scrollTop = conversa.scrollHeight; };
  rolar();
  mostrarConfirmacao(estado.confirmacao);

  // O que foi dito na janela de voz do PC aparece aqui sem recarregar.
  const ultima = (h) => (h.length ? h[h.length - 1].criado_em : 0);
  let vista = ultima(hist);
  clearInterval(JARVIS.sincronia);
  JARVIS.sincronia = setInterval(async () => {
    if (!document.body.contains(conversa)) { clearInterval(JARVIS.sincronia); return; }
    if (JARVIS.ocupado || document.hidden) return;
    try {
      const h = await api("GET", "jarvis/historico");
      if (ultima(h) === vista || JARVIS.ocupado) return;
      vista = ultima(h);
      conversa.innerHTML = h.map(balao).join("");
      rolar();
    } catch (e) { /* PC ocupado ou sem rede: tenta de novo na próxima volta */ }
  }, 5000);

  const enviar = async (texto, porVoz = false, opcoes = {}) => {
    texto = texto.trim();
    if (!texto || JARVIS.ocupado) return null;
    JARVIS.ocupado = true;
    $(".boas-vindas", conversa)?.remove();
    conversa.insertAdjacentHTML("beforeend", balao({ papel: "usuario", texto }) + '<div class="msg ele pensando" id="pensando"><p>Pensando…</p></div>');
    rolar();
    $("#enviar").disabled = true;
    try {
      const r = await api("POST", "jarvis/mensagem", { texto, voz: porVoz });
      $("#pensando")?.remove();
      conversa.insertAdjacentHTML("beforeend", balao({ papel: "jarvis", texto: r.resposta, acoes: r.acoes }));
      rolar();
      vista = ultima(await api("GET", "jarvis/historico").catch(() => [])) || vista;
      mostrarConfirmacao(r.confirmacao);
      if (opcoes.falar !== false && $("#voz")?.checked) tocar(r.resposta).catch((e) => avisar(e.message));
      atualizarSelo();
      return r;
    } catch (e) {
      $("#pensando")?.remove();
      conversa.insertAdjacentHTML("beforeend", `<div class="msg ele erro-msg"><p>${esc(e.message)}</p></div>`);
      rolar();
      return null;
    } finally {
      JARVIS.ocupado = false;
      if ($("#enviar")) $("#enviar").disabled = false;
    }
  };

  const entrada = $("#entrada");
  entrada.addEventListener("input", () => { entrada.style.height = "auto"; entrada.style.height = `${Math.min(entrada.scrollHeight, 160)}px`; });
  entrada.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#compositor").requestSubmit(); } });
  $("#compositor").addEventListener("submit", (e) => { e.preventDefault(); const t = entrada.value; entrada.value = ""; entrada.style.height = "auto"; enviar(t); });
  $$(".sugestao", conversa).forEach((b) => b.addEventListener("click", () => enviar(b.textContent)));
  $("#voz").addEventListener("change", (e) => guardar("central.voz", e.target.checked));
  $("#limpar").addEventListener("click", async () => { await api("DELETE", "jarvis/historico"); ROTAS.jarvis(); });
  $("#conf-sim").addEventListener("click", async () => { await api("POST", "jarvis/confirmacao", { aceitar: true }); mostrarConfirmacao(null); avisar("Confirmado"); });
  $("#conf-nao").addEventListener("click", async () => { await api("POST", "jarvis/confirmacao", { aceitar: false }); mostrarConfirmacao(null); avisar("Cancelado"); });

  $("#chamar").addEventListener("change", (e) => guardar("central.chamar", e.target.checked));

  const botaoConversa = $("#modo-conversa");
  const ROTULOS = { ouvindo: "Ouvindo…", gravando: "Ouvindo você…", pensando: "Pensando…", falando: "Respondendo…" };
  const aoEstado = (estado) => {
    if (!document.body.contains(botaoConversa)) { desligarConversa(); return; }
    const ligada = estado !== "parado";
    botaoConversa.setAttribute("aria-pressed", String(ligada));
    botaoConversa.textContent = ligada ? `${ROTULOS[estado] || "Conversa"} (parar)` : "Conversa";
    $("#mic").disabled = ligada;
  };
  const aoFrase = async (pcm, taxa) => {
    if (pcm.length < taxa * 0.4) return;                         // estalo, não fala
    let texto = (await apiBin(`jarvis/ouvir?taxa=${taxa}`, pcm.buffer)).texto || "";
    if (!texto.trim()) return;
    if ($("#chamar")?.checked) {
      if (!/\bjarvis\b/i.test(texto)) return;                       // conversa de fundo
      texto = texto.replace(/^\W*(ei|ok|olá|oi)?\W*jarvis\W*/i, "") || texto;
    }
    const r = await enviar(texto, true, { falar: false });
    if (r?.resposta && CONVERSA.ligada) {
      mudarConversa("falando");
      await tocar(r.resposta).catch((e) => avisar(e.message));
    }
  };
  botaoConversa.addEventListener("click", async () => {
    if (CONVERSA.ligada) { desligarConversa(); return; }
    try {
      JARVIS.som?.pause();
      await ligarConversa(aoFrase, aoEstado);
      avisar("Modo conversa ligado. Fale normalmente; toque de novo para parar.");
    } catch (e) {
      desligarConversa();
      avisar(e.name === "NotAllowedError" ? "O navegador bloqueou o microfone. Libere nas permissões do site." : e.message);
    }
  });

  const mic = $("#mic");
  mic.addEventListener("click", async () => {
    try {
      if (!JARVIS.gravando) {
        JARVIS.som?.pause();
        await comecarGravacao();
        mic.setAttribute("aria-pressed", "true");
        $("#mic-rotulo").textContent = "Ouvindo… toque para enviar";
      } else {
        mic.setAttribute("aria-pressed", "false");
        mic.disabled = true;
        $("#mic-rotulo").textContent = "Transcrevendo…";
        const texto = await pararGravacao();
        mic.disabled = false;
        $("#mic-rotulo").textContent = "Falar";
        if (texto) enviar(texto, true); else avisar("Não ouvi nada. Fale um pouco mais perto do microfone.");
      }
    } catch (e) {
      JARVIS.gravando = false;
      mic.disabled = false;
      mic.setAttribute("aria-pressed", "false");
      $("#mic-rotulo").textContent = "Falar";
      avisar(e.message.includes("Permission") || e.name === "NotAllowedError" ? "O navegador bloqueou o microfone. Libere nas permissões do site." : e.message);
    }
  });

  // Confirmações que aparecem depois (uma ação do PC pedindo seu ok).
  navegar.timer = setInterval(async () => {
    try { mostrarConfirmacao((await api("GET", "jarvis/confirmacao")).confirmacao); } catch (_) { /* silencioso */ }
  }, 4000);
};

// ── versão nova no disco: avisar e reiniciar ────────────────────────────────
async function conferirVersao() {
  try {
    const v = await api("GET", "sistema/versao");
    $("#versao").hidden = !(v.desatualizado && v.pode_reiniciar);
    conferirVersao.pid = conferirVersao.pid || v.pid;
  } catch (_) { /* central reiniciando ou fora do ar */ }
}

$("#versao-reiniciar").addEventListener("click", async () => {
  const botao = $("#versao-reiniciar");
  botao.disabled = true;
  botao.textContent = "Reiniciando…";
  try { await api("POST", "sistema/reiniciar"); } catch (e) { avisar(e.message); botao.disabled = false; botao.textContent = "Reiniciar agora"; return; }
  const antigo = conferirVersao.pid;
  for (let i = 0; i < 120; i++) {               // até 4 minutos (o modelo local demora a subir)
    await new Promise((ok) => setTimeout(ok, 2000));
    try {
      const v = await api("GET", "sistema/versao");
      if (v.pid !== antigo) { location.reload(); return; }
    } catch (_) { /* ainda subindo */ }
  }
  botao.disabled = false;
  botao.textContent = "Reiniciar agora";
  avisar("O Jarvis não voltou sozinho. Abra de novo pelo atalho ou com py jarvis_web.py.");
});

conferirVersao();
setInterval(conferirVersao, 60000);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => { /* sem app instalável, a página funciona igual */ });
}

// ── WhatsApp ──────────────────────────────────────────────────────────────
const WA = { conversa: null, timer: null };   // conversa: {contato, mensagens, cliente}

ROTAS.whatsapp = async () => {
  clearTimeout(WA.timer);
  main.innerHTML = `
    <div class="topo"><div><h1>WhatsApp</h1><p class="sub">Suas conversas do WhatsApp, aqui no Jarvis. Abrir uma conversa a marca como lida.</p></div>
      <div class="wa-topo-acoes"><button class="botao" id="wa-atualizar">Atualizar</button></div></div>
    <div class="wa">
      <section class="bloco wa-lista">
        <h2>Conversas</h2>
        <div id="wa-lista"><p class="carregando">Abrindo o WhatsApp Web…</p></div>
        <form id="wa-abrir" class="wa-abrir"><input name="contato" placeholder="Abrir conversa pelo nome exato" aria-label="Nome do contato"><button class="botao" type="submit">Abrir</button></form>
      </section>
      <section class="bloco wa-conversa" id="wa-conversa"><p class="vazio">Escolha uma conversa para ler, responder ou transformar em tarefa e evento.</p></section>
    </div>`;
  const caixa = $("#wa-lista");
  const viva = () => document.body.contains(caixa);
  const carregarLista = async () => {
    caixa.innerHTML = '<p class="carregando">Lendo as conversas…</p>';
    try {
      const { conversas } = await api("GET", "whatsapp/recentes");
      if (!viva()) return;
      conversas.sort((a, b) => (b.nao_lidas > 0) - (a.nao_lidas > 0));
      caixa.innerHTML = conversas.length ? `<ul class="wa-itens">${conversas.map((c) => `
        <li><button type="button" data-contato="${esc(c.contato)}" class="${c.nao_lidas ? "tem-nao-lidas" : ""}"><span class="wa-nome">${esc(c.contato)}</span>${c.nao_lidas ? `<span class="selo">${c.nao_lidas}</span>` : "<span></span>"}
          <span class="wa-previa">${esc(c.previa)}</span></button></li>`).join("")}</ul>`
        : '<p class="vazio">Nenhuma conversa apareceu ainda. Clique em Atualizar em alguns segundos.</p>';
      $$("[data-contato]", caixa).forEach((b) => b.addEventListener("click", () => abrirConversaWa(b.dataset.contato)));
    } catch (e) { if (viva()) erroWa(e.message); }
  };
  const erroWa = (msg) => {
    caixa.innerHTML = `<p class="erro">${esc(msg)}</p><button class="botao" type="button" id="wa-tentar">Tentar de novo</button>`;
    $("#wa-tentar").addEventListener("click", conferir);
  };
  // Conectado? Pedindo QR? Ainda carregando? A tela acompanha até conectar.
  const conferir = async () => {
    clearTimeout(WA.timer);
    let e;
    try { e = await api("GET", "whatsapp/estado"); } catch (err) { e = { estado: "erro", erro: err.message }; }
    if (!viva()) return;
    if (e.estado === "ok") { await carregarLista(); return; }
    if (e.estado === "qr") {
      caixa.innerHTML = `<div class="wa-qr"><img alt="QR Code para conectar o WhatsApp" src="data:image/png;base64,${e.imagem}">
        <ol><li>No celular, abra o WhatsApp.</li><li>Toque em Configurações (ou ⋮) e depois em <strong>Aparelhos conectados</strong>.</li><li>Toque em <strong>Conectar um aparelho</strong> e aponte a câmera para este código.</li></ol>
        <p class="sub">O código muda a cada poucos segundos; esta tela acompanha sozinha.</p></div>`;
    } else if (e.estado === "carregando") {
      caixa.innerHTML = '<p class="carregando">Abrindo o WhatsApp Web… Na primeira vez pode levar até um minuto.</p>';
    } else { erroWa(e.erro || "Não consegui abrir o WhatsApp Web."); return; }
    WA.timer = setTimeout(() => { if (viva()) conferir(); }, e.estado === "qr" ? 4000 : 3000);
  };
  $("#wa-atualizar").addEventListener("click", conferir);
  $("#wa-abrir").addEventListener("submit", (e) => { e.preventDefault(); const n = e.target.contato.value.trim(); if (n) abrirConversaWa(n); });
  if (WA.conversa) desenharConversaWa();
  await conferir();
};

function msgWa(m) {
  if (m.tipo === "audio") {
    return `<div class="msg ${m.de === "eu" ? "eu" : "ele"} audio"><p><span class="msg-voz" aria-hidden="true">🎤</span> Mensagem de voz${m.duracao ? ` · ${esc(m.duracao)}` : ""}</p>
      ${m.transcricao ? `<p class="msg-transcricao">${esc(m.transcricao)}</p>` : `<button class="botao mini" type="button" data-ouvir="${esc(m.id)}">Transcrever</button>`}
      <span class="msg-acoes">${esc(m.hora)}</span></div>`;
  }
  return `<div class="msg ${m.de === "eu" ? "eu" : "ele"}${m.tipo === "midia" ? " midia" : ""}"><p>${esc(m.texto)}</p><span class="msg-acoes">${esc(m.hora)}</span></div>`;
}

async function abrirConversaWa(contato) {
  const caixa = $("#wa-conversa");
  caixa.innerHTML = `<p class="carregando">Abrindo a conversa com ${esc(contato)}…</p>`;
  try {
    WA.conversa = await api("GET", `whatsapp/conversa?contato=${encodeURIComponent(contato)}&n=20`);
    desenharConversaWa();
  } catch (e) { caixa.innerHTML = `<p class="erro">${esc(e.message)}</p>`; }
}

function desenharConversaWa() {
  const c = WA.conversa;
  const caixa = $("#wa-conversa");
  if (!c || !caixa) return;
  caixa.innerHTML = `
    <header class="wa-topo"><h2>${esc(c.contato)}</h2>${c.cliente ? `<a class="sub" href="#/clientes/${c.cliente.id}">Cliente da central: ${esc(c.cliente.nome)}</a>` : '<span class="sub">Não está nos clientes da central</span>'}</header>
    <div class="wa-msgs" id="wa-msgs">${c.mensagens.map(msgWa).join("") || '<p class="vazio">Sem mensagens.</p>'}</div>
    ${c.mensagens.some((m) => m.tipo === "audio" && !m.transcricao) ? '<p class="wa-audios-aviso"><button class="botao" type="button" id="wa-ouvir-todos">Transcrever todos os áudios</button> <span class="sub">O áudio é transcrito aqui no PC, sem sair dele.</span></p>' : ""}
    <div class="wa-acoes">
      <button class="botao" type="button" id="wa-sugerir">Sugerir resposta</button>
      <button class="botao" type="button" id="wa-tarefa">Criar tarefa</button>
      <button class="botao" type="button" id="wa-evento">Criar evento</button>
      <button class="botao" type="button" id="wa-livre">Ver disponibilidade</button>
    </div>
    <form class="compositor" id="wa-compositor">
      <textarea id="wa-texto" rows="2" placeholder="Escreva a resposta para ${esc(c.contato)}" aria-label="Resposta"></textarea>
      <button class="botao primario" type="submit">Enviar</button>
    </form>`;
  const msgs = $("#wa-msgs");
  msgs.scrollTop = msgs.scrollHeight;
  const transcrever = async (b) => {
    const m = c.mensagens.find((x) => x.id === b.dataset.ouvir);
    if (!m || m.transcricao) return;
    b.disabled = true; b.textContent = "Ouvindo…";
    try {
      const r = await api("POST", "whatsapp/transcrever", { contato: c.contato, id: m.id });
      Object.assign(m, { transcricao: r.texto, texto: `[áudio] ${r.texto}` });
      b.closest(".msg").outerHTML = msgWa(m);
      ligarOuvir();
    } catch (e) { avisar(e.message); b.disabled = false; b.textContent = "Transcrever"; }
  };
  const ligarOuvir = () => $$("[data-ouvir]", msgs).forEach((b) => { if (!b.dataset.ligado) { b.dataset.ligado = "1"; b.addEventListener("click", () => transcrever(b)); } });
  ligarOuvir();
  $("#wa-ouvir-todos")?.addEventListener("click", async (ev) => {
    ev.currentTarget.disabled = true;
    for (const b of $$("[data-ouvir]", msgs)) await transcrever(b);
    ev.currentTarget.closest("p")?.remove();
  });
  const dele = c.mensagens.filter((m) => m.de !== "eu").map((m) => m.texto);
  const resumo = dele.slice(-3).join("\n");
  $("#wa-sugerir").addEventListener("click", async (ev) => {
    const b = ev.currentTarget; b.disabled = true; b.textContent = "Pensando…";
    try { $("#wa-texto").value = (await api("POST", "whatsapp/sugerir", { contato: c.contato, mensagens: c.mensagens })).texto; }
    catch (e) { avisar(e.message); }
    finally { b.disabled = false; b.textContent = "Sugerir resposta"; }
  });
  $("#wa-tarefa").addEventListener("click", () => editarTarefa({
    titulo: `${c.contato}: ${(dele[dele.length - 1] || "").slice(0, 70)}`, cliente_id: c.cliente?.id ?? "",
    descricao: `Pedido pelo WhatsApp:\n${resumo}`,
  }, () => avisar("Tarefa criada")));
  $("#wa-evento").addEventListener("click", () => criarEventoWa(c.contato, resumo));
  $("#wa-livre").addEventListener("click", () => disponibilidadeWa(c.contato, resumo));
  $("#wa-compositor").addEventListener("submit", async (e) => {
    e.preventDefault();
    const texto = $("#wa-texto").value.trim();
    if (!texto) return;
    if (!(await confirmarEnvio(c.contato, texto))) return;
    try {
      await api("POST", "whatsapp/enviar", { contato: c.contato, texto });
      avisar(`Enviado para ${c.contato}`);
      abrirConversaWa(c.contato);
    } catch (err) { avisar(err.message); }
  });
}

const confirmarEnvio = (contato, texto) => new Promise((ok) => {
  const d = document.createElement("dialog");
  d.className = "confirmar";
  d.innerHTML = `<p><strong>Enviar para ${esc(contato)}?</strong></p><p class="wa-previa-envio">${esc(texto)}</p>
    <div class="dialogo-acoes"><button class="botao" value="nao">Cancelar</button><button class="botao primario" value="sim">Enviar</button></div>`;
  document.body.appendChild(d);
  d.addEventListener("click", (e) => { const v = e.target.closest("button")?.value; if (v) { d.close(); ok(v === "sim"); } });
  d.addEventListener("close", () => { d.remove(); ok(false); });
  d.showModal();
});

function amanhaIso() { const d = new Date(Date.now() + 864e5); return new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); }

function criarEventoWa(contato, resumo, pre = {}) {
  dialogo({
    titulo: "Novo evento no Google Agenda",
    corpo: `<div class="campos">
      ${campo({ nome: "titulo", rotulo: "Título", valor: pre.titulo || `${contato}`, largo: true, obrig: true })}
      ${campo({ nome: "dia", rotulo: "Dia", tipo: "date", valor: pre.dia || amanhaIso(), obrig: true })}
      ${campo({ nome: "inicio", rotulo: "Início", tipo: "time", valor: pre.inicio || "09:00", obrig: true })}
      ${campo({ nome: "fim", rotulo: "Fim", tipo: "time", valor: pre.fim || "10:00", obrig: true })}
      ${campo({ nome: "descricao", rotulo: "Descrição", tipo: "textarea", valor: `Pedido pelo WhatsApp (${contato}):\n${resumo}`, largo: true })}
    </div>`,
    acoes: [{ texto: "Cancelar", acao: () => {} },
      { texto: "Criar evento", classe: "primario", enviar: true, acao: async (v) => { await api("POST", "agenda/evento", v); avisar("Evento criado no Google Agenda"); } }],
  });
}

function disponibilidadeWa(contato, resumo) {
  dialogo({
    titulo: "Disponibilidade",
    corpo: `<div class="campos">${campo({ nome: "dia", rotulo: "Dia", tipo: "date", valor: amanhaIso(), largo: true })}</div><div id="wa-livres"><p class="carregando">Lendo o Google Agenda…</p></div>`,
    acoes: [{ texto: "Fechar", acao: () => {} }],
    aoAbrir: (corpo) => {
      const pintar = async () => {
        const dia = $("[name=dia]", corpo).value;
        const caixa = $("#wa-livres", corpo);
        caixa.innerHTML = '<p class="carregando">Lendo o Google Agenda…</p>';
        try {
          const r = await api("GET", `agenda/livre?dia=${dia}`);
          caixa.innerHTML = `<h3 class="wa-sub">Livre</h3>${r.livres.length ? `<ul class="wa-faixas">${r.livres.map(([a, b]) => `<li><span>${a} às ${b}</span><button type="button" class="botao" data-a="${a}" data-b="${b}">Marcar aqui</button></li>`).join("")}</ul>` : '<p class="vazio">Nada livre entre 8h e 19h.</p>'}
            <h3 class="wa-sub">Ocupado</h3>${r.ocupados.length ? `<ul class="wa-faixas">${r.ocupados.map((o) => `<li><span>${o.dia_todo ? "Dia todo" : `${o.ini} às ${o.fim}`}</span><span class="sub">${esc(o.titulo)}</span></li>`).join("")}</ul>` : '<p class="vazio">Nenhum compromisso.</p>'}`;
          $$("[data-a]", caixa).forEach((b) => b.addEventListener("click", () => {
            const fim = (() => { const [h, m] = b.dataset.a.split(":").map(Number); const t = h * 60 + m + 60; const lim = b.dataset.b; const s = `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`; return s < lim ? s : lim; })();
            criarEventoWa(contato, resumo, { dia, inicio: b.dataset.a, fim });
          }));
        } catch (e) { caixa.innerHTML = `<p class="erro">${esc(e.message)}</p>`; }
      };
      $("[name=dia]", corpo).addEventListener("change", pintar);
      pintar();
    },
  });
}

// ── Ponte com a janela do Jarvis ──────────────────────────────────────────
const ESTADOS = {
  LISTENING: ["ouvindo", "Ouvindo. Pode falar."],
  THINKING: ["pensando", "Pensando…"],
  SPEAKING: ["falando", "Respondendo"],
  MUTED: ["mudo", "Microfone desligado"],
  SLEEPING: ["dormindo", "Em espera"],
};
const PONTE_ESTADO = { desde: 0, linhas: [], ultimo: null };

function lerEstado(e) {
  if (e.agente === false) return ["desligado", "Jarvis desligado"];
  if (e.mudo) return ESTADOS.MUTED;
  if (e.dormindo) return ESTADOS.SLEEPING;
  return ESTADOS[e.estado] || ["ouvindo", "Pronto"];
}

function pintarSistema(e) {
  const pilula = $("#mic-global");
  pilula.setAttribute("aria-pressed", String(!e.mudo));
  $("#mic-global-rotulo").textContent = e.mudo ? "Microfone desligado" : "Microfone ligado";
  const ligado = e.agente !== false;
  const bAg = $("#agente-jarvis");
  bAg.hidden = false;
  bAg.dataset.ligado = String(ligado);
  $("#agente-rotulo").textContent = ligado ? "Desligar só o Jarvis" : "Ligar Jarvis";
  bAg.title = ligado ? "Desliga a voz e a conversa do Jarvis; a central, a agenda, o WhatsApp e os agentes continuam" : "Liga de novo a voz e a conversa do Jarvis";
  pilula.hidden = !ligado;
  const [classe, texto] = lerEstado(e);
  const ponto = $("#nav-estado");
  ponto.hidden = false;
  ponto.dataset.estado = classe;
  ponto.title = texto;
}

async function lacoPonte() {
  for (;;) {
    try {
      const e = await api("GET", `janela/estado?desde=${PONTE_ESTADO.desde}`);
      for (const l of e.atividade) {
        PONTE_ESTADO.linhas.push(l.texto);
        PONTE_ESTADO.desde = l.id;
      }
      PONTE_ESTADO.linhas = PONTE_ESTADO.linhas.slice(-150);
      PONTE_ESTADO.ultimo = e;
      pintarSistema(e);
      if (NATIVO) NATIVO(e);
    } catch (_) { /* janela ocupada ou reiniciando: tenta de novo */ }
    await new Promise((ok) => setTimeout(ok, document.hidden ? 5000 : 1000));
  }
}

$("#agente-jarvis").addEventListener("click", async () => {
  const b = $("#agente-jarvis");
  const ligar = b.dataset.ligado === "false";
  b.disabled = true;
  try {
    await api("POST", "janela/agente", { ligado: ligar });
    pintarSistema({ ...(PONTE_ESTADO.ultimo || {}), agente: ligar });
    avisar(ligar ? "Ligando o Jarvis…" : "Jarvis desligado. O resto do sistema continua funcionando.");
  } catch (e) { avisar(e.message); }
  finally { b.disabled = false; }
});

$("#mic-global").addEventListener("click", async () => {
  const ligado = $("#mic-global").getAttribute("aria-pressed") !== "true";
  try {
    await api("POST", "janela/microfone", { ligado });
    pintarSistema({ ...(PONTE_ESTADO.ultimo || {}), mudo: !ligado });
  } catch (e) { avisar(e.message); }
});

const AJUSTES = [
  ["audio", "Áudio", "Microfone e alto-falante usados pelo Jarvis"],
  ["memoria", "Memória", "O que o Jarvis guardou sobre você"],
  ["motor", "Modelo e voz", "Qual modelo responde, como ele ouve e fala"],
  ["personalizar", "Aparência e nome", "Nome do assistente e cores do visual clássico"],
  ["plugins", "Plugins", "Ligar e desligar extensões"],
  ["plugins_ajustes", "Ajustes dos plugins", "Configurações de cada extensão"],
  ["remoto", "Controle pelo celular", "Código para usar o Jarvis no celular"],
  ["classico", "Visual clássico", "Volta ao visual antigo, com o avatar (F9 alterna)"],
];
$("#abrir-ajustes").addEventListener("click", () => {
  dialogo({
    titulo: "Ajustes",
    corpo: `<ul class="lista-ajustes">${AJUSTES.map(([id, nome, desc]) =>
      `<li><button type="button" class="ajuste" data-ajuste="${id}"><strong>${esc(nome)}</strong><span>${esc(desc)}</span></button></li>`).join("")}</ul>`,
    acoes: [{ texto: "Fechar", acao: () => {} }],
    aoAbrir: (corpo) => $$(".ajuste", corpo).forEach((b) => b.addEventListener("click", async () => {
      try {
        await api("POST", "janela/ajuste", { nome: b.dataset.ajuste });
        $("#dialogo").close();
      } catch (e) { avisar(e.message); }
    })),
  });
});

// ── Tela Jarvis com a janela nativa ───────────────────────────────────────
async function jarvisNativo() {
  const [e, hist] = await Promise.all([api("GET", "janela/estado"), api("GET", "jarvis/historico")]);
  const nome = e.nome || "Jarvis";
  main.innerHTML = `
    <div class="jarvis nativo">
      <header class="jarvis-topo">
        <div class="orbe" id="orbe" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
        <div class="jarvis-titulo"><h1>${esc(nome)}</h1><p class="sub" id="jarvis-estado" role="status">…</p></div>
        <div class="jarvis-acoes">
          <button class="botao" type="button" id="acordar" hidden>Acordar</button>
          <button class="botao" type="button" id="interromper" hidden>Interromper</button>
          <button class="botao" type="button" id="ver-registro" aria-expanded="false" aria-controls="registro">Registro</button>
        </div>
      </header>
      <div class="jarvis-corpo">
        <div class="conversa" id="conversa" aria-live="polite"></div>
        <aside class="registro" id="registro" hidden aria-label="Registro do Jarvis"><ol id="registro-linhas"></ol></aside>
      </div>
      <form class="compositor" id="compositor">
        <textarea id="entrada" rows="1" placeholder="Fale ou escreva para o ${esc(nome)}" aria-label="Mensagem para o ${esc(nome)}"></textarea>
        <button class="botao primario" type="submit" id="enviar">Enviar</button>
      </form>
    </div>`;
  const conversa = $("#conversa");
  const rolar = () => { conversa.scrollTop = conversa.scrollHeight; };
  const vazio = `<div class="boas-vindas"><p>Fale com o ${esc(nome)} pelo microfone ou escreva aqui. Ele abre programas, mexe em arquivos, consulta a agenda e cuida do financeiro da HAIZEN.</p>
    <div class="sugestoes"><button class="sugestao" type="button">O que tenho na agenda hoje?</button><button class="sugestao" type="button">Como está o financeiro deste mês?</button><button class="sugestao" type="button">Abre o WhatsApp</button></div></div>`;
  let vista = hist.length ? hist[hist.length - 1].criado_em : 0;
  let aguardando = null;           // {desde, quando}: mensagem enviada esperando resposta
  const desenhar = (h) => {
    conversa.innerHTML = h.length ? h.map((m) => balao({ ...m, origem: "" })).join("") : vazio;
    if (aguardando) conversa.insertAdjacentHTML("beforeend", '<div class="msg ele pensando"><p>Pensando…</p></div>');
    $$(".sugestao", conversa).forEach((b) => b.addEventListener("click", () => enviar(b.textContent)));
    rolar();
  };
  desenhar(hist);

  const registro = $("#registro");
  const linhas = $("#registro-linhas");
  const pintarRegistro = () => {
    linhas.innerHTML = PONTE_ESTADO.linhas.slice(-80).map((l) => `<li>${esc(l.replace(/^SYS:\s*/, ""))}</li>`).join("");
    registro.scrollTop = registro.scrollHeight;
  };
  $("#ver-registro").addEventListener("click", (ev) => {
    registro.hidden = !registro.hidden;
    ev.currentTarget.setAttribute("aria-expanded", String(!registro.hidden));
    guardar("central.registro", !registro.hidden);
    if (!registro.hidden) pintarRegistro();
  });
  if (lembrar("central.registro", false)) $("#ver-registro").click();

  const enviar = async (texto) => {
    texto = (texto || "").trim();
    if (!texto) return;
    try {
      await api("POST", "janela/mensagem", { texto });
      aguardando = { quando: Date.now() };
      // Mostra na hora; o histórico de verdade chega com a resposta.
      $(".boas-vindas", conversa)?.remove();
      $(".pensando", conversa)?.remove();
      conversa.insertAdjacentHTML("beforeend", balao({ papel: "usuario", texto }) + '<div class="msg ele pensando"><p>Pensando…</p></div>');
      rolar();
    } catch (e) { avisar(e.message); }
  };
  const entrada = $("#entrada");
  entrada.addEventListener("input", () => { entrada.style.height = "auto"; entrada.style.height = `${Math.min(entrada.scrollHeight, 160)}px`; });
  entrada.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); $("#compositor").requestSubmit(); } });
  $("#compositor").addEventListener("submit", (ev) => { ev.preventDefault(); const t = entrada.value; entrada.value = ""; entrada.style.height = "auto"; enviar(t); });
  $("#acordar").addEventListener("click", () => api("POST", "janela/acordar").catch((er) => avisar(er.message)));
  $("#interromper").addEventListener("click", () => api("POST", "janela/interromper").catch((er) => avisar(er.message)));

  const orbe = $("#orbe");
  const pintar = async (est) => {
    const [classe, texto] = lerEstado(est);
    orbe.dataset.estado = classe;
    $("#jarvis-estado").textContent = est.dormindo ? "Em espera. Diga a palavra de ativação ou toque em Acordar." : texto;
    $("#acordar").hidden = !est.dormindo;
    $("#interromper").hidden = !["THINKING", "SPEAKING"].includes(est.estado) || est.mudo;
    if (!registro.hidden) pintarRegistro();
    if (est.ultima && est.ultima !== vista) {
      vista = est.ultima;
      const h = await api("GET", "jarvis/historico").catch(() => null);
      if (h) {
        const ultima = h[h.length - 1];
        if (aguardando && ultima && ultima.papel === "jarvis") aguardando = null;
        desenhar(h);
      }
    } else if (aguardando && Date.now() - aguardando.quando > 240000) {
      aguardando = null;
      $(".pensando", conversa)?.remove();
      avisar("O Jarvis não respondeu a tempo. Veja o Registro para saber o que aconteceu.");
    }
  };
  NATIVO = pintar;
  pintar(e);
}

$("#desligar-jarvis").addEventListener("click", async () => {
  const d = document.createElement("dialog");
  d.className = "confirmar";
  d.innerHTML = `<p><strong>Desligar tudo?</strong></p><p class="sub">A janela, a voz, a central, o WhatsApp e os agentes param. Para desligar só a voz do Jarvis, use "Desligar só o Jarvis". O que um agente estiver fazendo volta para a fila quando você abrir de novo pelo atalho da área de trabalho.</p>
    <div class="dialogo-acoes"><button class="botao" value="nao">Cancelar</button><button class="botao perigo" value="sim">Desligar</button></div>`;
  document.body.appendChild(d);
  const sim = await new Promise((ok) => {
    d.addEventListener("click", (e) => { const v = e.target.closest("button")?.value; if (v) { d.close(); ok(v === "sim"); } });
    d.addEventListener("close", () => { d.remove(); ok(false); });
    d.showModal();
  });
  if (!sim) return;
  try { await api("POST", "sistema/desligar"); } catch (e) { avisar(e.message); return; }
  clearInterval(navegar.timer);
  document.body.innerHTML = `<main class="desligado"><div><h1>Jarvis desligado</h1><p>Para ligar de novo, use o atalho <strong>Jarvis HAIZEN</strong> na área de trabalho.</p></div></main>`;
});

async function iniciar() {
  try { await api("GET", "janela/estado"); PONTE = true; } catch (_) { PONTE = false; }
  if (PONTE) {
    $("#sistema").hidden = false;
    $("#abrir-ajustes").hidden = !APP;     // os painéis abrem na tela do PC
    document.body.classList.add("ponte");
    lacoPonte();
  }
  navegar();
}
iniciar();

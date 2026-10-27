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

const confirmar = (texto) => new Promise((ok) => {
  dialogo({
    titulo: "Confirmar", corpo: `<p>${esc(texto)}</p>`,
    acoes: [{ texto: "Cancelar", acao: () => ok(false) }, { texto: "Apagar", classe: "perigo", acao: () => ok(true) }],
  });
});

// ── roteamento ────────────────────────────────────────────────────────────
const ROTAS = {};
const main = $("#conteudo");

async function navegar() {
  const [rota, param] = (location.hash.replace(/^#\/?/, "") || "painel").split("/");
  const tela = ROTAS[rota] ? rota : "painel";
  $$(".trilho nav a").forEach((a) => {
    if (a.dataset.rota === tela) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  clearInterval(navegar.timer);
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
const STATUS_TRAB = { na_fila: "Na fila", executando: "Em execução", aguardando_aprovacao: "Aguardando aprovação", aprovado: "Aprovado", rejeitado: "Refeito", erro: "Com erro" };

async function abrirTrabalho(id, recarregar) {
  const t = await api("GET", `trabalhos/${id}`);
  const pode = t.status === "aguardando_aprovacao";
  dialogo({
    titulo: `Trabalho ${t.id}, ${t.agente}`,
    corpo: `<p class="sub" style="margin-top:0">${esc(t.cliente_nome || "Sem cliente")}, <span class="status-${t.status}">${esc(STATUS_TRAB[t.status] || t.status)}</span>, feito por ${t.executor === "claude" ? "Claude Code" : "modelo local"}</p>
      <p style="white-space:pre-wrap;margin:0 0 12px"><strong>Pedido:</strong> ${esc(t.pedido)}</p>
      ${t.erro ? `<p class="erro">${esc(t.erro)}</p>` : ""}
      ${t.entrega ? `<div class="entrega">${esc(t.entrega)}</div>` : t.status === "executando" || t.status === "na_fila" ? '<p class="sub">Ainda sem entrega. Esta tela atualiza sozinha.</p>' : ""}
      ${pode ? `<div class="campos" style="margin-top:14px">${campo({ nome: "ajuste", rotulo: "Se quiser outra versão, diga o que mudar", tipo: "textarea", largo: true })}</div>` : ""}`,
    acoes: pode ? [
      { texto: "Pedir nova versão", classe: "esquerda", acao: async (v) => {
        if (!v.ajuste.trim()) throw new Error("Escreva o que deve mudar na nova versão.");
        await api("POST", `trabalhos/${t.id}/refazer`, { ajuste: v.ajuste }); avisar("Nova versão na fila"); recarregar();
      } },
      { texto: "Fechar", acao: () => {} },
      { texto: "Aprovar", classe: "primario", acao: async () => { await api("POST", `trabalhos/${t.id}/aprovar`, {}); avisar("Entrega aprovada"); recarregar(); } },
    ] : [{ texto: "Fechar", acao: () => {} }],
  });
}

ROTAS.agentes = async (param) => {
  const [lista, ags] = await Promise.all([api("GET", "trabalhos?limite=60"), api("GET", "agentes")]);
  const linhas = lista.map((t) => `<tr data-trab="${t.id}" style="cursor:pointer">
    <td>${t.id}</td><td>${esc(t.agente)}</td><td>${esc(t.cliente_nome || "—")}</td>
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
        ${lista.length ? `<div class="tabela-caixa" style="border:0"><table><thead><tr><th>Nº</th><th>Agente</th><th>Cliente</th><th>Situação</th><th>Pedido em</th><th>Feito por</th></tr></thead><tbody>${linhas}</tbody></table></div>`
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

navegar();

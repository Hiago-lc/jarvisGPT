"""Relatório mensal de tráfego para o cliente: os números do mês lidos no Meta
Ads (só leitura), num PDF com a cara da HAIZEN e uma mensagem curta pronta."""
from __future__ import annotations

import calendar
import datetime as dt
import html
import subprocess
import sys
import tempfile
from pathlib import Path

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro")


def _maiuscula(t: str) -> str:
    return (t[:1].upper() + t[1:]) if t else t


def nome_mes(mes: str) -> str:
    a, m = map(int, mes.split("-"))
    return f"{MESES[m - 1]} de {a}"


def _periodo(mes: str) -> tuple[str, str]:
    a, m = map(int, mes.split("-"))
    return f"{a:04d}-{m:02d}-01", f"{a:04d}-{m:02d}-{calendar.monthrange(a, m)[1]:02d}"


def prompt(c: dict, mes: str) -> str:
    ini, fim = _periodo(mes)
    a, m = map(int, mes.split("-"))
    ant = (dt.date(a, m, 1) - dt.timedelta(days=1))
    pini, pfim = _periodo(ant.strftime("%Y-%m"))
    return f"""Você é o gestor de tráfego sênior da agência HAIZEN preparando o relatório MENSAL para o cliente.
Conta de anúncio: {c['id']} ({c.get('nome')}), cliente: {c.get('cliente_nome') or '—'}.
Objetivo combinado: {c.get('objetivo') or 'não informado'}.{(' Resultado principal: ' + __import__('haizen.indicadores', fromlist=['x']).RESULTADOS_META.get(c['resultado'], c['resultado']) + '.') if c.get('resultado') else ''} Meta de custo por resultado: {c.get('meta_cpa') or '—'}.

Use SÓ ferramentas de leitura do meta-ads. Busque os insights da conta e das campanhas de {ini} a {fim} e, para
comparar, de {pini} a {pfim}. Também os 3 anúncios com melhor resultado no mês.
Nunca invente número: o que não conseguir ler fica null.

Responda SÓ com JSON:
{{"resumo": "3 a 4 frases para o DONO do negócio (sem jargão): o que o investimento trouxe e o destaque do mês",
 "nome_resultado": "ex.: conversas no WhatsApp, leads, compras",
 "kpis": {{"investimento": n, "resultados": n, "custo_por_resultado": n, "impressoes": n, "alcance": n,
          "cliques": n, "ctr": n, "cpm": n, "faturamento": n|null, "roas": n|null}},
 "anterior": {{"investimento": n, "resultados": n, "custo_por_resultado": n, "ctr": n}},
 "campanhas": [{{"nome": "", "investimento": n, "resultados": n, "custo_por_resultado": n}}],
 "destaques": [{{"anuncio": "", "resultado": "", "porque": "por que funcionou, 1 frase"}}],
 "aprendizados": ["2 a 4 aprendizados do mês em linguagem simples"],
 "proximos_passos": ["2 a 4 ações para o próximo mês"]}}"""


def coletar(c: dict, mes: str) -> dict:
    from haizen import trafego
    texto = trafego._claude(prompt(c, mes), trafego.ferramentas_leitura(),
                            "Leia os números do mês descrito na entrada só com ferramentas de leitura. Responda só com o JSON.",
                            f"relatório mensal {c['nome']} {mes}")
    return trafego._json(texto)


def _n(v, casas: int = 0, prefixo: str = "") -> str:
    if v is None or v == "":
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return html.escape(str(v))
    s = f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return prefixo + s


def _variacao(atual, anterior, menor_melhor: bool = False) -> str:
    try:
        a, b = float(atual), float(anterior)
    except (TypeError, ValueError):
        return ""
    if not b:
        return ""
    pct = (a - b) / b * 100
    bom = (pct < 0) if menor_melhor else (pct > 0)
    cls = "sobe" if bom else "desce"
    seta = "▲" if pct > 0 else "▼"
    return f'<span class="var {cls}">{seta} {abs(pct):.0f}% vs mês anterior</span>'


def html_relatorio(c: dict, mes: str, d: dict) -> str:
    e = html.escape
    k, ant = d.get("kpis") or {}, d.get("anterior") or {}
    cliente = c.get("cliente_nome") or c.get("nome") or ""
    res = d.get("nome_resultado") or "resultados"
    cards = [
        ("Investimento", _n(k.get("investimento"), 2, "R$ "), _variacao(k.get("investimento"), ant.get("investimento"))),
        (_maiuscula(res), _n(k.get("resultados")), _variacao(k.get("resultados"), ant.get("resultados"))),
        ("Custo por resultado", _n(k.get("custo_por_resultado"), 2, "R$ "),
         _variacao(k.get("custo_por_resultado"), ant.get("custo_por_resultado"), menor_melhor=True)),
        ("Pessoas alcançadas", _n(k.get("alcance")), ""),
        ("Cliques", _n(k.get("cliques")), ""),
        ("CTR", _n(k.get("ctr"), 2) + ("%" if k.get("ctr") is not None else ""), _variacao(k.get("ctr"), ant.get("ctr"))),
    ]
    if k.get("roas"):
        cards.append(("Retorno (ROAS)", _n(k.get("roas"), 2) + "x", ""))
    camp = "".join(f"<tr><td>{e(str(x.get('nome') or ''))}</td><td>{_n(x.get('investimento'), 2, 'R$ ')}</td>"
                   f"<td>{_n(x.get('resultados'))}</td><td>{_n(x.get('custo_por_resultado'), 2, 'R$ ')}</td></tr>"
                   for x in (d.get("campanhas") or [])[:8])
    dest = "".join(f"<li><b>{e(str(x.get('anuncio') or ''))}</b> — {e(str(x.get('resultado') or ''))}"
                   f"<br><span>{e(str(x.get('porque') or ''))}</span></li>" for x in (d.get("destaques") or [])[:3])
    lista = lambda xs: "".join(f"<li>{e(str(x))}</li>" for x in (xs or [])[:5])  # noqa: E731
    cards_html = "".join(f'<div class="card"><div class="rot">{e(t)}</div><div class="val">{v}</div>{var}</div>'
                         for t, v, var in cards)
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
@page {{ margin: 0 }}
html, body {{ width: 1240px }}
* {{ box-sizing: border-box }}
body {{ margin: 0; font-family: Inter, Arial, sans-serif; color: #14161c; background: #fff; }}
.capa {{ background: #0e0f13; color: #fff; padding: 64px 72px 48px; }}
.marca {{ letter-spacing: .32em; font-weight: 800; font-size: 15px; color: #c9ff3b }}
h1 {{ font-size: 46px; line-height: 1.05; margin: 28px 0 10px; font-weight: 800 }}
.sub {{ color: #a9adb8; font-size: 18px }}
main {{ padding: 40px 72px 56px }}
.resumo {{ font-size: 18px; line-height: 1.55; border-left: 4px solid #c9ff3b; padding: 4px 0 4px 18px; margin: 0 0 32px }}
.cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 34px }}
.card {{ border: 1px solid #e6e7eb; border-radius: 14px; padding: 18px 18px 16px }}
.rot {{ font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: #6b7080 }}
.val {{ font-size: 28px; font-weight: 800; margin-top: 6px }}
.var {{ font-size: 12px; font-weight: 600 }} .sobe {{ color: #12884a }} .desce {{ color: #c0392b }}
h2 {{ font-size: 20px; margin: 30px 0 12px }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px }}
th, td {{ text-align: left; padding: 10px 8px; border-bottom: 1px solid #eceef2 }}
th {{ color: #6b7080; font-weight: 600; font-size: 12px; text-transform: uppercase }}
ul {{ padding-left: 20px; line-height: 1.6 }} li span {{ color: #6b7080 }}
.duas {{ display: grid; grid-template-columns: 1fr 1fr; gap: 28px }}
footer {{ padding: 0 72px 40px; color: #8a8f9c; font-size: 12px }}
</style></head><body>
<section class="capa"><div class="marca">HAIZEN</div>
<h1>Relatório de tráfego<br>{e(_maiuscula(nome_mes(mes)))}</h1><div class="sub">{e(cliente)}</div></section>
<main>
<p class="resumo">{e(str(d.get('resumo') or ''))}</p>
<div class="cards">{cards_html}</div>
{f'<h2>Campanhas</h2><table><tr><th>Campanha</th><th>Investimento</th><th>{e(res)}</th><th>Custo</th></tr>{camp}</table>' if camp else ''}
{f'<h2>Anúncios destaque</h2><ul>{dest}</ul>' if dest else ''}
<div class="duas"><div><h2>O que aprendemos</h2><ul>{lista(d.get('aprendizados'))}</ul></div>
<div><h2>Próximos passos</h2><ul>{lista(d.get('proximos_passos'))}</ul></div></div>
</main>
<footer>Dados do Meta Ads de {e(nome_mes(mes))}. Relatório preparado pela HAIZEN.</footer>
</body></html>"""


def montar_pdf(c: dict, mes: str, d: dict, destino: Path) -> Path:
    from haizen import executor
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        h = Path(tmp) / "relatorio.html"
        h.write_text(html_relatorio(c, mes, d), encoding="utf-8")
        r = subprocess.run([sys.executable, str(executor.FERRAMENTAS), "render", str(h), str(destino), "--largura", "1240",
                            "--altura", "1754"], capture_output=True, text=True, errors="replace",
                           stdin=subprocess.DEVNULL, timeout=300)
        if r.returncode != 0 or not destino.is_file():
            raise RuntimeError(f"o PDF não foi gerado: {(r.stderr or r.stdout)[-400:]}")
    return destino


def mensagem_cliente(c: dict, mes: str, d: dict) -> str:
    k = d.get("kpis") or {}
    res = d.get("nome_resultado") or "resultados"
    linhas = [f"Oi! Segue o relatório de tráfego de {nome_mes(mes)}. 📊", ""]
    if k.get("investimento") is not None:
        linhas.append(f"• Investimento: {_n(k['investimento'], 2, 'R$ ')}")
    if k.get("resultados") is not None:
        linhas.append(f"• {_maiuscula(res)}: {_n(k['resultados'])}")
    if k.get("custo_por_resultado") is not None:
        linhas.append(f"• Custo por resultado: {_n(k['custo_por_resultado'], 2, 'R$ ')}")
    if d.get("resumo"):
        linhas += ["", str(d["resumo"])]
    if d.get("proximos_passos"):
        linhas += ["", "Para este mês: " + "; ".join(str(x) for x in d["proximos_passos"][:3]) + "."]
    linhas += ["", "O PDF completo está aqui. Qualquer dúvida, estou à disposição!"]
    return "\n".join(linhas)

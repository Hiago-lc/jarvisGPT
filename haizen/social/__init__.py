"""Social: o Instagram da própria HAIZEN — análise, raio-x, calendário, produção e publicação.

Fluxo:
1. Toda segunda (ou quando você pede) o Jarvis coleta o perfil, os posts e os
   números pela API oficial, baixa a grade e o Claude analisa: nota de 0 a 100,
   o que melhorar e o calendário da semana.
2. Você aprova os itens do calendário; cada um vira um trabalho da equipe
   (criativos para carrossel/estático, vídeo para reels) na pasta da HAIZEN.
3. Quando você aprova a peça no Escritório, o item fica "pronto": você revisa a
   legenda e publica agora ou agenda. Nada vai ao ar sem o seu clique.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from haizen import executor, store
from haizen.social import instagram

PLAYBOOK = Path(__file__).resolve().parent / "playbook.md"
TIMEOUT = int(os.environ.get("HAIZEN_SOCIAL_TIMEOUT", "900"))
FORMATOS = ("reels", "carrossel", "estatico", "stories")
STATUS = ("ideia", "aprovado", "produzindo", "pronto", "agendado", "publicando", "publicado", "descartado", "erro")
ESTADO = {"fazendo": "", "desde": 0.0, "erro": ""}
_TRAVA = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS social_analises (
    id INTEGER PRIMARY KEY, criado_em REAL NOT NULL, nota INTEGER, criterios TEXT NOT NULL DEFAULT '[]',
    resumo TEXT NOT NULL DEFAULT '', kpis TEXT NOT NULL DEFAULT '{}', melhores TEXT NOT NULL DEFAULT '[]',
    melhorias TEXT NOT NULL DEFAULT '[]', bio_sugerida TEXT NOT NULL DEFAULT '', relatorio TEXT NOT NULL DEFAULT '',
    erro TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS social_itens (
    id INTEGER PRIMARY KEY, criado_em REAL NOT NULL, atualizado_em REAL NOT NULL, origem TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL DEFAULT '', formato TEXT NOT NULL DEFAULT 'carrossel', pilar TEXT NOT NULL DEFAULT '',
    tema TEXT NOT NULL DEFAULT '', gancho TEXT NOT NULL DEFAULT '', roteiro TEXT NOT NULL DEFAULT '',
    legenda TEXT NOT NULL DEFAULT '', cta TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'ideia',
    trabalho_id INTEGER, arquivos TEXT NOT NULL DEFAULT '[]', publicar_em REAL, publicado_id TEXT NOT NULL DEFAULT '',
    permalink TEXT NOT NULL DEFAULT '', resultado TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS social_raiox (
    id INTEGER PRIMARY KEY, criado_em REAL NOT NULL, alvo TEXT NOT NULL, dados TEXT NOT NULL DEFAULT '{}',
    erro TEXT NOT NULL DEFAULT ''
);
"""


def _con():
    con = store.conexao()
    return con


def _garantir(con) -> None:
    con.executescript(_SCHEMA)


def _pasta(*partes) -> Path:
    from core.data_paths import data_dir
    p = Path(data_dir()).joinpath("social", *partes)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── configuração ────────────────────────────────────────────────────────────
# O que o token precisa ter: ler o perfil e os números, e publicar.
PERMISSOES = ("instagram_basic", "instagram_manage_insights", "instagram_content_publish", "pages_show_list",
              "pages_read_engagement", "pages_manage_posts", "business_management")

PADRAO = {"ig_id": "", "page_id": "", "username": "", "dia": 0, "horario": "08:00", "posts_semana": 4,
          "whatsapp_ativo": False, "ultima_rodada": "", "conectado_em": 0, "token_vence": 0,
          "token_faltando": []}


def _faltando(escopos: list) -> list:
    """Permissões que faltam. pages_manage_posts só é preciso sem ads_management (as imagens podem
    ser hospedadas pela biblioteca da conta de anúncios)."""
    falta = [e for e in PERMISSOES if e not in escopos]
    if "ads_management" in escopos and "pages_manage_posts" in falta:
        falta.remove("pages_manage_posts")
    return falta


def _arq_config() -> Path:
    from core.data_paths import data_dir
    return Path(data_dir()) / "social.json"


def config() -> dict:
    try:
        return {**PADRAO, **json.loads(_arq_config().read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(PADRAO)


def _gravar(c: dict) -> dict:
    _arq_config().write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return c


def salvar_config(m: dict) -> dict:
    c = config()
    if "horario" in m:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(m["horario"])):
            raise ValueError("horário no formato HH:MM")
        c["horario"] = m["horario"]
    if "dia" in m:
        c["dia"] = int(m["dia"]) % 7
    if "posts_semana" in m:
        c["posts_semana"] = max(1, min(14, int(m["posts_semana"])))
    if "whatsapp_ativo" in m:
        c["whatsapp_ativo"] = bool(m["whatsapp_ativo"])
    if "ig_id" in m:
        conta = next((x for x in instagram.contas() if x["ig_id"] == m["ig_id"]), None)
        if conta is None:
            raise ValueError("conta do Instagram não encontrada neste token")
        c.update(ig_id=conta["ig_id"], page_id=conta["page_id"], username=conta["username"])
    return _gravar(c)


def conectar(tk: str = "") -> dict:
    """Guarda o token (se veio), confere e escolhe a conta (a única, ou a que tem HAIZEN no nome)."""
    if tk:
        tk = instagram.conferir_formato(tk)
    try:
        contas = instagram.contas(tk or None)      # confere ANTES de trocar: um token ruim não apaga o que funcionava
    except instagram.ErroInstagram as e:
        raise ValueError(f"a Meta não aceitou este token, e o anterior continua guardado: {e}") from None
    if not contas:
        raise ValueError("o token não enxerga nenhum Instagram profissional ligado a uma Página. Confira se o "
                         "Instagram da HAIZEN é conta profissional, está ligado à Página e se as permissões foram marcadas.")
    if tk:
        instagram.salvar_token(tk)
    ESTADO["erro"] = ""
    c = config()
    info = instagram.info_do_token()
    if tk and info and "ads_management" in (info.get("escopos") or []):
        try:                                 # token único: o mesmo token passa a servir para o Tráfego
            from haizen.trafego import envio
            envio.salvar_token(tk)
            from haizen import trafego
            trafego._ENVIO_CACHE.clear()
        except Exception:  # noqa: BLE001
            pass
    c["token_vence"] = info.get("vence_em", 0) if info else c.get("token_vence", 0)
    if info:
        c["token_faltando"] = _faltando(info.get("escopos") or [])
    escolhida = next((x for x in contas if x["ig_id"] == c["ig_id"]), None) or \
        next((x for x in contas if "haizen" in (x["username"] + x["nome"]).lower()), None) or contas[0]
    c.update(ig_id=escolhida["ig_id"], page_id=escolhida["page_id"], username=escolhida["username"],
             conectado_em=time.time())
    _gravar(c)
    return {"contas": contas, "escolhida": escolhida}


def _ig() -> str:
    c = config()
    if not c["ig_id"]:
        raise ValueError("conecte o Instagram na aba Social")
    return c["ig_id"]


# ── coleta ──────────────────────────────────────────────────────────────────
def _baixar(url: str, destino: Path) -> Path | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "HAIZEN-Jarvis"}),
                                    timeout=60) as r:
            destino.write_bytes(r.read())
        return destino
    except Exception:  # noqa: BLE001 - uma imagem que não baixa não derruba a análise
        return None


def coletar() -> dict:
    ig = _ig()
    perfil = instagram.perfil(ig)
    posts = instagram.posts(ig, 30)
    conta = instagram.insights_da_conta(ig)
    grade = _pasta("grade")
    for f in grade.glob("*.jpg"):
        f.unlink()
    imagens = []
    for i, p in enumerate(posts[:12], 1):
        url = p.get("thumbnail_url") or p.get("media_url")
        if url and (arq := _baixar(url, grade / f"{i:02d}.jpg")):
            imagens.append(str(arq))
    dados = {"perfil": perfil, "insights_conta": conta, "posts": posts, "grade": imagens,
             "coletado_em": dt.datetime.now().isoformat(timespec="minutes")}
    (_pasta("coletas") / f"{dt.date.today().isoformat()}.json").write_text(
        json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    return dados


def _resumo_posts(posts: list[dict]) -> list[dict]:
    out = []
    for p in posts:
        ins = p.get("insights") or {}
        out.append({"id": p["id"], "data": (p.get("timestamp") or "")[:10], "formato": p.get("media_product_type")
                    if p.get("media_product_type") == "REELS" else p.get("media_type"),
                    "legenda": (p.get("caption") or "")[:300], "curtidas": p.get("like_count"),
                    "comentarios": p.get("comments_count"), **{k: v for k, v in ins.items() if v is not None},
                    "link": p.get("permalink")})
    return out


# ── Claude ──────────────────────────────────────────────────────────────────
def _claude(prompt: str, referencia: str, pastas: list[Path] | None = None, web: bool = False) -> dict:
    from haizen import uso
    modelo = uso.modelo("social") or "sonnet"
    ferramentas = ["Read"] + (["WebSearch", "WebFetch"] if web else [])
    args = ["-p", "Siga a entrada. Responda só com o JSON pedido.", "--output-format", "json",
            "--permission-mode", "dontAsk", "--allowedTools", ",".join(ferramentas), "--model", modelo]
    for d in pastas or []:
        args += ["--add-dir", str(d)]
    texto = executor._rodar_claude(args, prompt, _pasta("claude"), TIMEOUT, origem="social", referencia=referencia)
    bloco = re.search(r"```(?:json)?\s*(\{.*\})\s*```", texto, re.S)
    bruto = bloco.group(1) if bloco else texto[texto.find("{"):texto.rfind("}") + 1]
    try:
        return json.loads(bruto)
    except ValueError:
        raise ValueError("o Claude não devolveu o JSON combinado") from None


_ITEM_JSON = {"data": "AAAA-MM-DD", "formato": "reels | carrossel | estatico | stories", "pilar": "portfolio | educacao | bastidores | prova | oferta",
              "tema": "o assunto", "gancho": "primeira frase/tela", "roteiro": "reels: cenas com tempos e texto na tela; carrossel: o texto de cada lâmina",
              "legenda": "legenda completa pronta (gancho, corpo, CTA, 3 a 5 hashtags)", "cta": "a chamada"}


def _semana(hoje: dt.date) -> list[str]:
    seg = hoje + dt.timedelta(days=(7 - hoje.weekday()) % 7 or 0)
    return [(seg + dt.timedelta(days=i)).isoformat() for i in range(7)]


def prompt_analise(dados: dict, hoje: dt.date, historico: str) -> str:
    c = config()
    return "\n".join([
        PLAYBOOK.read_text(encoding="utf-8"), "",
        f"## Perfil @{dados['perfil'].get('username', '')} — dados de hoje ({hoje.isoformat()})",
        "```json", json.dumps({"perfil": dados["perfil"], "insights_conta_28d": dados["insights_conta"]},
                              ensure_ascii=False)[:4000], "```",
        "Posts recentes (do mais novo ao mais antigo):", "```json",
        json.dumps(_resumo_posts(dados["posts"]), ensure_ascii=False)[:24000], "```",
        "Imagens da grade (do mais novo ao mais antigo; abra com Read para ver a vitrine): "
        + (", ".join(dados.get("grade") or []) or "(sem imagens)"),
        "", "Análises anteriores (para medir evolução e não repetir ideias):", historico or "(primeira análise)", "",
        f"Monte o calendário para a semana de {_semana(hoje)[0]} a {_semana(hoje)[-1]} com {c['posts_semana']} posts.",
        "Responda SÓ com JSON:", "```json", json.dumps({
            "nota": 0, "criterios": [{"nome": "Bio e posicionamento", "nota": 0, "comentario": "uma frase"}],
            "resumo": "3 a 5 frases: como o perfil está e a prioridade da semana",
            "kpis": {"alcance_medio_post": 0, "taxa_engajamento_pct": 0, "salvamentos_medios": 0,
                     "compartilhamentos_medios": 0, "posts_por_semana": 0, "seguidores": 0},
            "melhores": [{"id": "id do post", "porque": "o que ele tem"}],
            "melhorias": [{"prioridade": "alta | media | baixa", "o_que": "...", "como": "passo a passo curto"}],
            "bio_sugerida": "bio nova pronta (até 150 caracteres)",
            "calendario": [_ITEM_JSON],
            "relatorio": "Markdown curto para o dono: números, o que funciona, o que parar, o foco da semana",
        }, ensure_ascii=False, indent=1), "```"])


def _historico() -> str:
    with store.conexao() as con:
        _garantir(con)
        rows = con.execute("SELECT criado_em, nota, resumo FROM social_analises WHERE erro='' ORDER BY id DESC LIMIT 4"
                           ).fetchall()
        temas = con.execute("SELECT tema, status FROM social_itens ORDER BY id DESC LIMIT 30").fetchall()
    linhas = [f"- {dt.date.fromtimestamp(r['criado_em']).isoformat()}: nota {r['nota']} — {r['resumo'][:250]}"
              for r in rows]
    if temas:
        linhas.append("Temas já usados ou planejados: " + "; ".join(f"{t['tema']} ({t['status']})" for t in temas))
    return "\n".join(linhas)


def analisar() -> dict:
    dados = coletar()
    hoje = dt.date.today()
    try:
        r = _claude(prompt_analise(dados, hoje, _historico()), "análise do perfil", [_pasta("grade")])
    except Exception as e:  # noqa: BLE001
        with store.conexao() as con:
            _garantir(con)
            con.execute("INSERT INTO social_analises(criado_em, erro) VALUES(?,?)", (time.time(), str(e)[:600]))
        raise
    return _guardar_analise(r)


def _guardar_analise(r: dict) -> dict:
    agora = time.time()
    with store.conexao() as con:
        _garantir(con)
        cur = con.execute(
            "INSERT INTO social_analises(criado_em, nota, criterios, resumo, kpis, melhores, melhorias, bio_sugerida,"
            " relatorio) VALUES(?,?,?,?,?,?,?,?,?)",
            (agora, int(r.get("nota") or 0), json.dumps(r.get("criterios") or [], ensure_ascii=False),
             str(r.get("resumo") or "")[:3000], json.dumps(r.get("kpis") or {}, ensure_ascii=False),
             json.dumps(r.get("melhores") or [], ensure_ascii=False), json.dumps(r.get("melhorias") or [], ensure_ascii=False),
             str(r.get("bio_sugerida") or "")[:300], str(r.get("relatorio") or "")[:30000]))
        aid = cur.lastrowid
        # Ideias antigas que você não aprovou dão lugar às novas.
        con.execute("UPDATE social_itens SET status='descartado', atualizado_em=? WHERE status='ideia' AND origem='analise'",
                    (agora,))
    for item in (r.get("calendario") or [])[:14]:
        criar_item(item, "analise")
    return analise(aid)


def analise(aid: int | None = None) -> dict | None:
    with store.conexao() as con:
        _garantir(con)
        r = con.execute("SELECT * FROM social_analises WHERE id=?" if aid else
                        "SELECT * FROM social_analises WHERE erro='' ORDER BY id DESC LIMIT 1",
                        (aid,) if aid else ()).fetchone()
    if r is None:
        return None
    d = dict(r)
    for k in ("criterios", "kpis", "melhores", "melhorias"):
        d[k] = json.loads(d[k] or "null")
    return d


# ── itens do calendário ────────────────────────────────────────────────────
def criar_item(item: dict, origem: str = "manual") -> dict:
    formato = str(item.get("formato") or "carrossel").lower().replace("á", "a").replace("é", "e")
    formato = formato if formato in FORMATOS else "carrossel"
    agora = time.time()
    with store.conexao() as con:
        _garantir(con)
        cur = con.execute(
            "INSERT INTO social_itens(criado_em, atualizado_em, origem, data, formato, pilar, tema, gancho, roteiro,"
            " legenda, cta) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (agora, agora, origem, str(item.get("data") or "")[:10], formato, str(item.get("pilar") or "")[:30],
             str(item.get("tema") or "")[:300], str(item.get("gancho") or "")[:400],
             str(item.get("roteiro") or "")[:6000], str(item.get("legenda") or "")[:2200],
             str(item.get("cta") or "")[:300]))
    return item_(cur.lastrowid)


def item_(iid: int) -> dict:
    with store.conexao() as con:
        _garantir(con)
        r = con.execute("SELECT * FROM social_itens WHERE id=?", (int(iid),)).fetchone()
    if r is None:
        raise KeyError(f"item {iid} não encontrado")
    d = dict(r)
    d["arquivos"] = json.loads(d["arquivos"] or "[]")
    return d


def itens(incluir_antigos: bool = False) -> list[dict]:
    with store.conexao() as con:
        _garantir(con)
        rows = con.execute("SELECT id FROM social_itens WHERE status != 'descartado' ORDER BY "
                           "CASE WHEN data='' THEN 1 ELSE 0 END, data, id" if not incluir_antigos else
                           "SELECT id FROM social_itens ORDER BY id DESC LIMIT 60").fetchall()
    return [item_(r["id"]) for r in rows]


def _mudar(iid: int, **campos) -> dict:
    permitidos = {"status", "trabalho_id", "arquivos", "publicar_em", "publicado_id", "permalink", "resultado",
                  "legenda", "data", "tema", "gancho", "roteiro", "cta", "formato"}
    sets = {k: (json.dumps(v, ensure_ascii=False) if k == "arquivos" else v) for k, v in campos.items() if k in permitidos}
    sets["atualizado_em"] = time.time()
    with store.conexao() as con:
        _garantir(con)
        con.execute(f"UPDATE social_itens SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), int(iid)))
    return item_(iid)


def editar_item(iid: int, campos: dict) -> dict:
    it = item_(iid)
    if it["status"] in ("publicando", "publicado"):
        raise ValueError("este post já foi publicado")
    permitidos = {k: str(v)[:6000] for k, v in campos.items() if k in ("legenda", "data", "tema", "gancho", "roteiro",
                                                                     "cta", "formato")}
    if "formato" in permitidos and permitidos["formato"] not in FORMATOS:
        raise ValueError("formato inválido")
    return _mudar(iid, **permitidos)


def descartar(iid: int) -> dict:
    return _mudar(iid, status="descartado")


_AGENTE = {"reels": "video", "carrossel": "criativos", "estatico": "criativos", "stories": "criativos"}
_ENTREGA = {"reels": "um reels vertical 1080x1920 (MP4, 15 a 40 s) com legenda na tela",
            "carrossel": "o carrossel completo em PNG 1080x1350, uma imagem por lâmina, numeradas",
            "estatico": "um post estático PNG 1080x1350",
            "stories": "a sequência de stories em PNG 1080x1920"}


def aprovar_item(iid: int) -> dict:
    """O item vira trabalho da equipe, na pasta da HAIZEN."""
    from haizen import servicos, worker
    it = item_(iid)
    if it["status"] not in ("ideia", "erro"):
        raise ValueError(f"o item está {it['status']}")
    pedido = (f"Post para o Instagram da própria HAIZEN ({it['formato']}, {it['data'] or 'esta semana'}). "
              f"Entregue {_ENTREGA[it['formato']]}, com a identidade visual da HAIZEN.\n"
              f"Tema: {it['tema']}\nGancho: {it['gancho']}\nRoteiro / lâminas:\n{it['roteiro']}\n"
              f"Legenda aprovada (não precisa reescrever; use para alinhar o texto das peças): {it['legenda']}")
    cli = store.buscar_cliente("HAIZEN")
    r = servicos.delegar(_AGENTE[it["formato"]], pedido, cli["nome"] if cli else "")
    worker.iniciar()
    return _mudar(iid, status="produzindo", trabalho_id=r["trabalho"]["id"], resultado=r.get("aviso") or "")


def sincronizar() -> None:
    """Itens em produção: quando você aprova a peça no Escritório, o item fica pronto."""
    for it in [i for i in itens() if i["status"] == "produzindo" and i["trabalho_id"]]:
        t = store.trabalho(it["trabalho_id"])
        if t is None:
            continue
        if t["status"] == "rejeitado":
            # Você pediu nova versão: segue o trabalho novo do mesmo agente com o mesmo pedido.
            novos = [x for x in store.listar_trabalhos(None, 200) if x["id"] > t["id"] and x["agente"] == t["agente"]
                     and x["pedido"].startswith(t["pedido"][:200])]
            if novos:
                _mudar(it["id"], trabalho_id=novos[-1]["id"])
            continue
        if t["status"] == "aprovado" and t.get("pasta") and Path(t["pasta"]).is_dir():
            finais = sorted(str(f) for f in Path(t["pasta"]).iterdir() if f.is_file()
                            and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".mp4", ".mov")
                            and not f.name.endswith(".instagram.jpg"))
            if finais:
                _mudar(it["id"], status="pronto", arquivos=finais[:10])
                try:
                    from haizen import notificar
                    notificar.avisar("Post pronto para publicar", it["tema"][:120], "aprovacao", "#/social")
                except Exception:  # noqa: BLE001
                    pass


def publicar_item(iid: int, quando: str = "", em_segundo_plano: bool = True) -> dict:
    """Sua ordem de publicar (agora ou no horário). Só itens prontos (peça aprovada)."""
    it = item_(iid)
    if it["status"] not in ("pronto", "agendado", "erro") or not it["arquivos"]:
        raise ValueError("o post ainda não está pronto (aprove a peça no Escritório antes)")
    if quando:
        momento = dt.datetime.fromisoformat(quando)
        if momento.timestamp() > time.time() + 60:
            return _mudar(iid, status="agendado", publicar_em=momento.timestamp(), resultado="")
    _mudar(iid, status="publicando", resultado="")
    if em_segundo_plano:
        threading.Thread(target=_publicar, args=(iid,), daemon=True, name=f"social-publicar-{iid}").start()
        return item_(iid)
    return _publicar(iid)


def _publicar(iid: int) -> dict:
    it = item_(iid)
    c = config()
    try:
        r = instagram.publicar(c["ig_id"], c["page_id"], [Path(a) for a in it["arquivos"]], it["legenda"])
        feito = _mudar(iid, status="publicado", publicado_id=r["id"], permalink=r.get("permalink", ""),
                       resultado="publicado")
        titulo, tipo = "Publicado no Instagram", "aprovacao"
    except Exception as e:  # noqa: BLE001
        feito = _mudar(iid, status="erro", resultado=str(e)[:600])
        titulo, tipo = "Instagram: a publicação falhou", "erro"
    try:
        from haizen import notificar
        notificar.avisar(titulo, it["tema"][:120], tipo, "#/social")
    except Exception:  # noqa: BLE001
        pass
    return feito


# ── raio-x de referência ────────────────────────────────────────────────────
def _quadros(video: Path, destino: Path) -> list[str]:
    from haizen.producao.ferramentas import ffmpeg
    saidas = []
    for i, s in enumerate((0.3, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 18.0)):
        alvo = destino / f"quadro-{i:02d}-{s:.0f}s.jpg"
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-ss", str(s), "-i", str(video), "-frames:v", "1",
                        "-vf", "scale=540:-2", str(alvo)], capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
        if alvo.is_file():
            saidas.append(str(alvo))
    return saidas


def _transcrever(video: Path) -> str:
    try:
        from haizen.producao.ferramentas import ffmpeg
        wav = video.with_suffix(".wav")
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(video), "-t", "45", "-ac", "1", "-ar", "16000",
                        str(wav)], capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        from core import transcrever
        return transcrever.transcrever(wav.read_bytes())[:3000]
    except Exception:  # noqa: BLE001 - sem áudio ou sem Whisper: segue só com as imagens
        return ""


def raio_x(alvo: str) -> dict:
    """Um perfil (@usuario) ou um post/reels (link) de referência: por que funciona e como adaptar."""
    alvo = (alvo or "").strip()
    m = re.search(r"instagram\.com/(?:reel|p|tv)/([\w-]+)", alvo)
    usuario = re.search(r"@([\w.]+)", alvo) or re.search(r"instagram\.com/([\w.]+)/?(?:$|\?)", alvo)
    if not usuario:
        raise ValueError("diga o @ do perfil (e, se quiser, o link do post): ex. \"@perfil https://instagram.com/reel/...\"")
    dados = instagram.outro_perfil(_ig(), usuario.group(1))
    post = None
    if m:
        post = next((p for p in dados["posts"] if m.group(1) in (p.get("permalink") or "")), None)
    pasta = _pasta("raiox", f"{int(time.time())}")
    imagens, fala = [], ""
    if post and post.get("media_type") == "VIDEO" and post.get("media_url"):
        video = _baixar(post["media_url"], pasta / "video.mp4")
        if video:
            imagens, fala = _quadros(video, pasta), _transcrever(video)
    elif post and (post.get("media_url") or post.get("thumbnail_url")):
        img = _baixar(post.get("media_url") or post.get("thumbnail_url"), pasta / "post.jpg")
        imagens = [str(img)] if img else []
    seguidores = dados.get("followers_count") or 0
    prompt = "\n".join([
        PLAYBOOK.read_text(encoding="utf-8"), "",
        f"## Raio-x de referência: @{dados.get('username')} ({seguidores} seguidores)",
        f"Bio: {dados.get('biography', '')}",
        "Post analisado:" if post else "Sem post específico: analise o perfil e os posts que mais performaram.",
        "```json", json.dumps(post or _resumo_posts(dados["posts"])[:25], ensure_ascii=False)[:12000], "```",
        ("Quadros do vídeo (abra com Read, em ordem de tempo): " + ", ".join(imagens)) if imagens else "",
        f"Fala dos primeiros 45 s (transcrição automática): {fala}" if fala else "",
        "Responda SÓ com JSON:", "```json", json.dumps({
            "titulo": "uma linha", "nota": 0, "gancho": "o que acontece nos 0 a 3 s e por que prende",
            "ritmo": "duração, cortes, mudanças de cena", "estrutura": "a sequência de ideias",
            "legenda": "o que a legenda faz", "cta": "a chamada usada", "numeros": "o que os números mostram",
            "por_que_funcionou": "3 motivos", "adaptacoes": [_ITEM_JSON]}, ensure_ascii=False, indent=1), "```"])
    r = _claude(prompt, f"raio-x @{dados.get('username')}", [pasta])
    with store.conexao() as con:
        _garantir(con)
        cur = con.execute("INSERT INTO social_raiox(criado_em, alvo, dados) VALUES(?,?,?)",
                          (time.time(), alvo[:300], json.dumps({**r, "usuario": dados.get("username"),
                                                                 "seguidores": seguidores,
                                                                 "link": (post or {}).get("permalink", "")},
                                                                ensure_ascii=False)))
    return raiox(cur.lastrowid)


def raiox(rid: int) -> dict:
    with store.conexao() as con:
        _garantir(con)
        r = con.execute("SELECT * FROM social_raiox WHERE id=?", (int(rid),)).fetchone()
    if r is None:
        raise KeyError("raio-x não encontrado")
    return {**dict(r), "dados": json.loads(r["dados"] or "{}")}


def raiox_lista(limite: int = 10) -> list[dict]:
    with store.conexao() as con:
        _garantir(con)
        rows = con.execute("SELECT id FROM social_raiox ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    return [raiox(r["id"]) for r in rows]


def adaptar(rid: int, i: int) -> dict:
    """Uma adaptação do raio-x vira item do calendário."""
    ad = (raiox(rid)["dados"].get("adaptacoes") or [])
    if not 0 <= int(i) < len(ad):
        raise KeyError("adaptação não encontrada")
    return criar_item(ad[int(i)], "raiox")


# ── segundo plano e agenda ──────────────────────────────────────────────────
def em_segundo_plano(fazer, rotulo: str) -> None:
    if not _TRAVA.acquire(blocking=False):
        raise RuntimeError(f"já estou {ESTADO['fazendo'] or 'trabalhando'}")
    ESTADO.update(fazendo=rotulo, desde=time.time(), erro="")

    def _rodar():
        try:
            fazer()
        except Exception as e:  # noqa: BLE001
            ESTADO["erro"] = str(e)[:800]
        finally:
            ESTADO["fazendo"] = ""
            _TRAVA.release()
    threading.Thread(target=_rodar, daemon=True, name=f"social-{rotulo}").start()


def hora_da_semana(agora: dt.datetime | None = None) -> bool:
    agora = agora or dt.datetime.now()
    c = config()
    if not c["ig_id"] or agora.weekday() != c["dia"] or c["ultima_rodada"] == agora.date().isoformat():
        return False
    h, m = map(int, c["horario"].split(":"))
    return (agora.hour, agora.minute) >= (h, m)


def rodada_semanal() -> None:
    c = config()
    c["ultima_rodada"] = dt.date.today().isoformat()
    _gravar(c)
    a = analisar()
    try:
        from haizen import notificar
        notificar.avisar(f"Instagram: nota {a['nota']}/100", "Análise da semana e calendário prontos para aprovar.",
                         "info", "#/social")
    except Exception:  # noqa: BLE001
        pass
    if config()["whatsapp_ativo"]:
        try:
            from haizen import trafego
            contato = trafego.config().get("whatsapp_contato")
            if contato:
                from core import whatsapp_web
                ideias = [i for i in itens() if i["status"] == "ideia"]
                texto = (f"Instagram da HAIZEN: nota {a['nota']}/100.\n{a['resumo']}\n\n"
                         f"{len(ideias)} post(s) no calendário da semana esperando sua aprovação na aba Social.")
                whatsapp_web.run_op({"op": "send", "recipient": contato, "text": texto}, timeout=60)
        except Exception as e:  # noqa: BLE001
            print(f"[Social] resumo no WhatsApp: {e}")


_AGENDA = {"thread": None}


def iniciar_agenda() -> None:
    if os.environ.get("HAIZEN_SOCIAL_AGENDA", "1") == "0":
        return
    if _AGENDA["thread"] and _AGENDA["thread"].is_alive():
        return

    def _laco():
        while True:
            try:
                sincronizar()
                agora = time.time()
                for it in [i for i in itens() if i["status"] == "agendado" and (i["publicar_em"] or 0) <= agora]:
                    _mudar(it["id"], status="publicando")
                    _publicar(it["id"])
                if hora_da_semana() and executor.claude_disponivel() and not ESTADO["fazendo"]:
                    em_segundo_plano(rodada_semanal, "analisando o perfil")
            except Exception as e:  # noqa: BLE001
                print(f"[Social] agenda: {e}")
            time.sleep(60)
    _AGENDA["thread"] = threading.Thread(target=_laco, daemon=True, name="social-agenda")
    _AGENDA["thread"].start()


def conferir_token(forcar: bool = False) -> None:
    """Uma vez por hora: até quando o token vale e se tem todas as permissões."""
    c = config()
    if not instagram.token() or (not forcar and time.time() - float(c.get("token_checado_em") or 0) < 3600):
        return
    info = instagram.info_do_token()
    c["token_checado_em"] = time.time()
    if info:
        c["token_vence"] = info.get("vence_em", 0)
        c["token_faltando"] = _faltando(info.get("escopos") or [])
    _gravar(c)


def painel() -> dict:
    try:
        conferir_token()
    except Exception:  # noqa: BLE001
        pass
    c = config()
    try:
        sincronizar()
    except Exception:  # noqa: BLE001
        pass
    return {"config": {**{k: c[k] for k in ("username", "dia", "horario", "posts_semana", "whatsapp_ativo", "ultima_rodada")},
                       "token_vence": c.get("token_vence", 0), "token_faltando": c.get("token_faltando") or []},
            "conectado": bool(c["ig_id"] and instagram.token()), "tem_token": bool(instagram.token()),
            "estado": dict(ESTADO), "analise": analise(), "itens": itens(), "raiox": raiox_lista(6)}

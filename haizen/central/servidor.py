"""Servidor da central: só biblioteca padrão, só no seu PC (127.0.0.1).

Proteções, porque um site qualquer aberto no navegador pode tentar falar com
um servidor em localhost:
  - toda chamada /api exige o cabeçalho X-Central, que uma página de outro
    site não consegue enviar sem a permissão do servidor (que não é dada);
  - o cabeçalho Host precisa ser localhost/127.0.0.1 (contra "DNS rebinding").
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from haizen import agentes, servicos, store, worker
from haizen.central import dados

ESTATICOS = Path(__file__).resolve().parent / "static"
PORTA = int(os.environ.get("HAIZEN_CENTRAL_PORTA", "8765"))
_HOSTS = {"127.0.0.1", "localhost"}
# Pelo Tailscale ("tailscale serve"), o pedido chega com o nome do PC na sua
# rede privada, que sempre termina em .ts.net. O servidor continua preso a
# 127.0.0.1: só o próprio Tailscale, rodando neste PC, consegue repassar.
_SUFIXOS_HOST = (".ts.net",)
_TIPOS = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
          ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json",
          ".webmanifest": "application/manifest+json"}


# ── versão do código que está rodando ───────────────────────────────────────
# Uma cópia do Jarvis que iniciou com o Windows fica rodando escondida com o
# código daquele momento. Comparando as datas dos arquivos, a página avisa que
# há uma versão nova no disco e oferece reiniciar.
RAIZ = Path(__file__).resolve().parents[2]
_PASTAS_CODIGO = ("haizen", "actions", "plugins", "core", "providers", "memory")


def versao_no_disco() -> float:
    ultima = 0.0
    for pasta in _PASTAS_CODIGO:
        for arq in (RAIZ / pasta).rglob("*"):
            if arq.suffix in (".py", ".js", ".css", ".html") and "__pycache__" not in arq.parts:
                try:
                    ultima = max(ultima, arq.stat().st_mtime)
                except OSError:
                    pass
    for arq in ("jarvis_web.py", "start_local.py"):
        try:
            ultima = max(ultima, (RAIZ / arq).stat().st_mtime)
        except OSError:
            pass
    return ultima


VERSAO_INICIAL = versao_no_disco()
# Definido por jarvis_web.py: como iniciar de novo. Sem ele (central aberta
# pela janela antiga), a página não oferece reiniciar.
COMANDO_REINICIO: list[str] | None = None


def desatualizado() -> bool:
    return versao_no_disco() > VERSAO_INICIAL + 1


def reiniciar() -> None:
    """Abre uma cópia nova (que espera a porta liberar) e encerra esta."""
    import subprocess
    import time
    if not COMANDO_REINICIO:
        raise ValueError("Esta central não foi aberta pelo jarvis_web.py; feche e abra de novo.")

    def _trocar():
        time.sleep(0.5)                       # deixa a resposta chegar à página
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.executable.lower().endswith("pythonw.exe") else 0
        subprocess.Popen(COMANDO_REINICIO, cwd=str(RAIZ), creationflags=flags)
        parar()
        os._exit(0)
    threading.Thread(target=_trocar, daemon=True).start()


def _trabalho(t: dict, com_entrega: bool = False) -> dict:
    out = dict(t)
    cli = store.cliente_por_id(t["cliente_id"])
    out["cliente_nome"] = cli["nome"] if cli else None
    if com_entrega and t.get("arquivo"):
        try:
            out["entrega"] = Path(t["arquivo"]).read_text(encoding="utf-8")
        except OSError:
            out["entrega"] = None
    return out


def _projeto(p: dict) -> dict:
    etapas = store.trabalhos_do_projeto(p["id"])
    cli = store.cliente_por_id(p["cliente_id"])
    validas = [t for t in etapas if t["status"] != "rejeitado"]
    if any(t["agente"] != "gerente" for t in validas):
        validas = [t for t in validas if t["agente"] != "gerente"]   # o plano já virou etapas
    feitas = sum(1 for t in validas if t["status"] == "aprovado")
    return {**p, "cliente_nome": cli["nome"] if cli else None,
            "situacao": servicos.situacao_projeto(etapas),
            "progresso": [feitas, len(validas)],
            "etapas": [{k: t[k] for k in ("id", "agente", "titulo", "status", "etapa", "aprovacao", "executor")}
                       for t in validas]}


def escritorio() -> dict:
    """Quem está fazendo o quê agora: a tela Escritório se monta com isto."""
    recentes = store.listar_trabalhos(None, 300)
    projetos = {p["id"]: p["titulo"] for p in store.listar_projetos(100)}
    clientes: dict = {}

    def cliente(cid):
        if cid not in clientes:
            c = store.cliente_por_id(cid)
            clientes[cid] = c["nome"] if c else None
        return clientes[cid]

    def resumo(t):
        return {"id": t["id"], "titulo": t.get("titulo") or "", "pedido": t["pedido"][:220],
                "status": t["status"], "cliente": cliente(t["cliente_id"]),
                "projeto": projetos.get(t.get("projeto_id")), "atualizado_em": t["atualizado_em"]}
    saida = []
    for a in agentes.listar():
        meus = [t for t in recentes if t["agente"] == a.nome]
        atual = next((t for t in meus if t["status"] == "executando"), None)
        fila = [t for t in meus if t["status"] == "na_fila"]
        esperando = [t for t in meus if t["status"] == "esperando"]
        aprovar = [t for t in meus if t["status"] == "aguardando_aprovacao"]
        # Só o erro mais recente conta: depois de um trabalho bem feito, ele some.
        erro = meus[0] if meus and meus[0]["status"] == "erro" else None
        estado = ("trabalhando" if atual else "esperando_voce" if aprovar else "erro" if erro
                  else "na_fila" if fila else "livre")
        ultimo = next((t for t in meus if t["status"] in ("aprovado", "aguardando_aprovacao")), None)
        saida.append({**a.resumo(), "estado": estado,
                      "atual": resumo(atual) if atual else None,
                      "proximo": resumo(fila[-1]) if fila else None,
                      "aprovar": [resumo(t) for t in aprovar[:5]],
                      "erro": resumo(erro) | {"erro": erro["erro"][:200]} if erro else None,
                      "ultimo": resumo(ultimo) if ultimo else None,
                      "fila": len(fila), "esperando": len(esperando)})
    return {"agentes": saida, "trabalhando": worker.ocupado(),
            "projetos": [_projeto(p) for p in store.listar_projetos(12)]}


def _abrir_pasta(caminho: str) -> None:
    p = Path(caminho)
    if not p.exists():
        raise ValueError("a pasta não existe mais neste PC")
    if sys.platform == "win32":
        os.startfile(str(p))  # noqa: S606 - abre no Explorer
    elif sys.platform == "darwin":
        import subprocess
        subprocess.Popen(["open", str(p)])
    else:
        import subprocess
        subprocess.Popen(["xdg-open", str(p)])


class _Handler(BaseHTTPRequestHandler):
    server_version = "CentralHAIZEN"

    def log_message(self, fmt, *args):  # silencioso no console do Jarvis
        pass

    # ── respostas ───────────────────────────────────────────────────────────
    def _json(self, obj, status=HTTPStatus.OK):
        corpo = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _erro(self, status, msg):
        self._json({"erro": msg}, status)

    def _bruto(self, limite: int = 8_000_000) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > limite:
            raise ValueError("pedido grande demais")
        return self.rfile.read(n) if n else b""

    def _corpo(self) -> dict:
        bruto = self._bruto(2_000_000)
        return json.loads(bruto.decode("utf-8") or "{}") if bruto else {}

    def _binario(self, corpo: bytes, tipo: str):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in _HOSTS or host.endswith(_SUFIXOS_HOST)

    # ── roteamento ──────────────────────────────────────────────────────────
    def do_GET(self):
        self._rotear("GET")

    def do_POST(self):
        self._rotear("POST")

    def do_PATCH(self):
        self._rotear("PATCH")

    def do_DELETE(self):
        self._rotear("DELETE")

    def _rotear(self, metodo: str):
        if not self._host_ok():
            return self._erro(HTTPStatus.FORBIDDEN, "host não permitido")
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            if metodo != "GET":
                return self._erro(HTTPStatus.METHOD_NOT_ALLOWED, "método não permitido")
            return self._estatico(url.path)
        if self.headers.get("X-Central") != "1":
            return self._erro(HTTPStatus.FORBIDDEN, "cabeçalho X-Central ausente")
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        partes = [p for p in url.path[len("/api/"):].split("/") if p]
        try:
            resultado = self._api(metodo, partes, q)
        except KeyError as e:
            return self._erro(HTTPStatus.NOT_FOUND, str(e).strip("'\""))
        except (ValueError, TypeError) as e:
            return self._erro(HTTPStatus.BAD_REQUEST, str(e))
        except Exception as e:  # noqa: BLE001
            return self._erro(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(e).__name__}: {e}")
        if resultado is _NAO_ACHOU:
            return self._erro(HTTPStatus.NOT_FOUND, "rota inexistente")
        if isinstance(resultado, _Audio):
            return self._binario(resultado.dados, "audio/wav")
        self._json(resultado)

    def _api(self, metodo, partes, q):
        if partes == ["painel"] and metodo == "GET":
            return dados.painel(q.get("de") or dados.hoje()[:8] + "01", q.get("ate") or dados.hoje())
        if partes == ["opcoes"] and metodo == "GET":
            return dados.opcoes()
        if partes == ["agentes"] and metodo == "GET":
            return [a.resumo() for a in agentes.listar()]

        if partes and partes[0] == "trabalhos":
            return self._trabalhos(metodo, partes[1:], q)
        if partes == ["escritorio"] and metodo == "GET":
            return escritorio()
        if partes and partes[0] == "projetos":
            return self._projetos(metodo, partes[1:])
        if partes and partes[0] == "jarvis":
            return self._jarvis(metodo, partes[1:], q)
        if partes and partes[0] == "sistema":
            return self._sistema(metodo, partes[1:])
        if partes and partes[0] == "janela":
            return self._janela(metodo, partes[1:], q)
        if partes and partes[0] == "whatsapp":
            return self._whatsapp(metodo, partes[1:], q)
        if partes and partes[0] == "agenda":
            return self._agenda(metodo, partes[1:], q)

        if len(partes) == 3 and partes[0] == "clientes" and partes[2] == "ficha":
            return dados.ficha_cliente(int(partes[1]))
        if len(partes) == 3 and partes[0] == "tarefas" and partes[2] == "acessos":
            return {"acessos": dados.acessos_da_tarefa(int(partes[1]))}
        if len(partes) == 3 and partes[0] == "marcas" and partes[2] == "abrir" and metodo == "POST":
            m = dados.obter("marcas", int(partes[1]))
            if m is None:
                raise KeyError("marca não encontrada")
            _abrir_pasta(m["pasta"])
            return {"ok": True}

        if partes and partes[0] in dados.ENTIDADES:
            ent = partes[0]
            if len(partes) == 1 and metodo == "GET":
                return dados.listar(ent, **q)
            if len(partes) == 1 and metodo == "POST":
                return dados.criar(ent, self._corpo())
            if len(partes) == 2:
                rid = int(partes[1])
                if metodo == "GET":
                    r = dados.obter(ent, rid)
                    if r is None:
                        raise KeyError("não encontrado")
                    return r
                if metodo == "PATCH":
                    return dados.atualizar(ent, rid, self._corpo())
                if metodo == "DELETE":
                    dados.apagar(ent, rid)
                    return {"ok": True}
        return _NAO_ACHOU

    def _trabalhos(self, metodo, partes, q):
        if not partes and metodo == "GET":
            return [_trabalho(t) for t in store.listar_trabalhos(q.get("status") or None,
                                                                 int(q.get("limite") or 50))]
        if not partes and metodo == "POST":
            c = self._corpo()
            r = servicos.delegar(c.get("agente", ""), c.get("pedido", ""), c.get("cliente", ""))
            worker.iniciar()
            return {"trabalho": _trabalho(r["trabalho"]), "aviso": r["aviso"]}
        if len(partes) >= 1:
            tid = int(partes[0])
            if len(partes) == 1 and metodo == "GET":
                t = store.trabalho(tid)
                if t is None:
                    raise KeyError("trabalho não encontrado")
                return _trabalho(t, com_entrega=True)
            if len(partes) == 1 and metodo == "DELETE":
                return store.apagar_trabalho(tid)
            if len(partes) == 2 and partes[1] == "aprovar" and metodo == "POST":
                return _trabalho(servicos.aprovar(tid, self._corpo().get("observacao", "")))
            if len(partes) == 2 and partes[1] == "tentar" and metodo == "POST":
                t = servicos.tentar_de_novo(tid)
                worker.iniciar()
                return _trabalho(t)
            if len(partes) == 2 and partes[1] == "refazer" and metodo == "POST":
                novo = servicos.refazer(tid, self._corpo().get("ajuste", ""))
                worker.iniciar()
                return _trabalho(novo)
        return _NAO_ACHOU

    def _projetos(self, metodo, partes):
        if not partes and metodo == "GET":
            return [_projeto(p) for p in store.listar_projetos(30)]
        if not partes and metodo == "POST":
            c = self._corpo()
            r = servicos.criar_projeto(c.get("pedido", ""), c.get("cliente", ""), c.get("titulo", ""))
            worker.iniciar()
            return {"projeto": _projeto(r["projeto"]), "aviso": r["aviso"]}
        if len(partes) == 1:
            pid = int(partes[0])
            proj = store.projeto(pid)
            if proj is None:
                raise KeyError("projeto não encontrado")
            if metodo == "GET":
                return _projeto(proj)
            if metodo == "DELETE":
                return store.apagar_projeto(pid)
        return _NAO_ACHOU

    def _whatsapp(self, metodo, partes, q):
        """A tela WhatsApp: ler não lidas e conversas; enviar (o clique em Enviar,
        depois da confirmação na página, é o OK do usuário)."""
        from core import whatsapp_web
        rota = partes[0] if partes else ""

        def _ou_erro(ok, code, r):
            if not ok:
                raise ValueError(r)
            return r
        if rota == "estado" and metodo == "GET":
            ok, code, r = whatsapp_web.run_op({"op": "login", "wait": 15}, timeout=75)
            if not ok:
                return {"estado": "erro", "erro": r, "imagem": ""}
            return r
        if rota == "recentes" and metodo == "GET":
            return {"conversas": _ou_erro(*whatsapp_web.run_op({"op": "recent"}, timeout=90))}
        if rota == "janela" and metodo == "POST":
            mostrar = bool(self._corpo().get("mostrar", True))
            return {"ok": bool(_ou_erro(*whatsapp_web.run_op({"op": "window", "show": mostrar}, timeout=30)))}
        if rota == "nao_lidas" and metodo == "GET":
            return {"conversas": _ou_erro(*whatsapp_web.run_op({"op": "unread"}, timeout=90))}
        if rota == "conversa" and metodo == "GET":
            contato = (q.get("contato") or "").strip()
            if not contato:
                raise ValueError("informe o contato")
            n = max(1, min(40, int(q.get("n") or 15)))
            msgs = _ou_erro(*whatsapp_web.run_op({"op": "read", "recipient": contato, "count": n}, timeout=60))
            from core import transcrever
            msgs = transcrever.com_transcricoes(msgs)
            cli = store.buscar_cliente(contato)
            return {"contato": contato, "mensagens": msgs,
                    "cliente": {"id": cli["id"], "nome": cli["nome"]} if cli else None}
        if rota == "enviar" and metodo == "POST":
            c = self._corpo()
            contato, texto = str(c.get("contato") or "").strip(), str(c.get("texto") or "").strip()
            if not contato or not texto:
                raise ValueError("informe o contato e o texto")
            _ou_erro(*whatsapp_web.run_op({"op": "send", "recipient": contato, "text": texto}, timeout=45))
            return {"ok": True}
        if rota == "transcrever" and metodo == "POST":
            from core import transcrever
            c = self._corpo()
            contato, mid = str(c.get("contato") or "").strip(), str(c.get("id") or "").strip()
            if not contato or not mid:
                raise ValueError("informe o contato e a mensagem")
            return {"id": mid, "texto": transcrever.transcrever_mensagem(contato, mid)}
        if rota == "sugerir" and metodo == "POST":
            from haizen.central import whatsapp_ia
            c = self._corpo()
            return {"texto": whatsapp_ia.sugerir_resposta(str(c.get("contato") or ""), c.get("mensagens") or [])}
        return _NAO_ACHOU

    def _agenda(self, metodo, partes, q):
        import datetime as _dt
        from haizen.central import atalhos
        rota = partes[0] if partes else ""
        if rota == "livre" and metodo == "GET":
            dia = _dt.date.fromisoformat(q.get("dia") or _dt.date.today().isoformat())
            return atalhos.horarios_livres(dia)
        if rota == "eventos":
            from haizen.central import agenda_web
            if len(partes) == 1 and metodo == "GET":
                return agenda_web.listar(q.get("de", ""), q.get("ate", ""))
            if len(partes) == 1 and metodo == "POST":
                return agenda_web.criar(self._corpo())
            if len(partes) == 2 and metodo == "PATCH":
                return agenda_web.editar(partes[1], self._corpo())
            if len(partes) == 2 and metodo == "DELETE":
                return agenda_web.excluir(partes[1])
        if rota == "evento" and metodo == "POST":
            from zoneinfo import ZoneInfo
            from actions.google_agenda import google_agenda
            c = self._corpo()
            dia = _dt.date.fromisoformat(str(c.get("dia") or ""))
            fuso = ZoneInfo("America/Sao_Paulo")
            ini = _dt.datetime.combine(dia, _dt.time.fromisoformat(str(c.get("inicio"))), fuso)
            fim = _dt.datetime.combine(dia, _dt.time.fromisoformat(str(c.get("fim"))), fuso)
            r = str(google_agenda({"action": "create", "title": str(c.get("titulo") or "").strip(),
                                   "start": ini.isoformat(), "end": fim.isoformat(),
                                   "description": str(c.get("descricao") or "")[:2000],
                                   "timezone": "America/Sao_Paulo"}))
            if not r.startswith("status=done"):
                motivo = re.search(r"(?:reason|question)=(\"[^\"]*\"|\S+)", r)
                raise ValueError((motivo.group(1).strip('"') if motivo else r)[:300])
            return {"ok": True}
        return _NAO_ACHOU

    def _janela(self, metodo, partes, q):
        """A interface comandando o Jarvis da janela (só quando ele está aberto)."""
        from haizen.central import janela
        p = janela.ponte()
        if p is None:
            return _NAO_ACHOU
        rota = partes[0] if partes else ""
        if rota == "estado" and metodo == "GET":
            from haizen.central import cerebro
            hist = cerebro.historico(1)
            return {**p.estado(int(q.get("desde") or 0)),
                    "ultima": hist[-1]["criado_em"] if hist else 0}
        if rota == "agente" and metodo == "POST":
            if not hasattr(p, "agente"):
                raise ValueError("reinicie o Jarvis para usar este botão")
            p.agente(bool(self._corpo().get("ligado")))
            return {"ok": True}
        if rota == "mensagem" and metodo == "POST":
            texto = str(self._corpo().get("texto") or "").strip()
            if not texto:
                raise ValueError("mensagem vazia")
            p.enviar(texto[:4000])
            return {"ok": True}
        if rota == "microfone" and metodo == "POST":
            p.microfone(bool(self._corpo().get("ligado")))
            return {"ok": True}
        if rota == "acordar" and metodo == "POST":
            p.acordar()
            return {"ok": True}
        if rota == "interromper" and metodo == "POST":
            p.interromper()
            return {"ok": True}
        if rota == "ajuste" and metodo == "POST":
            nome = str(self._corpo().get("nome") or "")
            if nome not in janela.AJUSTES:
                raise ValueError("ajuste desconhecido")
            p.abrir(nome)
            return {"ok": True}
        return _NAO_ACHOU

    def _sistema(self, metodo, partes):
        rota = partes[0] if partes else ""
        if rota == "versao" and metodo == "GET":
            return {"desatualizado": desatualizado(), "pode_reiniciar": bool(COMANDO_REINICIO),
                    "pid": os.getpid()}
        if rota == "reiniciar" and metodo == "POST":
            reiniciar()
            return {"ok": True}
        if rota == "desligar" and metodo == "POST":
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            if host not in _HOSTS:
                raise ValueError("só pelo próprio PC")
            threading.Thread(target=desligar, daemon=True).start()
            return {"ok": True}
        if rota == "sair" and metodo == "POST":
            # Só de dentro do PC: é assim que uma cópia nova pede a vez.
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            if host not in _HOSTS:
                raise ValueError("só pelo próprio PC")
            threading.Thread(target=lambda: (parar(), os._exit(0)), daemon=True).start()
            return {"ok": True}
        return _NAO_ACHOU

    def _jarvis(self, metodo, partes, q):
        from haizen.central import cerebro
        rota = partes[0] if partes else ""
        if rota == "estado" and metodo == "GET":
            return {**cerebro.estado(), "confirmacao": cerebro.confirmacao_pendente()}
        if rota == "historico" and metodo == "GET":
            return cerebro.historico(int(q.get("limite") or 40))
        if rota == "historico" and metodo == "DELETE":
            cerebro.limpar_historico()
            return {"ok": True}
        if rota == "mensagem" and metodo == "POST":
            c = self._corpo()
            return cerebro.responder(c.get("texto", ""), bool(c.get("voz")))
        if rota == "ouvir" and metodo == "POST":
            return {"texto": cerebro.ouvir(self._bruto(), int(q.get("taxa") or 16000))}
        if rota == "falar" and metodo == "POST":
            return _Audio(cerebro.falar(self._corpo().get("texto", "")))
        if rota == "confirmacao" and metodo == "GET":
            return {"confirmacao": cerebro.confirmacao_pendente()}
        if rota == "confirmacao" and metodo == "POST":
            cerebro.resolver_confirmacao(bool(self._corpo().get("aceitar")))
            return {"ok": True}
        return _NAO_ACHOU

    def _estatico(self, caminho: str):
        rel = "index.html" if caminho in ("/", "") else caminho.lstrip("/")
        if not re.fullmatch(r"[A-Za-z0-9_\-./]+", rel) or ".." in rel:
            return self._erro(HTTPStatus.NOT_FOUND, "não encontrado")
        arq = (ESTATICOS / rel).resolve()
        if ESTATICOS.resolve() not in arq.parents or not arq.is_file():
            arq = ESTATICOS / "index.html"      # rotas da página única
        corpo = arq.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", _TIPOS.get(arq.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'")
        if arq.name == "sw.js":
            self.send_header("Service-Worker-Allowed", "/")
        self.end_headers()
        self.wfile.write(corpo)


_NAO_ACHOU = object()


class _Audio:
    def __init__(self, dados: bytes):
        self.dados = dados
_servidor: ThreadingHTTPServer | None = None
_lock = threading.Lock()


def url() -> str:
    return f"http://127.0.0.1:{PORTA}/"


def _pedir_para_sair() -> bool:
    """Pede à cópia que está na porta para fechar. True se ela aceitou."""
    import http.client
    try:
        c = http.client.HTTPConnection("127.0.0.1", PORTA, timeout=3)
        c.request("POST", "/api/sistema/sair", body=b"{}",
                  headers={"X-Central": "1", "Host": f"127.0.0.1:{PORTA}",
                           "Content-Type": "application/json"})
        return c.getresponse().status == 200
    except OSError:
        return False


def iniciar(abrir_navegador: bool = True, assumir: bool = False, espera: float = 20) -> str:
    """Sobe o servidor em segundo plano (uma vez) e devolve o endereço.

    assumir=True (jarvis_web.py): se uma cópia antiga ocupa a porta, pede para
    ela fechar e assume o lugar, para o navegador nunca falar com código velho.
    """
    import time
    global _servidor
    with _lock:
        pediu = False
        limite = time.monotonic() + (espera if assumir else 0)
        while _servidor is None:
            try:
                _servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), _Handler)
            except OSError:
                if not assumir or time.monotonic() > limite:
                    if assumir:
                        raise RuntimeError(
                            f"A porta {PORTA} continua ocupada por outro programa. Feche os "
                            "processos python.exe/pythonw.exe no Gerenciador de Tarefas e tente de novo.")
                    break        # janela antiga: usa a central que já está aberta
                if not pediu:
                    pediu = _pedir_para_sair()
                time.sleep(0.5)
            else:
                threading.Thread(target=_servidor.serve_forever, name="central-haizen",
                                 daemon=True).start()
                _retomar_fila()
    if abrir_navegador:
        webbrowser.open(url())
    return url()


def desligar(espera: float = 0.4) -> None:
    """Desliga o Jarvis inteiro: WhatsApp escondido, central, janela e voz.
    O que estava sendo feito pelos agentes volta à fila na próxima vez."""
    import time as _time
    _time.sleep(espera)                 # a resposta chega à página (ou é falada) antes
    try:
        from core import whatsapp_web
        whatsapp_web.fechar()
    except Exception:  # noqa: BLE001
        pass
    from haizen.central import janela
    ponte = janela.ponte()
    if ponte is not None and hasattr(ponte, "desligar"):
        try:
            ponte.desligar()            # a janela fecha e encerra o processo
            _time.sleep(5)
        except Exception:  # noqa: BLE001
            pass
    parar()
    os._exit(0)


def _retomar_fila() -> None:
    """Trabalhos que ficaram pela metade quando o Jarvis fechou voltam à fila,
    e a fila volta a andar: o escritório não fica parado esperando um comando."""
    try:
        if store.recuperar_interrompidos() or store.listar_trabalhos("na_fila", 1):
            worker.iniciar()
    except Exception as e:  # noqa: BLE001
        print(f"[HAIZEN] não consegui retomar a fila: {e}")


def parar() -> None:
    global _servidor
    with _lock:
        if _servidor is not None:
            _servidor.shutdown()
            _servidor.server_close()
            _servidor = None

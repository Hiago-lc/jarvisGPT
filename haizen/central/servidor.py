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
_TIPOS = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
          ".png": "image/png", ".ico": "image/x-icon"}


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

    def _corpo(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        if n > 2_000_000:
            raise ValueError("pedido grande demais")
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in _HOSTS

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
            if len(partes) == 2 and partes[1] == "aprovar" and metodo == "POST":
                return _trabalho(servicos.aprovar(tid, self._corpo().get("observacao", "")))
            if len(partes) == 2 and partes[1] == "refazer" and metodo == "POST":
                novo = servicos.refazer(tid, self._corpo().get("ajuste", ""))
                worker.iniciar()
                return _trabalho(novo)
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
                         "img-src 'self' data:; connect-src 'self'")
        self.end_headers()
        self.wfile.write(corpo)


_NAO_ACHOU = object()
_servidor: ThreadingHTTPServer | None = None
_lock = threading.Lock()


def url() -> str:
    return f"http://127.0.0.1:{PORTA}/"


def iniciar(abrir_navegador: bool = True) -> str:
    """Sobe o servidor em segundo plano (uma vez) e devolve o endereço."""
    global _servidor
    with _lock:
        if _servidor is None:
            try:
                _servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), _Handler)
            except OSError:
                # Porta ocupada: provavelmente outra cópia da central já está aberta.
                _servidor = None
            else:
                threading.Thread(target=_servidor.serve_forever, name="central-haizen",
                                 daemon=True).start()
    if abrir_navegador:
        webbrowser.open(url())
    return url()


def parar() -> None:
    global _servidor
    with _lock:
        if _servidor is not None:
            _servidor.shutdown()
            _servidor.server_close()
            _servidor = None

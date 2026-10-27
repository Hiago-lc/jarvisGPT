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
        if partes and partes[0] == "jarvis":
            return self._jarvis(metodo, partes[1:], q)
        if partes and partes[0] == "sistema":
            return self._sistema(metodo, partes[1:])

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

    def _sistema(self, metodo, partes):
        rota = partes[0] if partes else ""
        if rota == "versao" and metodo == "GET":
            return {"desatualizado": desatualizado(), "pode_reiniciar": bool(COMANDO_REINICIO),
                    "pid": os.getpid()}
        if rota == "reiniciar" and metodo == "POST":
            reiniciar()
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

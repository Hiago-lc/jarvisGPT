"""Login pelo Google quando o Jarvis roda num servidor (modo servidor).

No PC o Jarvis só aceita pedidos do próprio computador e não precisa de login. No servidor ele
fica na internet, então toda página e toda chamada exigem uma sessão aberta pelo login do Google
de um e-mail autorizado.

Configuração (no arquivo de ambiente do serviço, /etc/jarvis/jarvis.env):
    HAIZEN_URL_PUBLICA=https://jarvis.seudominio.com.br
    HAIZEN_EMAILS=voce@gmail.com[,outro@empresa.com]
    HAIZEN_GOOGLE_LOGIN_ID=....apps.googleusercontent.com
    HAIZEN_GOOGLE_LOGIN_SEGREDO=...
O cliente OAuth é do tipo "Aplicativo da Web" no Google Cloud, com o URI de redirecionamento
autorizado  https://jarvis.seudominio.com.br/auth/google/retorno
"""
from __future__ import annotations

import hashlib
import base64
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

COOKIE = "jarvis_sessao"
DURACAO = 30 * 86400
_PENDENTES: dict[str, dict] = {}       # state -> {verifier, criado, volta}
_TRAVA = threading.Lock()


def ativo() -> bool:
    return bool(os.environ.get("HAIZEN_URL_PUBLICA", "").strip())


def url_publica() -> str:
    return os.environ.get("HAIZEN_URL_PUBLICA", "").strip().rstrip("/")


def host_publico() -> str:
    return urllib.parse.urlparse(url_publica()).hostname or ""


def emails_permitidos() -> set[str]:
    return {e.strip().lower() for e in os.environ.get("HAIZEN_EMAILS", "").split(",") if e.strip()}


def _cliente() -> tuple[str, str]:
    cid = os.environ.get("HAIZEN_GOOGLE_LOGIN_ID", "").strip()
    seg = os.environ.get("HAIZEN_GOOGLE_LOGIN_SEGREDO", "").strip()
    if not cid or not seg:
        raise RuntimeError("login do Google não configurado (HAIZEN_GOOGLE_LOGIN_ID e HAIZEN_GOOGLE_LOGIN_SEGREDO)")
    return cid, seg


# ── sessões (guardadas como hash: o arquivo não serve para entrar) ──────────
def _arq() -> Path:
    from core.data_paths import data_dir
    return Path(data_dir()) / "sessoes.json"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _ler() -> dict:
    try:
        return json.loads(_arq().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _gravar(d: dict) -> None:
    p = _arq()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(p)


def criar_sessao(email: str) -> str:
    token = secrets.token_urlsafe(32)
    with _TRAVA:
        d = {k: v for k, v in _ler().items() if v.get("expira", 0) > time.time()}
        d[_hash(token)] = {"email": email, "expira": time.time() + DURACAO, "criada": time.time()}
        _gravar(d)
    return token


def sessao(token: str | None) -> dict | None:
    if not token:
        return None
    s = _ler().get(_hash(token))
    if not s or s.get("expira", 0) < time.time() or s.get("email", "").lower() not in emails_permitidos():
        return None
    return s


def encerrar(token: str | None) -> None:
    if not token:
        return
    with _TRAVA:
        d = _ler()
        d.pop(_hash(token), None)
        _gravar(d)


def token_do_cookie(cabecalho: str | None) -> str | None:
    for parte in (cabecalho or "").split(";"):
        nome, _, valor = parte.strip().partition("=")
        if nome == COOKIE and valor:
            return valor
    return None


def cookie(token: str, apagar: bool = False) -> str:
    idade = 0 if apagar else DURACAO
    return f"{COOKIE}={'' if apagar else token}; Max-Age={idade}; Path=/; HttpOnly; Secure; SameSite=Lax"


# ── fluxo do Google (OpenID Connect com PKCE) ──────────────────────────────
def url_login(volta: str = "/") -> str:
    cid, _ = _cliente()
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    with _TRAVA:
        for k in [k for k, v in _PENDENTES.items() if time.time() - v["criado"] > 900]:
            _PENDENTES.pop(k, None)
        _PENDENTES[state] = {"verifier": verifier, "criado": time.time(), "volta": volta if volta.startswith("/") else "/"}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": f"{url_publica()}/auth/google/retorno", "response_type": "code",
        "scope": "openid email", "state": state, "code_challenge": desafio, "code_challenge_method": "S256",
        "prompt": "select_account"})


def concluir(state: str, code: str) -> tuple[str, str]:
    """(token da sessão, para onde voltar). Erro se o e-mail não for autorizado."""
    with _TRAVA:
        p = _PENDENTES.pop(state or "", None)
    if not p or time.time() - p["criado"] > 900:
        raise ValueError("o login expirou: tente de novo")
    cid, seg = _cliente()
    dados = urllib.parse.urlencode({"code": code, "client_id": cid, "client_secret": seg,
                                    "redirect_uri": f"{url_publica()}/auth/google/retorno",
                                    "grant_type": "authorization_code", "code_verifier": p["verifier"]}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=dados), timeout=30) as r:
            tok = json.loads(r.read())
        req = urllib.request.Request("https://openidconnect.googleapis.com/v1/userinfo",
                                     headers={"Authorization": f"Bearer {tok['access_token']}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            info = json.loads(r.read())
    except (urllib.error.URLError, KeyError, ValueError) as e:
        raise ValueError(f"o Google não confirmou o login ({e})") from None
    email = str(info.get("email") or "").lower()
    if not info.get("email_verified") or email not in emails_permitidos():
        raise PermissionError(f"o e-mail {email or '(sem e-mail)'} não tem acesso a este Jarvis")
    return criar_sessao(email), p["volta"]


PAGINA_LOGIN = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Entrar · Jarvis HAIZEN</title>
<link rel="icon" href="/icone.svg"><style>
:root{--bg:#F3F5F4;--fg:#16201F;--sub:#5B6766;--card:#fff;--linha:#DCE3E1;--acento:#0F3B3A}
@media (prefers-color-scheme:dark){:root{--bg:#0E1515;--fg:#E8EEEC;--sub:#9AA7A5;--card:#162020;--linha:#263332;--acento:#7FD1C7}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--fg);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:24px}
main{background:var(--card);border:1px solid var(--linha);border-radius:14px;padding:36px 32px;max-width:380px;width:100%;text-align:center}
img{width:56px;height:56px}h1{font-size:22px;margin:14px 0 6px}p{color:var(--sub);margin:0 0 24px;font-size:14.5px}
a.botao{display:inline-flex;gap:10px;align-items:center;justify-content:center;width:100%;padding:11px 16px;border-radius:10px;
border:1px solid var(--linha);background:var(--card);color:var(--fg);text-decoration:none;font-weight:600}
a.botao:hover{border-color:var(--acento)}.erro{color:#B4442F;margin-top:16px;font-size:14px}</style></head>
<body><main><img src="/icone.svg" alt=""><h1>Jarvis HAIZEN</h1><p>Entre com a conta Google autorizada.</p>
<a class="botao" href="/auth/google{volta}"><svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.4 30.2 0 24 0 14.6 0 6.6 5.4 2.6 13.2l7.8 6.1C12.3 13.6 17.7 9.5 24 9.5z"/><path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.4 5.8c4.3-4 6.9-9.9 6.9-17.1z"/><path fill="#FBBC05" d="M10.4 28.7c-.5-1.4-.8-3-.8-4.7s.3-3.2.8-4.7l-7.8-6.1C.9 16.6 0 20.2 0 24s.9 7.4 2.6 10.8l7.8-6.1z"/><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.4-5.8c-2.1 1.4-4.8 2.3-8.5 2.3-6.3 0-11.7-4.1-13.6-9.8l-7.8 6.1C6.6 42.6 14.6 48 24 48z"/></svg>Entrar com o Google</a>
{erro}</main></body></html>"""


def pagina_login(erro: str = "", volta: str = "") -> bytes:
    import html
    v = f"?volta={urllib.parse.quote(volta)}" if volta and volta.startswith("/") and volta != "/" else ""
    return (PAGINA_LOGIN.replace("{volta}", v)
            .replace("{erro}", f'<p class="erro">{html.escape(erro)}</p>' if erro else "")).encode("utf-8")

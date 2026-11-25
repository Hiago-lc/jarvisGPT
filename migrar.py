"""Leva o Jarvis configurado de um computador para outro (ex.: do desktop para o notebook).

O código vem do GitHub; este script leva o que NÃO vai para o GitHub: o banco (clientes, tarefas,
financeiro, projetos, histórico), as configurações, os tokens e a memória. Tudo sai num único
arquivo .jarvispack protegido por uma senha que você escolhe.

    python migrar.py exportar [pasta_destino]     # no computador de origem
    python migrar.py importar arquivo.jarvispack  # no computador novo, com o Jarvis fechado

Os tokens ficam criptografados pela conta do Windows (DPAPI), que só abre no PC onde foram
guardados. Na exportação eles são abertos e protegidos pela senha do pacote; na importação voltam
a ser fechados pelo Windows do computador novo. Não ficam anexos do chat (podem ter vários GB),
o perfil do WhatsApp Web (escaneie o QR de novo) nem caches.
"""
from __future__ import annotations

import base64
import datetime as dt
import getpass
import io
import json
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

ASSINATURA = b"JARVISPACK1"
ITERACOES = 600_000
# Dentro da pasta de dados: o que não vai (pesado, refeito sozinho ou preso a este PC).
FORA_DADOS = {"jarvis-claude/anexos", "janela-web", "whatsapp-web-profile", "backups"}
FORA_EXT = {".log", ".lock", ".pyc", ".tmp"}
# Dentro da pasta do Jarvis: o que é local (não está no GitHub) e precisa ir junto.
LOCAIS_RAIZ = ["config/api_keys.json", "client_secret.json", "memory/long_term.json", "importar_base44",
               "haizen/gerar_maxiflora.py"]


# ── criptografia do pacote ──────────────────────────────────────────────────
def _chave(senha: str, sal: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sal, iterations=ITERACOES)
    return base64.urlsafe_b64encode(kdf.derive(senha.encode("utf-8")))


def cifrar(dados: bytes, senha: str) -> bytes:
    from cryptography.fernet import Fernet
    sal = os.urandom(16)
    return ASSINATURA + sal + Fernet(_chave(senha, sal)).encrypt(dados)


def decifrar(pacote: bytes, senha: str) -> bytes:
    from cryptography.fernet import Fernet, InvalidToken
    if not pacote.startswith(ASSINATURA):
        raise ValueError("isso não é um pacote do Jarvis (.jarvispack)")
    sal = pacote[len(ASSINATURA):len(ASSINATURA) + 16]
    try:
        return Fernet(_chave(senha, sal)).decrypt(pacote[len(ASSINATURA) + 16:])
    except InvalidToken:
        raise ValueError("senha errada (ou o arquivo está corrompido)") from None


# ── segredos: abrir (exportar) e fechar de novo (importar) ──────────────────
def _trocar_segredos(valor, abrir: bool):
    from haizen import segredo
    if isinstance(valor, dict):
        return {k: _trocar_segredos(v, abrir) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_trocar_segredos(v, abrir) for v in valor]
    if isinstance(valor, str):
        if abrir and valor.startswith("dpapi:"):
            return "plain:" + segredo.abrir(valor)
        if not abrir and valor.startswith("plain:"):
            return segredo.fechar(valor[len("plain:"):])
    return valor


def _json_segredos(texto: str, abrir: bool) -> str | None:
    try:
        dados = json.loads(texto)
    except ValueError:
        return None
    novo = _trocar_segredos(dados, abrir)
    return json.dumps(novo, ensure_ascii=False, indent=1) if novo != dados else None


def _copiar_banco(origem: Path) -> bytes:
    """Cópia consistente mesmo com o Jarvis aberto (API de backup do SQLite)."""
    tmp = Path(tempfile.mkdtemp()) / origem.name
    a, b = sqlite3.connect(origem), sqlite3.connect(tmp)
    try:
        a.backup(b)
    finally:
        a.close()
        b.close()
    dados = tmp.read_bytes()
    shutil.rmtree(tmp.parent, ignore_errors=True)
    return dados


def _banco_trocar(caminho: Path, abrir: bool | None, troca_caminho: tuple[str, str] | None = None) -> int:
    """Abre/fecha segredos guardados em colunas de texto e troca a pasta do usuário antigo."""
    from haizen import segredo
    n = 0
    con = sqlite3.connect(caminho)
    try:
        tabelas = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tabelas:
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")') if (r[2] or "").upper() in ("TEXT", "")]
            for c in cols:
                if abrir is not None:
                    prefixo = "dpapi:" if abrir else "plain:"
                    for rid, v in con.execute(f'SELECT rowid, "{c}" FROM "{t}" WHERE "{c}" LIKE ?', (prefixo + "%",)).fetchall():
                        novo = "plain:" + segredo.abrir(v) if abrir else segredo.fechar(v[len("plain:"):])
                        con.execute(f'UPDATE "{t}" SET "{c}"=? WHERE rowid=?', (novo, rid))
                        n += 1
                if troca_caminho and troca_caminho[0] != troca_caminho[1]:
                    cur = con.execute(f'UPDATE "{t}" SET "{c}"=REPLACE("{c}", ?, ?) WHERE "{c}" LIKE ?',
                                      (troca_caminho[0], troca_caminho[1], f"%{troca_caminho[0]}%"))
                    n += cur.rowcount
        con.commit()
    finally:
        con.close()
    return n


# ── exportar ────────────────────────────────────────────────────────────────
def _pasta_drive() -> Path | None:
    for letra in "GHIJKLMNOPDEF":
        p = Path(f"{letra}:/Meu Drive")
        if p.is_dir():
            return p
    return None


def exportar(destino: Path, senha: str) -> Path:
    from core.data_paths import data_dir
    dados = Path(data_dir())
    buf = io.BytesIO()
    resumo = {"dados": 0, "locais": 0, "segredos": 0}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(dados.rglob("*")):
            rel = f.relative_to(dados).as_posix()
            if not f.is_file() or f.suffix.lower() in FORA_EXT or "__pycache__" in rel:
                continue
            if any(rel == x or rel.startswith(x + "/") for x in FORA_DADOS):
                continue
            if f.suffix.lower() == ".db":
                conteudo = _copiar_banco(f)
                tmp = Path(tempfile.mkdtemp()) / f.name
                tmp.write_bytes(conteudo)
                resumo["segredos"] += _banco_trocar(tmp, True)
                conteudo = tmp.read_bytes()
                shutil.rmtree(tmp.parent, ignore_errors=True)
            elif f.suffix.lower() == ".json":
                texto = f.read_text(encoding="utf-8", errors="replace")
                trocado = _json_segredos(texto, True)
                if trocado is not None:
                    resumo["segredos"] += 1
                conteudo = (trocado if trocado is not None else texto).encode("utf-8")
            else:
                conteudo = f.read_bytes()
            z.writestr("dados/" + rel, conteudo)
            resumo["dados"] += 1
        for item in LOCAIS_RAIZ:
            p = RAIZ / item
            arquivos = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else []
            for f in arquivos:
                if "__pycache__" in f.parts:
                    continue
                z.write(f, "raiz/" + f.relative_to(RAIZ).as_posix())
                resumo["locais"] += 1
        z.writestr("manifesto.json", json.dumps({
            "criado_em": dt.datetime.now().isoformat(timespec="seconds"), "computador": socket.gethostname(),
            "pasta_usuario": str(Path.home()), "pasta_jarvis": str(RAIZ), **resumo}, ensure_ascii=False, indent=1))
    destino.mkdir(parents=True, exist_ok=True)
    saida = destino / f"jarvis-migracao-{dt.date.today().isoformat()}.jarvispack"
    saida.write_bytes(cifrar(buf.getvalue(), senha))
    print(f"\nPacote criado: {saida}")
    print(f"  {resumo['dados']} arquivos de dados, {resumo['locais']} arquivos locais, segredos protegidos pela senha.")
    return saida


# ── importar ────────────────────────────────────────────────────────────────
def _jarvis_aberto(porta: int = int(os.environ.get("HAIZEN_CENTRAL_PORTA", "8765"))) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", porta)) == 0


def importar(pacote: Path, senha: str) -> dict:
    from core.data_paths import data_dir
    if _jarvis_aberto():
        raise RuntimeError("feche o Jarvis deste computador antes de importar (ícone perto do relógio → Sair)")
    conteudo = decifrar(pacote.read_bytes(), senha)
    dados = Path(data_dir())
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        manifesto = json.loads(z.read("manifesto.json"))
        # Guarda o que já existia aqui, para poder voltar.
        if any(dados.iterdir()):
            guarda = dados.with_name(f"{dados.name}-antes-da-importacao-{dt.datetime.now():%Y%m%d-%H%M%S}")
            shutil.copytree(dados, guarda, ignore=shutil.ignore_patterns("janela-web", "whatsapp-web-profile", "anexos"))
            print(f"O que havia neste computador foi guardado em: {guarda}")
        troca = (manifesto.get("pasta_usuario") or "", str(Path.home()))
        for nome in z.namelist():
            if nome.endswith("/") or nome == "manifesto.json":
                continue
            if nome.startswith("dados/"):
                alvo = dados / nome[len("dados/"):]
            elif nome.startswith("raiz/"):
                alvo = RAIZ / nome[len("raiz/"):]
            else:
                continue
            alvo.parent.mkdir(parents=True, exist_ok=True)
            corpo = z.read(nome)
            if alvo.suffix.lower() == ".json":
                texto = corpo.decode("utf-8", errors="replace")
                if troca[0] and troca[0] != troca[1]:
                    texto = texto.replace(json.dumps(troca[0])[1:-1], json.dumps(troca[1])[1:-1]).replace(troca[0], troca[1])
                trocado = _json_segredos(texto, False)
                corpo = (trocado if trocado is not None else texto).encode("utf-8")
            alvo.write_bytes(corpo)
            if alvo.suffix.lower() == ".db":
                _banco_trocar(alvo, False, troca if troca[0] else None)
    print("\nImportado. O Jarvis deste computador agora tem os mesmos clientes, tarefas, projetos, "
          "configurações e tokens do outro.")
    return manifesto


def _pedir_senha(confirmar: bool) -> str:
    while True:
        s = getpass.getpass("Senha do pacote: ")
        if len(s) < 8:
            print("Use pelo menos 8 caracteres.")
            continue
        if confirmar and getpass.getpass("Repita a senha: ") != s:
            print("As senhas não batem. De novo.")
            continue
        return s


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("exportar", "importar"):
        print(__doc__)
        return 1
    try:
        if argv[0] == "exportar":
            destino = Path(argv[1]) if len(argv) > 1 else ((_pasta_drive() / "JARVIS - migracao") if _pasta_drive()
                                                           else Path.home() / "Desktop")
            print(f"Vou criar o pacote em: {destino}\nEscolha uma senha (você vai digitá-la no outro computador).")
            exportar(destino, _pedir_senha(True))
        else:
            if len(argv) > 1:
                pacote = Path(argv[1])
            else:
                candidatos = sorted(((_pasta_drive() or Path.home()) / "JARVIS - migracao").glob("*.jarvispack"))
                if not candidatos:
                    print("Não achei o pacote. Arraste o arquivo .jarvispack para cima deste programa.")
                    return 1
                pacote = candidatos[-1]
            print(f"Importando: {pacote}")
            importar(pacote, _pedir_senha(False))
        return 0
    except (ValueError, RuntimeError, OSError) as e:
        print(f"\nNão deu certo: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

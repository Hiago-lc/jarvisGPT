#!/usr/bin/env bash
# Instala o Jarvis HAIZEN num VPS Ubuntu 24.04 (Hostinger ou outro).
#
#   curl -fsSL https://raw.githubusercontent.com/Hiago-lc/jarvisGPT/main/servidor/instalar.sh -o instalar.sh
#   sudo bash instalar.sh
#
# Pode rodar de novo quantas vezes quiser: ele só completa o que falta.
set -euo pipefail

REPO="${JARVIS_REPO:-https://github.com/Hiago-lc/jarvisGPT.git}"
RAMO="${JARVIS_RAMO:-main}"
APP=/opt/jarvis
CASA=/var/lib/jarvis
DADOS=$CASA/dados
DRIVE=/srv/drive
ETC=/etc/jarvis
ENVF=$ETC/jarvis.env

verde() { printf '\033[1;32m%s\033[0m\n' "$*"; }
passo() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
[ "$(id -u)" = 0 ] || { echo "Rode com sudo: sudo bash instalar.sh"; exit 1; }

perguntar() {   # perguntar VAR "texto" [padrão]
  local atual="${!1:-}"
  [ -n "$atual" ] && return
  read -r -p "$2${3:+ [$3]}: " resp </dev/tty || true
  printf -v "$1" '%s' "${resp:-${3:-}}"
}

# Valores já salvos de uma instalação anterior.
if [ -f "$ENVF" ]; then
  set -a; . "$ENVF"; set +a
  DOMINIO="${HAIZEN_URL_PUBLICA#https://}"; EMAIL="${HAIZEN_EMAILS:-}"
fi

passo "Dados do seu Jarvis"
perguntar DOMINIO "Domínio do Jarvis (ex.: jarvis.haizen.com.br)"
perguntar EMAIL "Seu e-mail do Google (o único que poderá entrar)"
[ -n "${DOMINIO:-}" ] && [ -n "${EMAIL:-}" ] || { echo "Domínio e e-mail são obrigatórios."; exit 1; }

passo "Pacotes do sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates gnupg python3 python3-venv python3-pip python3-dev build-essential \
  ffmpeg fuse3 unzip ufw locales fonts-noto fonts-noto-color-emoji fonts-liberation debian-keyring debian-archive-keyring \
  apt-transport-https >/dev/null
locale-gen pt_BR.UTF-8 >/dev/null || true
timedatectl set-timezone America/Sao_Paulo || true
grep -q '^user_allow_other' /etc/fuse.conf || echo user_allow_other >> /etc/fuse.conf

if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi
command -v rclone >/dev/null || curl -fsSL https://rclone.org/install.sh | bash >/dev/null

passo "Usuário e pastas"
id jarvis >/dev/null 2>&1 || useradd --system --home-dir "$CASA" --create-home --shell /bin/bash jarvis
usermod -aG systemd-journal jarvis || true
mkdir -p "$DADOS" "$DRIVE" "$ETC" /var/cache/jarvis-rclone
chown -R jarvis:jarvis "$CASA" "$DRIVE" /var/cache/jarvis-rclone
chmod 750 "$CASA"; chmod 700 "$ETC"; chown jarvis:jarvis "$ETC"

passo "Código do Jarvis"
if [ -d "$APP/.git" ]; then
  sudo -u jarvis git -C "$APP" pull --ff-only
else
  git clone -b "$RAMO" "$REPO" "$APP" && chown -R jarvis:jarvis "$APP"
fi
sudo -u jarvis git config --global --add safe.directory "$APP" || true

passo "Python e navegador (alguns minutos)"
[ -d "$APP/.venv" ] || sudo -u jarvis python3 -m venv "$APP/.venv"
sudo -u jarvis "$APP/.venv/bin/pip" install -q --upgrade pip
sudo -u jarvis "$APP/.venv/bin/pip" install -q -r "$APP/servidor/requirements-servidor.txt"
"$APP/.venv/bin/python" -m playwright install-deps chromium >/dev/null
sudo -u jarvis -H "$APP/.venv/bin/python" -m playwright install chromium >/dev/null

passo "Claude Code"
if [ ! -x "$CASA/.local/bin/claude" ]; then
  sudo -u jarvis -H bash -c 'curl -fsSL https://claude.ai/install.sh | bash' >/dev/null
fi

passo "Chave dos segredos e configuração"
if [ ! -f "$ETC/chave" ]; then
  "$APP/.venv/bin/python" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > "$ETC/chave"
fi
chown jarvis:jarvis "$ETC/chave"; chmod 600 "$ETC/chave"
if [ ! -f "$ENVF" ]; then
  cat > "$ENVF" <<EOF
# Configuração do Jarvis no servidor. Depois de mudar: sudo jarvis reiniciar
HAIZEN_URL_PUBLICA=https://$DOMINIO
HAIZEN_EMAILS=$EMAIL
# Cliente OAuth "Aplicativo da Web" do Google Cloud (login): veja servidor/LEIA-ME.md
HAIZEN_GOOGLE_LOGIN_ID=
HAIZEN_GOOGLE_LOGIN_SEGREDO=
JARVIS_DATA_DIR=$DADOS
HAIZEN_CHAVE_ARQUIVO=$ETC/chave
HAIZEN_RAIZ_DRIVE=$DRIVE
HOME=$CASA
PATH=$CASA/.local/bin:/usr/local/bin:/usr/bin:/bin
TZ=America/Sao_Paulo
LANG=pt_BR.UTF-8
PYTHONUNBUFFERED=1
EOF
fi
chown jarvis:jarvis "$ENVF"; chmod 600 "$ENVF"

passo "HTTPS (Caddy) e firewall"
cat > /etc/caddy/Caddyfile <<EOF
$DOMINIO {
	encode gzip
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options nosniff
		Referrer-Policy same-origin
		-Server
	}
	reverse_proxy 127.0.0.1:8765 {
		flush_interval -1
		transport http {
			read_timeout 30m
			write_timeout 30m
		}
	}
}
EOF
systemctl enable --now caddy >/dev/null 2>&1; systemctl reload caddy || systemctl restart caddy
ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw --force enable >/dev/null

passo "Serviços"
install -m 644 "$APP/servidor/jarvis.service" /etc/systemd/system/jarvis.service
install -m 644 "$APP/servidor/rclone-drive.service" /etc/systemd/system/rclone-drive.service
install -m 755 "$APP/servidor/jarvis-admin.sh" /usr/local/bin/jarvis
systemctl daemon-reload
systemctl enable jarvis.service rclone-drive.service >/dev/null 2>&1

verde ""
verde "Instalação concluída. Faltam 4 passos, que você faz uma vez só:"
cat <<EOF

  1) Google Drive:          sudo jarvis drive
  2) Login do Google:       edite /etc/jarvis/jarvis.env (HAIZEN_GOOGLE_LOGIN_ID e _SEGREDO)
                            com:  sudo nano /etc/jarvis/jarvis.env
  3) Claude Code:           sudo jarvis claude
  4) Seus dados do PC:      sudo jarvis importar
  Depois:                   sudo jarvis iniciar
  e abra https://$DOMINIO

  Outros comandos:  sudo jarvis status | logs | reiniciar | atualizar
EOF

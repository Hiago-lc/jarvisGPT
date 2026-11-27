#!/usr/bin/env bash
# Atalhos para cuidar do Jarvis no servidor:  sudo jarvis <comando>
set -euo pipefail
APP=/opt/jarvis
ENVF=/etc/jarvis/jarvis.env
comando="${1:-ajuda}"
comoJarvis() { sudo -u jarvis -H bash -c 'cd /var/lib/jarvis; set -a; . /etc/jarvis/jarvis.env; set +a; exec "$@"' _ "$@"; }

case "$comando" in
  drive)
    cat <<'EOF'
Conectar o Google Drive (uma vez):
  1. No seu PC (Windows), abra o PowerShell e rode:   winget install Rclone.Rclone
  2. Feche e abra o PowerShell de novo e rode:
       rclone authorize "drive" "SEU_ID_DO_CLIENTE" "SUA_CHAVE_SECRETA"
     (o cliente OAuth "App para computador" do seu Google Cloud; veja servidor/LEIA-ME.md.
      Sem cliente próprio: rclone authorize "drive"  — funciona, mas o Google vai desativar.)
     O navegador abre: entre com a conta Google do Drive da HAIZEN e autorize.
  3. O PowerShell mostra um texto entre ---> e <---End paste. Copie esse texto (começa com {).
  4. Responda as perguntas abaixo.
EOF
    read -r -p "ID do cliente do Drive (Enter se não usou): " cid </dev/tty
    cseg=""
    [ -n "$cid" ] && read -r -p "Chave secreta do cliente do Drive: " cseg </dev/tty
    read -r -p "Cole o texto do rclone: " token </dev/tty
    case "$token" in \{*\}) ;; *) echo "Isso não parece o texto completo do rclone (começa com { e termina com })."; exit 1;; esac
    umask 077
    {
      printf '[drive]\ntype = drive\nscope = drive\n'
      [ -n "$cid" ] && printf 'client_id = %s\nclient_secret = %s\n' "$cid" "$cseg"
      printf 'token = %s\n' "$token"
    } > /etc/jarvis/rclone.conf
    chown jarvis:jarvis /etc/jarvis/rclone.conf
    systemctl restart rclone-drive.service
    # O Drive é montado pelo usuário jarvis: só ele enxerga a pasta.
    for _ in $(seq 1 15); do
      [ -n "$(sudo -u jarvis ls -A /srv/drive 2>/dev/null)" ] && break
      sleep 2
    done
    if [ -n "$(sudo -u jarvis ls -A /srv/drive 2>/dev/null)" ]; then
      echo "Drive conectado. Pastas:"; sudo -u jarvis ls /srv/drive | head -20
    else
      echo "O Drive não montou. Veja: sudo journalctl -u rclone-drive -n 30"
    fi
    ;;
  pastas)
    sudo -u jarvis ls /srv/drive | head -40
    ;;
  claude)
    echo "O Claude Code vai abrir. Digite /login, escolha a conta Claude com assinatura,"
    echo "abra o link no navegador do seu PC, autorize e cole o código aqui. Depois digite /exit."
    comoJarvis /var/lib/jarvis/.local/bin/claude
    ;;
  importar)
    systemctl stop jarvis.service || true
    comoJarvis "$APP/.venv/bin/python" "$APP/migrar.py" importar ${2:+"$2"}
    echo "Agora: sudo jarvis iniciar"
    ;;
  iniciar)   systemctl start rclone-drive.service jarvis.service; systemctl --no-pager status jarvis.service | head -5 ;;
  reiniciar) systemctl restart jarvis.service; echo "Reiniciado." ;;
  parar)     systemctl stop jarvis.service; echo "Parado." ;;
  status)    systemctl --no-pager status jarvis.service rclone-drive.service caddy | grep -E "●|Active:" ;;
  logs)      journalctl -u jarvis.service -n "${2:-80}" --no-pager ;;
  atualizar)
    sudo -u jarvis git -C "$APP" pull --ff-only
    sudo -u jarvis "$APP/.venv/bin/pip" install -q -r "$APP/servidor/requirements-servidor.txt"
    install -m 755 "$APP/servidor/jarvis-admin.sh" /usr/local/bin/jarvis
    systemctl restart jarvis.service; echo "Atualizado e reiniciado."
    ;;
  *)
    echo "Uso: sudo jarvis drive | pastas | claude | importar [arquivo] | iniciar | reiniciar | parar | status | logs | atualizar"
    ;;
esac

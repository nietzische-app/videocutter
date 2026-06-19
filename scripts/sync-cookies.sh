#!/usr/bin/env bash
# YouTube cookies.txt dosyasini sunucuya yukler ve uygulamayi yeniden baslatir.
#
# Kurulum:
#   cp scripts/sync-cookies.env.example scripts/sync-cookies.env
#   # sync-cookies.env duzenle
#   chmod +x scripts/sync-cookies.sh
#
# Kullanim:
#   ./scripts/sync-cookies.sh
#   ./scripts/sync-cookies.sh /path/to/cookies.txt

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="${SYNC_COOKIES_CONFIG:-$SCRIPT_DIR/sync-cookies.env}"

if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

LOCAL_COOKIES="${1:-${LOCAL_COOKIES:-$PROJECT_DIR/cookies.txt}}"
REMOTE="${REMOTE:-}"
REMOTE_PATH="${REMOTE_PATH:-/root/videocutter/videocutter/cookies.txt}"
RESTART_CMD="${RESTART_CMD:-}"

if [[ -z "$REMOTE" ]]; then
  echo "HATA: REMOTE ayarlanmamis."
  echo "Ornek: REMOTE=root@123.45.67.89"
  echo "Dosya: $CONFIG_FILE"
  exit 1
fi

if [[ ! -f "$LOCAL_COOKIES" ]]; then
  echo "HATA: Cookie dosyasi bulunamadi: $LOCAL_COOKIES"
  echo "Chrome eklentisi 'Get cookies.txt LOCALLY' ile youtube.com'dan export edin."
  exit 1
fi

echo "Yukleniyor: $LOCAL_COOKIES -> $REMOTE:$REMOTE_PATH"
scp "$LOCAL_COOKIES" "$REMOTE:$REMOTE_PATH"

if [[ -n "$RESTART_CMD" ]]; then
  echo "Uygulama yeniden baslatiliyor..."
  ssh "$REMOTE" "$RESTART_CMD"
else
  echo "RESTART_CMD bos — sunucuda elle yeniden baslatin:"
  echo "  ssh $REMOTE 'cd $(dirname "$REMOTE_PATH") && pkill -f app.py; source .venv/bin/activate && set -a && source .env && set +a && nohup python3 app.py >> app.log 2>&1 &'"
fi

echo "Tamam."

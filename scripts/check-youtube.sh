#!/usr/bin/env bash
# Sunucuda YouTube indirme altyapisini kontrol eder.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== yt-dlp ==="
python3 -m yt_dlp --version 2>/dev/null || yt-dlp --version

echo ""
echo "=== Cookies ==="
if [[ -f cookies.txt ]]; then
  age_days=$(( ( $(date +%s) - $(stat -c %Y cookies.txt) ) / 86400 ))
  echo "cookies.txt var (${age_days} gunluk)"
  head -1 cookies.txt
else
  echo "cookies.txt YOK"
fi

echo ""
echo "=== PO Token provider ==="
POT_URL="${BGUTIL_POT_URL:-http://127.0.0.1:4416}"
if curl -sf "${POT_URL}/" -o /dev/null 2>/dev/null || curl -sf "${POT_URL}" -o /dev/null 2>/dev/null; then
  echo "POT provider erisilebilir: $POT_URL"
else
  echo "POT provider erisilemiyor: $POT_URL"
  echo "  Docker: docker run -d --name bgutil-pot -p 127.0.0.1:4416:4416 brainicism/bgutil-ytdlp-pot-provider"
fi

echo ""
echo "=== .env ==="
grep -E '^(YOUTUBE_COOKIES|BGUTIL_POT_URL|YTDLP_PROXY)=' .env 2>/dev/null || echo ".env ayarlari bulunamadi"

echo ""
echo "=== Test indirme (metadata only) ==="
TEST_URL="${1:-https://www.youtube.com/watch?v=jNQXAC9IVRw}"
python3 - <<PY
from youtube_dl import build_ytdlp_options, check_cookies_health
from yt_dlp import YoutubeDL
import os
os.chdir("$(pwd)")
print("Cookie health:", check_cookies_health().get("message"))
opts = build_ytdlp_options(quiet=True)
opts["skip_download"] = True
with YoutubeDL(opts) as ydl:
    info = ydl.extract_info("$TEST_URL", download=False)
    print("OK:", info.get("title", "?")[:60])
PY

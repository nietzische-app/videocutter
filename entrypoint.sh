#!/bin/sh
set -e

# Tek container: web + scheduler birlikte
if [ "$SCHEDULER_ENABLED" = "true" ] && [ "$SCHEDULER_STANDALONE" != "true" ]; then
  echo "Scheduler arka planda baslatiliyor..."
  python scheduler_service.py &
fi

exec gunicorn --bind 0.0.0.0:7860 --timeout 1800 --workers 1 app:app

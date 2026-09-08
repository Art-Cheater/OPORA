#!/bin/bash
set -e

echo "$(date -u +%H:%M:%S) Ожидание PostgreSQL..."
while ! python -c "
import socket, os, sys
host = os.environ.get('DB_HOST', 'db')
port = int(os.environ.get('DB_PORT', '5432'))
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1)
try:
    s.connect((host, port))
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
    sleep 1
done

echo "$(date -u +%H:%M:%S) PostgreSQL доступен."

if [ "${OPORA_RUN_MIGRATE:-1}" = "1" ]; then
    echo "$(date -u +%H:%M:%S) Миграции..."
    if ! flask db upgrade; then
        echo "ERROR: flask db upgrade failed"
        flask db current || true
        flask db heads || true
        exit 1
    fi
    flask db current || true
    echo "$(date -u +%H:%M:%S) Каталог прав..."
    flask sync-security || echo "WARN: flask sync-security failed (продолжаем)"
else
    echo "$(date -u +%H:%M:%S) Миграции пропускаем (их делает web)."
fi

if [ "${OPORA_SEED_ON_START:-0}" = "1" ]; then
    echo "$(date -u +%H:%M:%S) Справочники (OPORA_SEED_ON_START=1)..."
    flask seed-reference-data || echo "WARN: seed-reference-data failed (продолжаем)"
    flask seed-admin || echo "WARN: seed-admin failed (продолжаем)"
else
    echo "$(date -u +%H:%M:%S) Справочники пропускаем (уже в БД). Для сида: OPORA_SEED_ON_START=1"
fi

if [ "${1:-}" = "gunicorn" ]; then
    # Gunicorn reads GUNICORN_CMD_ARGS itself.  It is intentionally ignored:
    # Compose owns its command line, and application environment must not be
    # reinterpreted as Gunicorn CLI arguments.
    # Keep the name present but empty at exec time.  Gunicorn snapshots this
    # variable during startup and treats an empty value as no extra CLI args.
    export GUNICORN_CMD_ARGS=""
    : "${WEB_CONCURRENCY:=3}"
    : "${GUNICORN_THREADS:=8}"
    : "${GUNICORN_TIMEOUT:=120}"
    set -- gunicorn wsgi:app \
        --bind 0.0.0.0:5000 \
        --worker-class gthread \
        --workers "$WEB_CONCURRENCY" \
        --threads "$GUNICORN_THREADS" \
        --timeout "$GUNICORN_TIMEOUT" \
        --graceful-timeout 30 \
        --keep-alive 5
fi

echo "$(date -u +%H:%M:%S) Запуск: $*"
exec "$@"

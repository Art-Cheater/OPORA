#!/bin/bash
set -e

echo "Ожидание PostgreSQL..."
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

echo "PostgreSQL доступен."

echo "Миграции..."
if ! flask db upgrade; then
    echo "ERROR: flask db upgrade failed"
    flask db current || true
    flask db heads || true
    exit 1
fi
flask db current || true

echo "Справочники..."
flask seed-reference-data || echo "WARN: seed-reference-data failed (продолжаем)"
flask seed-admin || echo "WARN: seed-admin failed (продолжаем)"

echo "Запуск: $*"
exec "$@"

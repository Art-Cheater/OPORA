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
echo "Запуск: $*"
exec "$@"

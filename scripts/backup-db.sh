#!/usr/bin/env bash
# Ежедневный бэкап PostgreSQL (контейнер opora_db). Хранение 14 дней.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"
CONTAINER="${OPORA_DB_CONTAINER:-opora_db}"
KEEP_DAYS="${OPORA_BACKUP_KEEP_DAYS:-14}"
BACKUP_DIR="${OPORA_BACKUP_DIR:-/var/backups/opora}"

read_env() {
  local key="$1" default="${2:-}"
  local line val
  [[ -f "$ENV_FILE" ]] || { echo "$default"; return; }
  line="$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" | tail -n1 || true)"
  [[ -n "$line" ]] || { echo "$default"; return; }
  val="${line#*=}"
  val="${val%\"}"
  val="${val#\"}"
  val="${val%\'}"
  val="${val#\'}"
  echo "$val"
}

PGUSER="$(read_env POSTGRES_USER opora_user)"
PGDB="$(read_env POSTGRES_DB opora)"

mkdir -p "$BACKUP_DIR"

running="$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)"
if [[ "$running" != "true" ]]; then
  echo "Контейнер $CONTAINER не запущен. Бэкап пропущен."
  exit 1
fi

stamp="$(date +%Y-%m-%d)"
outfile="$BACKUP_DIR/opora_${stamp}.dump"

echo "==> Бэкап $PGDB -> $outfile"
docker exec "$CONTAINER" pg_dump -U "$PGUSER" -d "$PGDB" -Fc -f /tmp/opora_backup.dump
docker cp "${CONTAINER}:/tmp/opora_backup.dump" "$outfile"
docker exec "$CONTAINER" rm -f /tmp/opora_backup.dump

if [[ ! -s "$outfile" ]]; then
  echo "Файл бэкапа не создан: $outfile"
  exit 1
fi

find "$BACKUP_DIR" -name 'opora_*.dump' -type f -mtime +"$KEEP_DAYS" -print -delete

echo "==> Готово: $outfile ($(du -h "$outfile" | cut -f1))"

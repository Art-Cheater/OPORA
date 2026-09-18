#!/usr/bin/env bash
# Host-side backup helper. Credentials stay in .env / host secret store.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
backup_dir="${BACKUP_DIR:-$root/backups}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:?POSTGRES_USER is required}" -d "${POSTGRES_DB:?POSTGRES_DB is required}" -Fc > "$backup_dir/opora-$stamp.dump"
docker run --rm -v opora_uploads_data:/source:ro -v "$backup_dir:/backup" alpine:3.20 tar -czf "/backup/opora-uploads-$stamp.tar.gz" -C /source .
find "$backup_dir" -type f -mtime "+${BACKUP_RETENTION_DAYS:-7}" -delete
if [[ -n "${BACKUP_S3_URI:-}" ]] && command -v aws >/dev/null; then
  aws s3 cp "$backup_dir/opora-$stamp.dump" "$BACKUP_S3_URI/"
  aws s3 cp "$backup_dir/opora-uploads-$stamp.tar.gz" "$BACKUP_S3_URI/"
fi
echo "Backup written to $backup_dir"

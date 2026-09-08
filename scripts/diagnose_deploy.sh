#!/usr/bin/env bash
# Safe operational snapshot: it deliberately never prints `docker compose config`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> git: $(git rev-parse --short HEAD) $(git log -1 --pretty=%s)"
echo "==> docker compose"
docker compose version
echo "==> services"
docker compose config --services
echo "==> .env pre-flight"
python3 scripts/check_env.py .env || true
echo "==> Docker context candidates (excluded data is checked by pre-flight tests)"
du -sh . 2>/dev/null || true
echo "==> containers"
docker compose ps
echo "==> web inspect"
docker inspect opora_web --format 'Path={{.Path}} Args={{json .Args}} State={{.State.Status}} Health={{json .State.Health.Status}}' 2>/dev/null || true
echo "==> nginx inspect"
docker inspect opora_nginx --format 'State={{.State.Status}} Health={{json .State.Health.Status}}' 2>/dev/null || true
echo "==> recent web logs (secret assignments masked)"
docker compose logs --tail=120 web 2>&1 | sed -E \
  -e 's/(SECRET_KEY|[^[:space:]]*PASSWORD|DATABASE_URL)=[^[:space:]]+/\1=********/g' \
  -e 's#postgres(ql)?://[^@[:space:]]+@#postgresql://********@#g' || true
echo "==> recent nginx logs (secret assignments masked)"
docker compose logs --tail=80 nginx 2>&1 | sed -E \
  -e 's/(SECRET_KEY|[^[:space:]]*PASSWORD|DATABASE_URL)=[^[:space:]]+/\1=********/g' \
  -e 's#postgres(ql)?://[^@[:space:]]+@#postgresql://********@#g' || true

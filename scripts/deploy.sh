#!/usr/bin/env bash
# Обновление с origin/main. Тома БД не трогаем.
# Если Docker Hub недоступен (часто IPv6), пересобираем поверх уже
# имеющихся opora-web / opora-nginx — код всё равно берётся из git.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> OPORA deploy: $ROOT"

command -v git >/dev/null || { echo "Нужен git"; exit 1; }
command -v docker >/dev/null || { echo "Нужен docker"; exit 1; }
docker compose version >/dev/null || { echo "Нужен Docker Compose plugin"; exit 1; }

echo "==> git fetch / reset to origin/main"
git fetch origin
git checkout main
git reset --hard origin/main

if [[ ! -f "$ROOT/.env" ]]; then
  echo "Нет файла .env. Скопируйте .env.example и заполните секреты."
  exit 1
fi

echo "==> production .env pre-flight"
if ! python3 scripts/check_env.py "$ROOT/.env"; then
  echo "==> deploy остановлен до Docker build. Исправьте .env и повторите проверку:"
  echo "    python3 scripts/check_env.py .env"
  exit 1
fi

# Do not source .env: it can contain shell-significant passwords. Read only the
# profile key and select an overlay; the main command remains unchanged.
OPORA_ENV="$(awk -F= '$1 == "OPORA_ENV" { value=$2 } END { print value }' "$ROOT/.env" | tr -d '\r\"' | tr '[:upper:]' '[:lower:]')"
case "$OPORA_ENV" in
  production)
    COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.timeweb.example.yml)
    BUILD_SERVICES=(web nginx inquiry-sync eis-sync documents-notify tcp-gateway)
    ;;
  staging)
    COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.staging.yml)
    BUILD_SERVICES=(web nginx)
    ;;
  *)
    echo "OPORA_ENV должен быть staging или production."
    exit 1
    ;;
esac

compose() {
  docker compose "${COMPOSE_FILES[@]}" "$@"
}

echo "==> окружение: $OPORA_ENV"

show_web_failure() {
  echo "==> web не стал healthy; последние логи и состояние контейнера:"
  compose logs --tail=120 web || true
  docker inspect opora_web --format 'Path={{.Path}} Args={{json .Args}} State={{.State.Status}} Health={{json .State.Health}}' || true
}

build_from_local_images() {
  echo "==> Docker Hub недоступен — сборка из локальных образов (код из git)"
  if ! docker image inspect opora-web:latest >/dev/null 2>&1; then
    echo "Нет образа opora-web:latest. Нужен хотя бы один успешный build с Docker Hub."
    exit 1
  fi
  if ! docker image inspect opora-nginx:latest >/dev/null 2>&1; then
    echo "Нет образа opora-nginx:latest. Нужен хотя бы один успешный build с Docker Hub."
    exit 1
  fi

  local tmp_web tmp_nginx
  tmp_web="$(mktemp)"
  tmp_nginx="$(mktemp)"
  cat >"$tmp_web" <<'EOF'
FROM opora-web:latest
WORKDIR /app
COPY . .
EOF
  cat >"$tmp_nginx" <<'EOF'
FROM opora-nginx:latest
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY app/static /usr/share/nginx/html/static
EOF

  docker build -f "$tmp_web" -t opora-web:latest .
  docker tag opora-web:latest opora-eis-sync:latest
  docker tag opora-web:latest opora-inquiry-sync:latest
  docker build -f "$tmp_nginx" -t opora-nginx:latest .
  rm -f "$tmp_web" "$tmp_nginx"
}

echo "==> docker compose build (через overlay $OPORA_ENV)"
# Debian/Timeweb builds may reject BuildKit's --allow capability. Retry only
# the build with classic builder; running containers are not changed by it.
if ! compose build --pull=false "${BUILD_SERVICES[@]}"; then
  echo "==> обычная сборка не удалась, пробуем без Docker Hub"
  if ! DOCKER_BUILDKIT=0 compose build --pull=false "${BUILD_SERVICES[@]}"; then
    build_from_local_images
  fi
fi

echo "==> пересоздаём web (миграции в entrypoint), nginx ждёт healthcheck"
if ! compose up -d --no-deps --force-recreate web; then
  show_web_failure
  exit 1
fi
if ! compose up -d --force-recreate nginx; then
  show_web_failure
  exit 1
fi

echo "==> поднимаем остальное"
if ! compose up -d; then
  show_web_failure
  exit 1
fi

echo "==> пересчёт районов заявок по адресу (OSM, с паузой)"
compose exec -T web flask repair-request-districts || echo "WARN: repair-request-districts не выполнился"

echo "==> Готово. Проверка: curl -s http://127.0.0.1:5000/health"
compose ps

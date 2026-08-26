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

echo "==> docker compose build web nginx inquiry-sync eis-sync"
if ! docker compose build --pull=false web nginx inquiry-sync eis-sync; then
  echo "==> обычная сборка не удалась, пробуем без Docker Hub"
  build_from_local_images
fi

echo "==> пересоздаём web (миграции в entrypoint), nginx ждёт healthcheck"
docker compose up -d --no-deps --force-recreate web
docker compose up -d --force-recreate nginx inquiry-sync eis-sync

echo "==> поднимаем остальное"
docker compose up -d

echo "==> пересчёт районов заявок по адресу (OSM, с паузой)"
docker compose exec -T web flask repair-request-districts || echo "WARN: repair-request-districts не выполнился"

echo "==> Готово. Проверка: curl -s http://127.0.0.1:5000/health"
docker compose ps

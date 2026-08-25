#!/usr/bin/env bash
# Обновление с origin/main. Тома БД не трогаем. Короче простой, чем force-recreate всего стека.
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

echo "==> docker compose build web nginx inquiry-sync eis-sync"
docker compose build web nginx inquiry-sync eis-sync

echo "==> пересоздаём web (миграции в entrypoint), nginx ждёт healthcheck"
docker compose up -d --no-deps --force-recreate web
docker compose up -d --force-recreate nginx inquiry-sync eis-sync

echo "==> поднимаем остальное"
docker compose up -d

echo "==> пересчёт районов заявок по адресу (OSM, с паузой)"
docker compose exec -T web flask repair-request-districts || echo "WARN: repair-request-districts не выполнился"

echo "==> Готово. Проверка: curl -s http://127.0.0.1:5000/health"
docker compose ps

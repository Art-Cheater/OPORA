#!/usr/bin/env bash
# Обновляет код с origin/main и пересобирает контейнеры. Тома БД не трогает.
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

echo "==> docker compose up --build -d"
docker compose up --build -d

echo "==> Готово. Сайт: http://localhost:5000"
docker compose ps

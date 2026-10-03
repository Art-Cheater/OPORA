#!/usr/bin/env bash
# Только публичный сайт Кировсвет: контейнер opora_public_site.
# CRM, база и остальные контейнеры не пересоздаются.
# Сертификат лежит в nginx, не в этом контейнере: если Let's Encrypt уже
# выпущен, скрипт заново кладёт его конфиг и делает nginx -s reload.
#
# На сервере:
#   cd /opt/opora && sudo bash scripts/rebuild-public-site.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

command -v git >/dev/null || { echo "Нужен git"; exit 1; }
command -v docker >/dev/null || { echo "Нужен docker"; exit 1; }
docker compose version >/dev/null || { echo "Нужен Docker Compose plugin"; exit 1; }

echo "==> git fetch / reset to origin/main"
git fetch origin
git checkout main
git reset --hard origin/main

if [[ "${OPORA_SITE_REEXEC:-0}" != "1" ]]; then
  export OPORA_SITE_REEXEC=1
  exec bash "$ROOT/scripts/rebuild-public-site.sh"
fi

if [[ ! -f "$ROOT/.env" ]]; then
  echo "Нет файла .env"
  exit 1
fi

OPORA_ENV="$(awk -F= '$1 == "OPORA_ENV" { value=$2 } END { print value }' "$ROOT/.env" | tr -d '\r\"' | tr '[:upper:]' '[:lower:]')"
case "$OPORA_ENV" in
  production) COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.timeweb.example.yml) ;;
  staging) COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.staging.yml) ;;
  *) echo "OPORA_ENV должен быть staging или production."; exit 1 ;;
esac

compose() {
  COMPOSE_BAKE=false docker compose "${COMPOSE_FILES[@]}" "$@"
}

PUBLIC_SITE_DOMAIN="kirovsvet.truthqwark.ru"
certs_dir="$(awk -F= '$1 == "TLS_CERTS_DIR" { value=$2 } END { print value }' "$ROOT/.env" | tr -d '\r\"')"
if [[ -z "$certs_dir" ]]; then
  certs_dir="$ROOT/data/letsencrypt"
fi
state_dir="$ROOT/data/nginx"
webroot="${OPORA_ACME_WEBROOT:-/var/www/certbot}"

echo "==> собираем только public-site"
if ! compose build --pull=false public-site && ! DOCKER_BUILDKIT=0 compose build --pull=false public-site; then
  echo "FAIL: образ Кировсвета не собрался"
  exit 1
fi

echo "==> пересоздаём только контейнер opora_public_site"
compose up -d --no-build --no-deps --force-recreate public-site

echo "==> ждём /health"
ready=0
for _ in $(seq 1 30); do
  if docker exec opora_public_site python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1/health', timeout=2).read()" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" != "1" ]]; then
  echo "FAIL: opora_public_site не ответил на /health"
  docker logs --tail 50 opora_public_site || true
  exit 1
fi

if [[ "$OPORA_ENV" != "production" ]]; then
  echo "==> Готово. Контейнер public-site пересобран."
  exit 0
fi

mkdir -p "$state_dir" "$webroot"
if [[ ! -f "$certs_dir/live/$PUBLIC_SITE_DOMAIN/fullchain.pem" || ! -f "$certs_dir/live/$PUBLIC_SITE_DOMAIN/privkey.pem" ]]; then
  echo "==> TLS: выпускаем сертификат $PUBLIC_SITE_DOMAIN"
  if ! command -v certbot >/dev/null 2>&1; then
    echo "WARN: certbot нет, сайт остаётся как был. Контейнер уже пересобран."
    exit 0
  fi
  certbot certonly --webroot -w "$webroot" \
    --config-dir "$certs_dir" \
    --cert-name "$PUBLIC_SITE_DOMAIN" \
    -d "$PUBLIC_SITE_DOMAIN" \
    --non-interactive \
    --agree-tos \
    --keep-until-expiring \
    --no-eff-email \
    || echo "WARN: сертификат не выпущен"
fi

if [[ -f "$certs_dir/live/$PUBLIC_SITE_DOMAIN/fullchain.pem" && -f "$certs_dir/live/$PUBLIC_SITE_DOMAIN/privkey.pem" ]]; then
  echo "==> TLS: подключаем сертификат $PUBLIC_SITE_DOMAIN, nginx только reload"
  cp "$ROOT/docker/nginx.public-site.conf" "$state_dir/public-site.conf.tmp"
  mv -f "$state_dir/public-site.conf.tmp" "$state_dir/public-site.conf"
  if docker exec opora_nginx nginx -t; then
    docker exec opora_nginx nginx -s reload
    openssl x509 -in "$certs_dir/live/$PUBLIC_SITE_DOMAIN/fullchain.pem" -noout -subject -issuer -dates || true
    echo "==> TLS: сертификат $PUBLIC_SITE_DOMAIN подключён"
  else
    echo "WARN: nginx не принял конфиг Кировсвета. Контейнер сайта уже пересобран, Опора не перезапускалась."
  fi
else
  echo "WARN: файла сертификата нет. Контейнер сайта пересобран, Опора не перезапускалась."
fi

echo "==> Готово. Пересобран только public-site."

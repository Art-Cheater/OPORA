#!/usr/bin/env bash
# Обновление с origin/main: cd /opt/opora && sudo bash scripts/deploy.sh
# Тома БД и uploads не трогаем (никаких down -v). Образы собираются один раз,
# затем все application services пересоздаются с --no-build.
set -euo pipefail
DEPLOY_STARTED="$(date +%s)"

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
    # tcp-gateway runs the web image (opora-web:latest) and has no own build.
    BUILD_SERVICES=(web nginx inquiry-sync eis-sync documents-notify modem-sniffer irz-poller)
    RECREATE_SERVICES=(web nginx inquiry-sync eis-sync documents-notify tcp-gateway modem-sniffer irz-poller)
    CRITICAL_SERVICES=(web nginx tcp-gateway modem-sniffer irz-poller)
    ;;
  staging)
    COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.staging.yml)
    BUILD_SERVICES=(web nginx)
    RECREATE_SERVICES=(web nginx)
    CRITICAL_SERVICES=(web nginx)
    ;;
  *)
    echo "OPORA_ENV должен быть staging или production."
    exit 1
    ;;
esac
OTHER_SERVICES=()
for service in "${RECREATE_SERVICES[@]}"; do
  [[ "$service" == "web" ]] || OTHER_SERVICES+=("$service")
done

compose() {
  # Compose >= 2.30 delegates builds to Buildx Bake and passes --allow=fs.read;
  # an older docker-buildx rejects it ("unknown flag: --allow"). The classic
  # Compose build path does not use that flag.
  COMPOSE_BAKE=false docker compose "${COMPOSE_FILES[@]}" "$@"
}

container_of() { compose ps -a -q "$1" 2>/dev/null | head -n1; }

container_state() {
  local id
  id="$(container_of "$1")"
  [[ -n "$id" ]] || { echo "missing/none"; return; }
  docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id" 2>/dev/null || echo "missing/none"
}

show_service_failure() {
  local service="$1" state id
  state="$(container_state "$service")"
  id="$(container_of "$service")"
  echo "==> FAIL: сервис $service, состояние $state"
  if [[ -n "$id" ]]; then
    docker inspect "$id" --format 'Image={{.Config.Image}} Created={{.Created}} RestartCount={{.RestartCount}} ExitCode={{.State.ExitCode}} Error={{.State.Error}}' || true
    docker inspect "$id" --format '{{if .State.Health}}{{range .State.Health.Log}}health exit={{.ExitCode}} {{.Output}}{{end}}{{end}}' | tail -n 5 || true
  fi
  compose logs --tail=120 "$service" || true
}

show_web_failure() {
  show_service_failure web
  docker inspect opora_web --format 'Path={{.Path}} Args={{json .Args}}' 2>/dev/null || true
}

wait_ready() {
  # running + healthy, or running without a healthcheck; fails fast on unhealthy/exited.
  local service="$1" timeout="$2" deadline state
  deadline=$(( $(date +%s) + timeout ))
  while :; do
    state="$(container_state "$service")"
    case "$state" in
      running/healthy|running/none) return 0 ;;
      */unhealthy|exited/*|dead/*) return 1 ;;
    esac
    (( $(date +%s) < deadline )) || return 1
    sleep 2
  done
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

  DOCKER_BUILDKIT=0 docker build -f "$tmp_web" -t opora-web:latest .
  docker tag opora-web:latest opora-eis-sync:latest
  docker tag opora-web:latest opora-inquiry-sync:latest
  docker tag opora-web:latest opora-documents-notify:latest
  docker tag opora-web:latest opora-modem-sniffer:latest
  docker tag opora-web:latest opora-irz-poller:latest
  DOCKER_BUILDKIT=0 docker build -f "$tmp_nginx" -t opora-nginx:latest .
  rm -f "$tmp_web" "$tmp_nginx"
}

alembic_revisions() {
  { compose exec -T web flask db "$1" 2>/dev/null | grep -Eo '^[0-9]{3}_[0-9A-Za-z_]+' | sort -u | tr '\n' ' ' | sed 's/ $//'; } || true
}

echo "==> окружение: $OPORA_ENV"

echo "==> docker compose build (один раз, через overlay $OPORA_ENV): ${BUILD_SERVICES[*]}"
if ! compose build --pull=false "${BUILD_SERVICES[@]}"; then
  echo "==> сборка через BuildKit не удалась, повтор классическим builder (DOCKER_BUILDKIT=0)"
  if ! DOCKER_BUILDKIT=0 compose build --pull=false "${BUILD_SERVICES[@]}"; then
    echo "==> обычная сборка не удалась, пробуем локальные базовые образы"
    build_from_local_images
  fi
fi

echo "==> db: запуск без пересоздания (том postgres_data не трогаем)"
compose up -d --no-build db
wait_ready db 120 || { show_service_failure db; exit 1; }

echo "==> web: пересоздание и миграции"
if ! compose up -d --no-build --no-deps --force-recreate web; then
  show_web_failure
  exit 1
fi
wait_ready web 240 || { show_web_failure; exit 1; }

echo "==> проверяем Alembic: flask db current == flask db heads"
DB_CURRENT="$(alembic_revisions current)"
DB_HEADS="$(alembic_revisions heads)"
echo "    current: ${DB_CURRENT:-—}"
echo "    heads:   ${DB_HEADS:-—}"
if [[ -z "$DB_HEADS" || "$DB_CURRENT" != "$DB_HEADS" ]]; then
  echo "FAIL: миграции не применены до head"
  compose logs --tail=80 web || true
  exit 1
fi

echo "==> пересоздаём остальные сервисы без сборки: ${OTHER_SERVICES[*]}"
if ! compose up -d --no-build --no-deps --force-recreate "${OTHER_SERVICES[@]}"; then
  for service in "${OTHER_SERVICES[@]}"; do
    [[ "$(container_state "$service")" == running/* ]] || show_service_failure "$service"
  done
  exit 1
fi

echo "==> ждём готовности сервисов"
FAILED=()
for service in "${OTHER_SERVICES[@]}"; do
  wait_ready "$service" 180 || FAILED+=("$service")
done
sleep 5
for service in "${RECREATE_SERVICES[@]}"; do
  [[ "$(container_state "$service")" == running/* ]] || FAILED+=("$service")
done
if (( ${#FAILED[@]} )); then
  for service in $(printf '%s\n' "${FAILED[@]}" | sort -u); do show_service_failure "$service"; done
  exit 1
fi

echo "==> пересчёт районов заявок по адресу (OSM, с паузой)"
compose exec -T web flask repair-request-districts || echo "WARN: repair-request-districts не выполнился"

echo "==> проверяем, что critical containers созданы текущим deploy"
for service in "${CRITICAL_SERVICES[@]}"; do
  created="$(docker inspect -f '{{.Created}}' "$(container_of "$service")")"
  created_epoch="$(date -d "$created" +%s)"
  (( created_epoch >= DEPLOY_STARTED )) || { echo "FAIL: $service не был пересоздан текущим deploy ($created)"; exit 1; }
done

if [[ "$OPORA_ENV" == "production" ]]; then
  echo "==> проверяем published ports (5000 = другие платы, 5009 = IRZ/ATM21)"
  docker port opora_tcp_gateway 5000/tcp | grep -Eq ':5000$' || { echo "FAIL: 5000 не опубликован tcp-gateway"; exit 1; }
  docker port opora_modem_sniffer 5009/tcp | grep -Eq ':5009$' || { echo "FAIL: 5009 не опубликован modem-sniffer"; exit 1; }
  if docker port opora_modem_sniffer | grep -Eq ':5000$' || docker port opora_tcp_gateway | grep -Eq ':5009$'; then
    echo "FAIL: порты 5000 и 5009 перепутаны между tcp-gateway и modem-sniffer"
    exit 1
  fi
fi

echo
echo "COMMIT: $(git rev-parse HEAD)"
echo "MIGRATION HEAD: $DB_HEADS"
printf '%-18s %-26s %-28s %-21s %-9s %-10s %s\n' SERVICE CONTAINER IMAGE CREATED STATUS HEALTH PORTS
for service in $(compose config --services); do
  id="$(container_of "$service")"
  if [[ -z "$id" ]]; then
    printf '%-18s %s\n' "$service" "—"
    continue
  fi
  docker inspect "$id" --format "{{printf \"%-18s\" \"$service\"}} {{printf \"%-26s\" (slice .Name 1)}} {{printf \"%-28s\" .Config.Image}} {{printf \"%-21s\" (slice .Created 0 19)}} {{printf \"%-9s\" .State.Status}} {{printf \"%-10s\" (or (and .State.Health .State.Health.Status) \"-\")}} {{range \$port, \$bindings := .NetworkSettings.Ports}}{{if \$bindings}}{{(index \$bindings 0).HostPort}}->{{\$port}} {{end}}{{end}}"
done
echo "==> Готово. Deploy занял $(( $(date +%s) - DEPLOY_STARTED )) с."

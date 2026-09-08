#!/usr/bin/env bash
# Подготовить локальный PBF и запустить сборку tiles в контейнере Valhalla.
# Скрипт принципиально не скачивает OSM-данные сам.
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="$ROOT_DIR/data/valhalla"
PBF_PATH="${VALHALLA_PBF_PATH:-$DATA_DIR/kirov-oblast-latest.osm.pbf}"
COMPOSE=(docker compose -f "$ROOT_DIR/docker-compose.yml" -f "$ROOT_DIR/docker-compose.routing.yml")

mkdir -p "$DATA_DIR"

if [[ ! -f "$PBF_PATH" ]]; then
  cat >&2 <<EOF
OSM PBF не найден: $PBF_PATH

Скачайте или скопируйте extract Кировской области вручную в:
  $DATA_DIR/kirov-oblast-latest.osm.pbf

Либо укажите уже существующий файл:
  VALHALLA_PBF_PATH=/абсолютный/путь/kirov-oblast-latest.osm.pbf bash scripts/valhalla/prepare-valhalla.sh

Большие OSM-файлы скрипт намеренно не скачивает автоматически.
EOF
  exit 2
fi

EXPECTED_DIR="$DATA_DIR/"
case "$(cd "$(dirname "$PBF_PATH")" && pwd)/" in
  "$EXPECTED_DIR"*) ;;
  *)
    cat >&2 <<EOF
PBF должен находиться внутри $DATA_DIR, потому что только эта папка
монтируется в контейнер как /custom_files. Скопируйте файл туда и повторите.
EOF
    exit 2
    ;;
esac

"${COMPOSE[@]}" config --quiet
echo "Запуск Valhalla. При первом запуске container соберёт tiles из: $PBF_PATH"
"${COMPOSE[@]}" up -d valhalla
echo
echo "Сборка может занять заметное время. Следите за журналом:"
echo "  ${COMPOSE[*]} logs -f valhalla"
echo
echo "После готовности проверьте OPORA:"
echo "  ${COMPOSE[*]} exec -T web python -m flask check-routing"

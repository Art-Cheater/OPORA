#!/usr/bin/env bash
# Подготовка данных optional routing. Ничего не скачивает и не запускает web/deploy.
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
provider=""
pbf=""

while (($#)); do
  case "$1" in
    --provider) provider="${2:-}"; shift 2 ;;
    --pbf) pbf="${2:-}"; shift 2 ;;
    -h|--help)
      echo "Usage: bash scripts/routing/prepare-routing.sh --provider valhalla --pbf data/osm/kirov-oblast-latest.osm.pbf"
      exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ "$provider" != "valhalla" && "$provider" != "osrm" ]] || [[ -z "$pbf" ]]; then
  echo "Specify --provider valhalla|osrm and --pbf PATH." >&2
  exit 2
fi
if [[ ! -f "$pbf" ]]; then
  echo "OSM PBF not found: $pbf" >&2
  exit 2
fi
size_bytes=$(wc -c < "$pbf")
if (( size_bytes > 6 * 1024 * 1024 * 1024 )); then
  echo "Refusing PBF larger than 6 GiB: use a Kirov city/oblast extract, not Russia/Eurasia." >&2
  exit 2
fi

if [[ "$provider" == "osrm" ]]; then
  echo "OSRM is not the selected OPORA provider. No OSRM Compose service is configured." >&2
  echo "Use --provider valhalla, or add OSRM as a separate approved infrastructure task." >&2
  exit 2
fi

target="$ROOT_DIR/data/valhalla/$(basename "$pbf")"
mkdir -p "$ROOT_DIR/data/valhalla"
if [[ "$(cd "$(dirname "$pbf")" && pwd)/$(basename "$pbf")" != "$target" ]]; then
  cp -n "$pbf" "$target"
fi
VALHALLA_PBF_PATH="$target" bash "$ROOT_DIR/scripts/valhalla/prepare-valhalla.sh"

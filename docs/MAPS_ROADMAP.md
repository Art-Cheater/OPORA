# Дорожная карта картографического стека «Опоры»

## Назначение

Документ фиксирует картографический стек `MapLibre GL JS + Photon + Valhalla`.
Основные карты Request, Defect, Work Orders, WorkPlan и Waybill уже используют
MapLibre. Leaflet оставлен только как legacy для карт Agreements до отдельной
изолированной миграции этого read-only модуля.

## Текущее состояние

- `Request.latitude` / `Request.longitude` и `Defect.latitude` /
  `Defect.longitude` имеют тип `Numeric(10, 7)`.
- `coordinates_source` различает `manual`, `geocoder`, `import` и `unknown`;
  ручная точка имеет приоритет над автоматическим геокодированием.
- JSON карт совместим с будущим renderer: `id`, `type`, `number`, `address`,
  `lat`, `lng`, `url`, `in_plan`, `color`.
- Рабочий frontend использует MapLibre через `app/static/js/ops-map.js` и
  единый интерфейс `window.OporaMap` (`window.OporaOpsMap` — compatibility alias).
- Адресные подсказки используют локальный каталог улиц Кирова и Nominatim;
  `PhotonGeocodingProvider` доступен при `GEOCODING_PROVIDER=photon`.
- `RoutingService` поддерживает существующий OSRM-совместимый endpoint и
  Valhalla. При ошибке road route не подменяется прямой линией.

## Целевой стек

```text
OPORA Flask/PostgreSQL
  -> Request / Defect coordinates
  -> MapLibre GL JS (GeoJSON source, clusters, vector tiles)
  -> Photon (forward + reverse geocoding)
  -> Valhalla (route, matrix, optimization)
```

MapLibre не содержит собственных тайлов: style URL задаётся через
`MAPLIBRE_STYLE_URL`. На первом этапе допустим OpenFreeMap или другой
согласованный vector style; позднее — собственный tiles/style source.

## Ручная точка

Формы Request и Defect позволяют ввести широту/долготу или нажать «Указать на
карте». Клик в модальном Leaflet picker заполняет форму и выставляет
`coordinates_source=manual`. Изменение адреса только предупреждает: «Адрес
изменён. Проверьте точку на карте», но не затирает точку. В будущем можно
использовать `reverse_geocode(lat, lng)` Photon для предложения адреса; адрес
нельзя заменять автоматически.

## Поэтапное внедрение

1. **MapLibre.** Поддерживать `lat/lng`, ручные точки, raw addresses деревень,
   GeoJSON clustering, marker state и cleanup перед SPA navigation.
2. **Valhalla.** Настроить backend и `ROUTING_PROVIDER=valhalla`.
   API маршрута получает точки в текущем порядке и возвращает GeoJSON
   `LineString`, `distance_m`, `duration_s` либо `routing_unavailable`.
3. **Photon.** Подключить локальный/согласованный Photon через
   `GEOCODING_PROVIDER=photon`; локальный каталог улиц сохраняется первым
   уровнем exact/stable matching.
4. **Дальнейшие маршруты.** Добавить Valhalla matrix для nearby, отдельное
   подтверждаемое действие «Оптимизировать» и сохранение road geometry.

## Адреса и nearby

Порядок адресной логики: локальное точное/стабильное совпадение улицы Кирова,
затем Photon или Nominatim для координат. Для деревенских журналов сохраняется
raw address, не применяется городской autocomplete и не выполняется
неуверенное геокодирование. Nearby сохраняет exact PP и текущий fallback:
дорожная дистанция при доступном routing, приблизительная — при недоступном.

## Valhalla и API

```env
ROUTING_PROVIDER=valhalla
VALHALLA_BASE_URL=http://valhalla:8002
# либо существующий ROUTING_BASE_URL для OSRM-совместимого provider
```

`GET /work-orders/route.json` остаётся совместимым с текущим Work Orders UI и
возвращает `ok`, `route.geometry` (GeoJSON), `distance_m`, `duration_s`.
Если provider не настроен или недоступен, ответ содержит
`ok: false`, `error: routing_unavailable`; frontend показывает ошибку и не
рисует фальшивый дорожный маршрут.

Будущая модель сохранённого маршрута WorkPlan: `total_distance_m`,
`total_duration_s`, `route_geometry`, `route_updated_at`; порядок задаёт уже
существующий `WorkPlanItem.sequence`. Пока road route не сохраняется, migration
ради этих полей не нужна.

## Локальная инфраструктура (не production deploy)

Тяжёлые Photon/Valhalla контейнеры намеренно не добавлены в
`docker-compose.yml`. Для локального стенда нужен отдельный override:

```yaml
services:
  photon:
    image: komoot/photon:latest
    volumes:
      - ./data/photon:/photon/photon_data
  valhalla:
    image: ghcr.io/gis-ops/docker-valhalla/valhalla:latest
    volumes:
      - ./data/valhalla:/custom_files
```

Перед запуском загрузить OSM extract Кировской области согласно документации
выбранного образа, подготовить tiles (`valhalla_build_tiles`) и проверить health
запросами `/api?q=Киров` (Photon) и `/route` (Valhalla). В production контейнеры,
OSM data volume и публичные URL вводятся только отдельным решением; в текущем
пакете deploy не выполняется.

## Конфигурация

```env
MAP_PROVIDER=maplibre
MAP_FRONTEND_PROVIDER=maplibre
# Для self-hosted tiles замените OpenFreeMap URL своим style.json.
MAPLIBRE_STYLE_URL=https://tiles.openfreemap.org/styles/liberty
GEOCODING_PROVIDER=nominatim # или photon
PHOTON_BASE_URL=http://photon:2322
PHOTON_REGION_BIAS=Киров, Кировская область
ROUTING_PROVIDER=valhalla # либо osrm для совместимого старого endpoint
ROUTING_BASE_URL=
VALHALLA_BASE_URL=http://valhalla:8002
```

Ни ключи, ни production credentials в документе не хранятся.

## Диагностика маршрутизации

Для Valhalla задайте `ROUTING_PROVIDER=valhalla` и
`VALHALLA_BASE_URL=http://valhalla:8002`; для OSRM-совместимого сервиса
используйте `ROUTING_BASE_URL`. Пока URL не задан, маршрут намеренно не
подменяется прямой линией. Проверка без записи в БД: `flask check-routing`.

## Сложные адреса

`flask repair-work-coordinates --entity requests --only-missing --dry-run
--build-points --limit 20` безопасно показывает распознанные диапазоны и списки
домов. Автоматический backfill не запускается. Сейчас сохраняется первая
успешная anchor-точка в существующие `latitude/longitude`; отдельная таблица
multi-point для одной заявки требует отдельной миграции и ещё не вводилась.

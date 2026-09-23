# Карты ОПОРЫ

Все рабочие карты рисует MapLibre GL JS. Общие настройки и слои лежат в
`app/static/js/map/`. Страницы по-прежнему вызывают `window.OporaMap`
(`window.OporaOpsMap` — то же самое).

## Что где лежит

| Файл | Назначение |
| --- | --- |
| `js/map/config.js` | style URL, центр, zoom, порог подъездов |
| `js/map/core.js` | загрузка MapLibre, resize, таймаут подложки |
| `js/map/markers.js` | цвет точки по типу и статусу |
| `js/map/layers.js` | кластеры, маршрут, подъезды |
| `js/map/geocoder.js` | вызовы `/api/geo/search` и `/api/geo/reverse` |
| `js/map/routing.js` | вызов `POST /api/routes` |
| `js/ops-map.js` | карта журнала, плана и объектов |

Центр по умолчанию — Киров, `[49.668, 58.6035]`, zoom 12. Значения задаются
в `app/config.py` и попадают на страницу через meta-теги
`app/templates/components/map_scripts.html`. В JavaScript адрес тайлов не
прописан отдельно в каждом разделе.

Подложка: `MAPLIBRE_STYLE_URL`, по умолчанию
`https://tiles.openfreemap.org/styles/liberty`. Это векторный стиль
OpenFreeMap на данных OpenMapTiles. На крупном масштабе видны здания и номера
домов. Подъезды OSM (`entrance=*`) в этом стиле отдельным слоем не приходят,
поэтому они рисуются своими точками. У публичного OpenFreeMap нет SLA и есть
ограничение частоты. Для production его можно оставить, пока нагрузка небольшая.
Свой tileserver нужен, когда лимит или отсутствие договора станут проблемой.
Менять источник без своей инфраструктуры не нужно.

## Разделы

| Раздел | Маршрут данных | Движок |
| --- | --- | --- |
| Заявки | `GET /requests/map.json` | MapLibre |
| Дефекты | `GET /defects/map.json` | MapLibre |
| Заявки по деревням | тот же журнал, фильтр деревенского журнала | MapLibre |
| План мастера | `GET /work-orders/map.json`: заявки, дефекты, деревни, работы рядом | MapLibre, только точки |
| Объекты | `GET /objects/map.json` | MapLibre |
| Договоры | `GET /agreements/map.json` | MapLibre |
| IRZ | `GET /irz/map-summary`, киоск `/irz/map-display` | MapLibre, квадратные маркеры |

Ответ карты: `points`, `geojson` (`FeatureCollection`) и `remaining`.
Точка без чисел, с `NaN` или вне диапазона широты/долготы в GeoJSON не попадает.
Если координат нет, карта показывает «Координаты не заданы» и не падает.

Для большого списка есть bbox: `min_lat`, `max_lat`, `min_lon`, `max_lon`.
Неполный bbox — ошибка, а не вся база. Журналы отдают не больше 500 точек.

Цвета: заявка синяя, дефект красный, деревня коричневая, объект голубой,
выбранное в план зелёное, работа рядом бирюзовая, завершённое серое.
IRZ остаётся со своими квадратами по состоянию связи.

Карта отдаёт только то, на что есть право модуля. Пользователь без
`defects.view` не получает дефекты ни с `/defects/map.json`, ни с карты
мастера, ни из «работ рядом».

Новая сущность подключается так: хранит `latitude`/`longitude`, отдаёт GeoJSON
через свой route с проверкой права и рисуется через `OporaMapKit`, а не
отдельной библиотекой.

## Статус

```text
flask geo-status
flask security-status
```

`geo-status` печатает число населённых пунктов, улиц и домов, число подъездов
и время последнего импорта, провайдер геокодера, адрес стиля карты, каталог
`/opt/opora/data/geo` и флаги проверки входа. Если архива ещё нет, статус
пишет `not found` и не падает. Секрет Turnstile не печатается. Строка
маршрутов всегда `Disabled / not in current scope`: отсутствие Valhalla — не ошибка.

Проверка входа в production включается только переменными окружения, не кодом:

```text
CAPTCHA_ENABLED=1
TURNSTILE_SITE_KEY=...
TURNSTILE_SECRET_KEY=...
```

В Cloudflare Turnstile в список hostname добавляется домен, с которого
открывается сайт: `opora.zheleznogame.ru`. Реальные ключи в git не кладутся.
Если скрипт виджета не загрузился, форма входа показывает ошибку и не
отправляется. Таймаут проверки на сервере тоже не пропускает вход.

## Порядок на сервере

Деплой не скачивает ГАР и OSM и не импортирует адреса.

```text
mkdir -p /opt/opora/data/geo
# сюда кладут архив ГАР (*.zip) и OSM PBF (*.osm.pbf)
ls -lh /opt/opora/data/geo

cd /opt/opora
sudo bash scripts/deploy.sh

docker compose exec -T web ls -lh /data/geo
docker compose exec -T web stat /data/geo/<real-filename>.zip
docker compose exec -T web stat /data/geo/<real-filename>.osm.pbf
docker compose exec -T web flask db current
docker compose exec -T web flask geo-status

docker compose exec -T web flask geo-import-gar \
  --archive /data/geo/<real-filename>.zip \
  --region 43

docker compose exec -T web flask geo-import-entrances \
  --pbf /data/geo/<real-filename>.osm.pbf

docker compose exec -T web flask geo-status
```

`flask db current` после этой поставки должен показать ревизию
`063_geo_gar_entrances` (она идёт следом за `062_geo_directory`).
Дальше открыть карты заявок, дефектов, деревень, объектов, плана и IRZ.
Архив ГАР привозит официальный адрес. Координата дома запрашивается у
геокодера, когда этот дом ищут, и только точное совпадение дома сохраняется.

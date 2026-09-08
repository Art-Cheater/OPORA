# Дорожные маршруты OPORA: Valhalla

Valhalla выбран как основной provider: он строит реальные автомобильные маршруты
по OSM, а позднее позволит добавить matrix и явную оптимизацию порядка работ.
Он является **опциональной** инфраструктурой: OPORA, карты и планы запускаются
без Valhalla.

## Обычный deploy OPORA

```bash
cd /opt/opora && sudo bash scripts/deploy.sh
```

После него можно проверить сайт без маршрутизации:

```bash
curl -fsS http://127.0.0.1:5000/health
```

## Однократная подготовка маршрутизации

1. Положите небольшой OSM extract Кирова или Кировской области, но не России,
   в `/opt/opora/data/osm/kirov-oblast-latest.osm.pbf`.
2. Подготовьте tiles (скрипт ничего не скачивает):

```bash
cd /opt/opora
sudo bash scripts/routing/prepare-routing.sh \
  --provider valhalla \
  --pbf data/osm/kirov-oblast-latest.osm.pbf
```

3. В `.env` добавьте **по одной переменной на строку**:

```dotenv
ROUTING_PROVIDER=valhalla
ROUTING_BASE_URL=http://valhalla:8002
ROUTING_TIMEOUT_SECONDS=8
```

Правильно: отдельные строки выше. Неправильно:

```dotenv
ROUTING_PROVIDER=valhalla ROUTING_BASE_URL=http://valhalla:8002
```

4. Поднимите только optional provider:

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.routing.yml up -d valhalla
sudo docker compose -f docker-compose.yml -f docker-compose.routing.yml up -d --force-recreate web
sudo docker compose -f docker-compose.yml -f docker-compose.routing.yml exec -T web python -m flask check-routing
```

Порт Valhalla наружу не публикуется. Если routing выключен или tiles ещё
строятся, кнопка маршрута покажет ошибку, но карта и план продолжат работать.
Для выключения удалите три routing-переменные из `.env` отдельными строками и
выполните обычный deploy OPORA.

## Диагностика

```bash
sudo docker compose exec -T web python -m flask check-routing
sudo docker compose exec -T web python -m flask map-stats
```

`check-routing` выполняет короткий тест в Кирове. `map-stats` показывает
количество работ с координатами и без них; последние не попадут в маршрут.

PBF, tiles и generated routing files хранятся вне Git и не входят в Docker
build context. Автоматическая оптимизация порядка и сохранение geometry в БД
в этом этапе не выполняются: маршрут строго повторяет порядок «Мой план работ».

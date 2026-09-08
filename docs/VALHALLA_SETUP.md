# Valhalla: дорожные маршруты OPORA

Valhalla — опциональный внутренний сервис дорожной маршрутизации. Основной
`docker-compose.yml` намеренно не запускает его: OPORA остаётся доступной без
маршрутов, а маршрут не подменяется прямой линией.

Используется официальный образ `ghcr.io/valhalla/valhalla-scripted:3.8.3`.
Он читает OSM PBF и создаёт tiles в `data/valhalla/`. PBF, tiles, архивы и
служебные базы исключены из Git.

## Подготовка сервера

Работайте в каталоге проекта. Команды Docker могут требовать `sudo`.

```bash
cd /opt/opora
git pull origin main
mkdir -p data/valhalla
```

Скопируйте OSM extract, содержащий Киров и нужную территорию обслуживания, в
следующий путь:

```text
/opt/opora/data/valhalla/kirov-oblast-latest.osm.pbf
```

Файл PBF не скачивается скриптом автоматически: это осознанно, чтобы не
получить многогигабайтную загрузку без решения администратора.

## Построение данных

```bash
cd /opt/opora
sudo bash scripts/valhalla/prepare-valhalla.sh
```

Скрипт проверяет PBF, создаёт каталог данных и запускает только `valhalla`
через основной Compose и routing override. При первом запуске Valhalla строит
tiles; это может занять длительное время. Следите за процессом:

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.routing.yml logs -f valhalla
```

Повторный запуск безопасен: образ использует существующие tiles, если PBF не
менялся. Чтобы использовать PBF с другим именем, сначала положите его в
`data/valhalla/`, затем укажите абсолютный путь:

```bash
sudo VALHALLA_PBF_PATH=/opt/opora/data/valhalla/another.osm.pbf \
  bash scripts/valhalla/prepare-valhalla.sh
```

## Конфигурация OPORA

Добавьте в `/opt/opora/.env` ровно следующие параметры. Не используйте
Markdown-ссылки и не публикуйте порт 8002 наружу.

```env
ROUTING_PROVIDER=valhalla
VALHALLA_BASE_URL=http://valhalla:8002
ROUTING_BASE_URL=
ROUTING_TIMEOUT_SECONDS=3
```

Запустите routing override, затем обязательно пересоздайте только `web`, чтобы
он прочитал изменённый `.env`:

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.routing.yml up -d valhalla
sudo docker compose -f docker-compose.yml -f docker-compose.routing.yml up -d --force-recreate web
```

`web` не имеет жёсткого `depends_on` от Valhalla. Если routing недоступен,
заявки, дефекты и карты продолжают работать; UI покажет понятное сообщение.

## Проверка

Убедитесь, что сервис есть и не публикует порт наружу:

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.routing.yml ps
```

Проверьте внутренний маршрут из web-контейнера:

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.routing.yml \
  exec -T web python -m flask check-routing
```

Команда печатает provider и адрес. При пустом URL, ошибке DNS, отказе соединения
или неготовых tiles она заканчивается короткой диагностикой без traceback.
После успешной проверки откройте «Работа с заявками», добавьте две работы с
координатами и нажмите «Построить маршрут».

## Диагностика

- `service "valhalla" is not running` — повторите команду `up -d` с обоими
  compose-файлами.
- Контейнер перезапускается — смотрите `logs -f valhalla`; чаще всего отсутствует
  PBF либо ещё идёт построение tiles.
- `check-routing` не может подключиться — убедитесь, что URL ровно
  `http://valhalla:8002` и `web` запущен с тем же compose override.
- Не удаляйте `data/valhalla/` или Docker volumes командой `down -v`: там лежат
  большие подготовленные routing-данные.

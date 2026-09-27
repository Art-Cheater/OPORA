# Staging и production

Рабочая цепочка: `LOCAL → GitHub main → STAGING → ручная проверка → PRODUCTION`.
Никакой автоматической доставки из GitHub на серверы здесь не настраивается.

| Окружение | Назначение | Адрес | Правила |
| --- | --- | --- | --- |
| Staging | Проверка изменений | `20.42.0.122` | Отдельные PostgreSQL и uploads; нет команд production-платам и production DB. |
| Production | Рабочая система | `46.19.66.5` | Реальные пользователи, uploads, интеграции и будущие устройства. |

Production URL: `https://opora.truthqwark.ru`. `opora.zheleznogame.ru`
перенаправляется на него с сохранением пути и query. Чтобы временно открывать
старый адрес как отдельный сайт, в `.env` поставьте `OPORA_LEGACY_REDIRECT=0`.

Платы подключаются raw TCP без TLS к `tcp.truthqwark.ru:5000`. Прежние
`tcp.zheleznogame.ru:5000` и IP сервера продолжают работать. Счётчики ATM21
используют порт `5009` на тех же именах. Внутренний API модема `5010` наружу
не публикуется. На staging `tcp-gateway` отсутствует из Compose-стека;
реальные device secrets туда не переносятся.

## Deploy

На обоих серверах главная команда остаётся прежней:

```bash
cd /opt/opora
git pull
sudo bash scripts/deploy.sh
```

`OPORA_ENV=staging` подключает `docker-compose.staging.yml`, который не запускает
TCP gateway и помещает EIS, inquiry и documents-notify в неактивный профиль
`external-sync`. `OPORA_ENV=production` подключает
`docker-compose.timeweb.example.yml`: host `80/443` принадлежат nginx, а `5000`
— только tcp-gateway; PostgreSQL и web наружу не опубликованы.

Сначала deploy на staging и ручная проверка. Только после этого допускается
production deploy. Скрипт не source-ит `.env`, выбирает overlay по одному ключу
`OPORA_ENV` и выполняет pre-flight. При несовместимости BuildKit на Debian он
повторяет только build с `DOCKER_BUILDKIT=0`.

## Refresh staging DB

Допускается односторонняя копия: `pg_dump` на production → transfer → restore в
отдельную staging PostgreSQL. Staging-изменения при refresh теряются; обратного
копирования и общей БД быть не может. Uploads переносятся отдельным архивом
только при необходимости теста, без production device secrets.

## Volumes и сертификаты

Timeweb overlay объявляет существующий восстановленный `uploads_data` как
external volume, поэтому Compose не пытается создать или удалить его. Base
compose не менялся и на новой/локальной установке создаёт volume сам.
`TLS_CERTS_DIR=/etc/letsencrypt` монтируется в nginx read-only. `deploy.sh`
выпускает отдельный сертификат `opora.truthqwark.ru` через webroot, не удаляя
сертификат `opora.zheleznogame.ru`. Если сертификата ещё нет, nginx сначала
поднимается со старым сайтом, затем Certbot и `nginx -s reload` — без второго
перезапуска TCP. Hook `renewal-hooks/deploy/opora-nginx-reload.sh` делает тот
же reload после автоматического продления.

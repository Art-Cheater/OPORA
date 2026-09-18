# Переезд OPORA на Timeweb Cloud

Этот документ — runbook, а не команда deploy. До cutover старый production не
изменять. Использовать новый сервер только после тестового restore и пилота с
одной платой.

## Целевая схема

`443 -> nginx -> web:5000`; raw `5000 -> tcp-gateway:5000`. `db`, Valhalla и
внутренние API доступны только внутри Compose. Для Timeweb запускается overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.timeweb.example.yml config
```

Нужны DNS-only записи `opora.zheleznogame.ru` и `tcp.zheleznogame.ru`; raw TCP
нельзя проксировать HTTP-режимом CDN. TLS-сертификат и private keys остаются на
сервере в каталоге, смонтированном в nginx, и никогда не попадают в Git.

## Данные и rollback

До остановки старого сервера сделать согласованный `pg_dump` и архив uploads,
проверить checksum, передать по защищённому каналу, восстановить на Timeweb и
сверить Alembic head, число активных записей и выборочно файлы. Критичные данные:
PostgreSQL, uploads, `.env`, TLS certificates, Valhalla tiles. Пересобираемы:
images, static assets, Python dependencies, Nginx image.

Cutover: короткое maintenance window, финальный dump/uploads, restore, migrate,
healthcheck `web` и `tcp-gateway`, smoke login, затем pilot одного устройства.
При откате вернуть DNS/ingress на старый сервер только после остановки записи на
новом; не выполнять двустороннюю запись в PostgreSQL.

## Backup и восстановление

Ежедневно: `pg_dump` + архив uploads, retention минимум 7 дней, copy в S3 только
через переменные окружения и серверный credential store. Раз в месяц проверять
restore в отдельную БД/volume. Секреты VAPID, Turnstile, DB и ключ шифрования
устройств резервировать через защищённый менеджер секретов, не вместе с кодом.

## Production pre-flight

`scripts/backup-opora.sh` создаёт PostgreSQL custom dump и архив uploads,
применяет retention и, только при явно заданном `BACKUP_S3_URI`, передаёт файлы
через настроенный на хосте AWS CLI. До cutover выполнить test restore в отдельную
БД/volume.

До запуска проверить: уникальные `SECRET_KEY`, DB credentials, `CAPTCHA_ENABLED=1`
и оба Turnstile ключа, `SESSION_COOKIE_SECURE=True`,
`REMEMBER_COOKIE_SECURE=True`, `PROXY_FIX_ENABLED=True`, Fernet key gateway,
занятость портов 80/443/5000, healthchecks и свободное место для backups/tiles.

# Запуск OPORA на Debian 13 (Docker Engine, не Docker Desktop)

Прод крутится на **отдельном Debian 13 stable**. Разработка — на другом ПК.  
Пуш в `main` → self-hosted runner на этом же сервере → `scripts/deploy.sh`.

Данные БД — Docker-том `postgres_data`. **Никогда не выполняйте** `docker compose down -v`.

Рекомендуемый путь репозитория: `/opt/opora`.

---

## 0. Перенос с текущего Windows (один раз)

Пока Windows-сервер ещё жив.

### На Windows (сейчас `C:\OPORA`)

```powershell
cd C:\OPORA
docker compose stop eis-sync inquiry-sync
.\scripts\backup-db.ps1
docker volume ls
# обычно opora_uploads_data — подставьте точное имя:
docker run --rm -v opora_uploads_data:/data -v ${PWD}:/backup alpine tar czf /backup/uploads-migrate.tar.gz -C /data .
```

Если том загрузок называется иначе: `docker volume ls` и подставьте имя в `-v ИМЯ:/data`.

Скопируйте на Debian (флешка, scp, общая папка):

- `Desktop\OPORA_backups\opora_ГГГГ-ММ-ДД.dump`
- `C:\OPORA\.env`
- `C:\OPORA\uploads-migrate.tar.gz`

Сайт на Windows можно оставить работать, пока Debian не проверен. Потом выключить Windows-контейнеры, чтобы не было двух заборов почты.

### На Debian — после шагов 1–3 ниже

```bash
cd /opt/opora
# .env уже должен лежать здесь (тот же, что на Windows)
docker compose up -d db
# дождитесь healthy:
docker compose ps

docker cp /путь/к/opora_ГГГГ-ММ-ДД.dump opora_db:/tmp/restore.dump
docker exec -it opora_db pg_restore -U opora_user -d opora --clean --if-exists /tmp/restore.dump
# код выхода 1 у pg_restore с предупреждениями часто нормален; проверьте, что таблицы на месте

docker run --rm -v opora_uploads_data:/data -v /путь/к/каталогу/с/архивом:/backup alpine \
  tar xzf /backup/uploads-migrate.tar.gz -C /data

docker compose up --build -d
docker compose ps
```

Откройте сайт по IP Debian. Если списки и файлы на месте — переключите пользователей на новый адрес и **остановите** Windows: `docker compose down` (без `-v`) плюс выключите старый GitHub runner.

---

## 1. Что установить на Debian 13

```bash
sudo apt update
sudo apt install -y ca-certificates curl git ufw

# Docker Engine (официальный репозиторий Docker)
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

sudo usermod -aG docker "$USER"
# перелогиньтесь, затем:
git --version
docker version
docker compose version
```

Если `apt update` не находит `trixie` у Docker — в `docker.list` временно поставьте `bookworm` вместо `$VERSION_CODENAME` или поставьте пакеты Debian: `apt install docker.io docker-compose-v2`.

Часовой пояс (бэкап в 03:00 и ЕИС 12:00/18:00):

```bash
sudo timedatectl set-timezone Europe/Moscow
```

Файрвол: наружу только сайт (сейчас порт 5000). Postgres и gunicorn в файрвол не публикуются.

```bash
sudo ufw allow OpenSSH
sudo ufw allow 5000/tcp
sudo ufw enable
```

---

## 2. Клонирование и `.env`

```bash
sudo mkdir -p /opt/opora
sudo chown "$USER:$USER" /opt/opora
git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ> /opt/opora
cd /opt/opora
cp .env.example .env
nano .env
```

При переносе с Windows — положите **тот же** `.env`, не генерируйте новый `SECRET_KEY` (иначе все сессии слетят; пароли пользователей в БД не затронет, но cookie станут невалидны).

В `.env` обязательно:

| Переменная | Значение |
|------------|----------|
| `SECRET_KEY` | тот же, что на Windows, либо новая длинная случайная строка |
| `POSTGRES_PASSWORD` | тот же, что в дампе / старом `.env` |
| `POSTGRES_HOST` | `db` |
| `FLASK_ENV` | `production` |

`.env` **не коммитить**.

Сделайте скрипты исполняемыми:

```bash
chmod +x scripts/*.sh
```

---

## 3. Первый запуск (чистый сервер без переноса)

Если базу переносите — сначала раздел 0, не этот.

```bash
cd /opt/opora
docker compose up --build -d
docker compose ps
```

Сайт: http://IP-СЕРВЕРА:5000  

Снаружи слушает **nginx** (`5000:80`). Gunicorn и PostgreSQL на хост не публикуются.

`SECRET_KEY` из примера в production контейнер `web` не поднимет.

Конвертация `.doc`/`.rtf`/`.pdf` → `.docx`: в образ web LibreOffice по умолчанию не ставится. Нужно — `docker compose build --build-arg WITH_LIBREOFFICE=1`.

Логи:

```bash
docker compose logs -f nginx
docker compose logs -f web
docker compose logs -f db
```

На сервере **не** запускайте `docker-compose.dev.yml` (bind-mount `.` убивает скорость).

---

## 4. Self-hosted runner (Linux)

1. GitHub: **Settings → Actions → Runners → New self-hosted runner** → **Linux x64**.  
2. Команды, которые покажет GitHub (`mkdir`, `tar`, `./config.sh`). Каталог, например `/opt/actions-runner`.  
3. При `config` имя вроде `opora-debian`.  
4. Как служба:

```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

5. Старый **Windows**-runner в GitHub удалите или остановите — иначе деплой может уехать не туда.

Workflow [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) берёт только runner с меткой `Linux` и запускает `/opt/opora/scripts/deploy.sh` (путь: переменная репозитория `OPORA_ROOT`).

Скрипт: `git fetch` + `reset --hard origin/main` + `docker compose up --build -d`, **без** `-v`.

---

## 5. Ежедневный бэкап БД

Каталог: `/var/backups/opora/`  
Файлы: `opora_YYYY-MM-DD.dump`, хранение **14 дней**.

От root:

```bash
cd /opt/opora
sudo ./scripts/install-backup-cron.sh
```

Проверка:

```bash
sudo ./scripts/backup-db.sh
```

### Восстановление

```bash
docker cp /var/backups/opora/opora_YYYY-MM-DD.dump opora_db:/tmp/restore.dump
docker exec -it opora_db pg_restore -U opora_user -d opora --clean --if-exists /tmp/restore.dump
```

---

## 6. Команды на сервере

```bash
cd /opt/opora
docker compose ps
./scripts/deploy.sh
docker compose down          # тома БД сохраняются
# docker compose down -v    # ЗАПРЕЩЕНО — сотрёт базу
```

---

## 7. Локальная разработка (не сервер)

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Либо Python без Docker: `POSTGRES_HOST=localhost`.

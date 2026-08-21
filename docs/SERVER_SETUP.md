# Запуск OPORA на Windows-сервере (автодеплой + бэкапы)

Инструкция для **отдельного Windows-ПК**, на котором крутятся сайт и PostgreSQL в Docker.  
ПК разработки пушит в GitHub (`main`) — сервер сам подтягивает изменения и пересобирает контейнеры.

Данные БД хранятся в Docker-томе `postgres_data` и **не пропадают** при обычном деплое.  
**Никогда не выполняйте** `docker compose down -v` — флаг `-v` удалит базу.

---

## 1. Что установить

1. [Git for Windows](https://git-scm.com/download/win)  
2. [Docker Desktop](https://www.docker.com/products/docker-desktop/)  
   - Режим: **Linux containers**  
   - После установки перезагрузите ПК и дождитесь зелёного статуса Docker  

Проверка в PowerShell:

```powershell
git --version
docker version
docker compose version
```

---

## 2. Клонирование и `.env`

Рекомендуемый путь: `C:\OPORA` (его же использует workflow деплоя).

```powershell
cd C:\
git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ> OPORA
cd C:\OPORA
copy .env.example .env
notepad .env
```

В `.env` обязательно задайте:

| Переменная | Значение |
|------------|----------|
| `SECRET_KEY` | длинная случайная строка |
| `POSTGRES_PASSWORD` | надёжный пароль |
| `POSTGRES_HOST` | `db` (имя сервиса в Docker) |
| `DATABASE_URL` | `postgresql://USER:PASSWORD@db:5432/opora` (спецсимволы в пароле URL-кодируйте, `!` → `%21`) |
| `FLASK_ENV` | `production` |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | учётка первого администратора |

Файл `.env` **не коммитить** в git.

---

## 3. Первый запуск

```powershell
cd C:\OPORA
docker compose up --build -d
docker compose ps
```

Откройте в браузере: http://localhost:5000  

Снаружи слушает **nginx** (порт 5000 → контейнер :80). Gunicorn и PostgreSQL наружу не публикуются.

Логин — из `ADMIN_EMAIL` / `ADMIN_PASSWORD` в `.env`.

`SECRET_KEY` в production не должен оставаться значением из примера, иначе контейнер `web` не стартует.

Конвертация договоров `.doc`/`.rtf`/`.pdf` в `.docx` требует LibreOffice. В образ web он больше не ставится по умолчанию (тяжёлый apt). Если это нужно: `docker compose build --build-arg WITH_LIBREOFFICE=1`.

Логи при проблемах:

```powershell
docker compose logs -f nginx
docker compose logs -f web
docker compose logs -f db
```

---

## 4. Self-hosted runner (автодеплой из GitHub)

Чтобы после `git push` в `main` сервер сам обновлялся:

1. В GitHub: **Settings → Actions → Runners → New self-hosted runner**  
2. Выберите **Windows** и выполните команды, которые покажет GitHub (скачать, `config.cmd`, `run.cmd`).  
3. При `config` укажите имя runner’а, например `opora-server`.  
4. Установите runner **как службу Windows** (`install.cmd` / `run.cmd` от администратора — по подсказкам установщика Actions), чтобы он работал без открытого окна.  
5. В репозитории runner должен быть **Online**.

Workflow: [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml)  
Он запускает `C:\OPORA\scripts\deploy.ps1` (путь можно сменить через переменную репозитория `OPORA_ROOT`).

Скрипт деплоя:

- `git fetch` + `git reset --hard origin/main`
- `docker compose up --build -d`  
- **без** удаления томов

Проверка: с ПК разработки сделайте push в `main` → в GitHub Actions должен пройти job **Deploy** → на сервере обновится сайт, данные в БД останутся.

Как мерить скорость после выкладки: [PERFORMANCE.md](PERFORMANCE.md).  
Ветки и коммиты: [DEV_PROCESS.md](DEV_PROCESS.md).

---

## 5. Ежедневный бэкап БД на рабочий стол

Бэкапы пишутся в: `%USERPROFILE%\Desktop\OPORA_backups\`  
Формат: `opora_YYYY-MM-DD.dump`, хранение **14 дней**.

Один раз от **администратора**:

```powershell
cd C:\OPORA
powershell -ExecutionPolicy Bypass -File .\scripts\install-backup-task.ps1
```

Проверка вручную:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\backup-db.ps1
```

В Планировщике заданий появится задача `OPORA_DB_Backup_Daily` (ежедневно в 03:00).

### Восстановление из бэкапа

```powershell
docker cp "$env:USERPROFILE\Desktop\OPORA_backups\opora_YYYY-MM-DD.dump" opora_db:/tmp/restore.dump
docker exec -it opora_db pg_restore -U opora_user -d opora --clean --if-exists /tmp/restore.dump
```

(подставьте своего пользователя из `.env`, если отличается)

---

## 6. Полезные команды на сервере

```powershell
cd C:\OPORA

# Статус
docker compose ps

# Пересобрать вручную (как при деплое)
.\scripts\deploy.ps1

# Остановить контейнеры (данные БД сохраняются)
docker compose down

# ЗАПРЕЩЕНО — удалит том с базой:
# docker compose down -v
```

---

## 7. Локальная разработка (другой ПК)

На машине разработчика, с hot-reload исходников (**не на сервере** — bind-mount `.` на Windows сильно тормозит Python):

```powershell
copy .env.example .env
# в .env: POSTGRES_HOST=db, DATABASE_URL=...@db:5432/...
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Либо Python без Docker — тогда `POSTGRES_HOST=localhost` и локальный Postgres.

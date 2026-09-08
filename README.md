# Опора

Корпоративная информационная система для диспетчеризации, объектов освещения, закупок и внутренней работы сотрудников.

Репозиторий: [Art-Cheater/OPORA](https://github.com/Art-Cheater/OPORA)

## Что умеет система

| Раздел | Назначение |
|--------|------------|
| **Заявки** | Диспетчеризация: создание, назначение, статусы, материалы, файлы |
| **Объекты / проекты / торги** | Адресные лоты, проекты работ, заявки на закупки |
| **Контракты и подрядчики** | Контракты ЕИС и справочник организаций |
| **Договора на опоры** | Договоры на оборудование на опорах, карта точек, загрузка файлов |
| **Обращения** | Письма с корпоративной почты, вложения, пересылка сотруднику |
| **Импорт ЕИС** | Автозагрузка с zakupki.gov.ru (закупки с 2025 года) |
| **Мессенджер** | Чаты, файлы, карточки заявок, звук и уведомления |
| **Личные документы** | Приватный архив файлов сотрудника |
| **Отчёты** | Сводки по объектам и работе |
| **Роли и права** | Матрица доступа к разделам и полям |
| **Обучение** | Встроенный тур по интерфейсу и разделам (по роли) |

## Стек

| Слой | Технологии |
|------|------------|
| Backend | Python 3.12, Flask, SQLAlchemy, Flask-Migrate, Flask-Login |
| Frontend | Bootstrap 5, Jinja2, JavaScript (SPA-навигация) |
| БД | PostgreSQL 17 (Docker) |
| Инфра | Docker Compose, Gunicorn, Nginx |

## Архитектура

Модульные Flask Blueprint: каждый модуль — свои маршруты, сервисы, репозитории и шаблоны.

```
app/modules/<имя>/
├── blueprint.py
├── routes.py
├── services.py
├── repositories.py
├── forms.py
└── templates/<имя>/
```

Новый модуль: каталог по шаблону → запись в `app/modules/registry.py` → миграция → `flask db upgrade`.

## Быстрый старт

### Production (Debian + Docker)

Подробно: **[docs/SERVER_SETUP.md](docs/SERVER_SETUP.md)**

### Production recovery: повреждённый `.env`

Если `docker compose config` показывает несколько `KEY=value` внутри значения
одной переменной или web сообщает о стандартном `SECRET_KEY`, не отключайте
production-проверку. Сначала сохраните `.env` и исправьте формат: каждая
переменная должна занимать ровно одну строку.

```bash
cd /opt/opora
sudo cp .env ".env.backup.$(date +%Y%m%d-%H%M%S)"
sudo nano .env
python3 scripts/check_env.py .env
sudo bash scripts/deploy.sh
sudo docker compose ps
sudo docker compose logs --tail=100 web
```

Минимальный корректный production-блок (без реальных секретов):

```dotenv
FLASK_ENV=production
FLASK_DEBUG=0
SECRET_KEY=<long-random-value-at-least-32-characters>
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=opora
POSTGRES_USER=opora_user
POSTGRES_PASSWORD=<password>
POSTGRES_SCHEMA=opora
USE_SQLITE=0
WEB_CONCURRENCY=3
DB_POOL_SIZE=2
DB_MAX_OVERFLOW=0
INQUIRY_SYNC_INTERVAL_SECONDS=300
EIS_SSL_VERIFY=0
```

```bash
cd /opt/opora
cp .env.example .env   # один раз, заполнить секреты
docker compose up --build -d
# обновление с GitHub:
git fetch origin && git reset --hard origin/main
docker compose up --build --force-recreate -d
curl -s http://127.0.0.1:5000/health
```

Том `postgres_data` не удалять (`docker compose down -v` — нельзя).

### Локально (Docker)

```bash
cp .env.example .env
# POSTGRES_HOST=db, DATABASE_URL=...@db:5432/...
docker compose up --build -d
# разработка с hot-reload:
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Сайт: http://localhost:5000

### Без Docker

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux:   source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m flask db upgrade
python -m flask seed-reference-data
python -m flask sync-security
python -m flask seed-admin
python run.py
```

Или после `db upgrade`: `python -m flask init-db`.

## Учётка по умолчанию

| | |
|--|--|
| Email | `admin@opora.ru` |
| Пароль | `admin123` |

В production сразу смените пароль (`ADMIN_*` в `.env`).

## Роли (типовые)

Права настраиваются в разделе «Роли». Базовые коды:

| Код | Кто |
|-----|-----|
| `admin` | Полный доступ |
| `dispatcher` | Диспетчер заявок |
| `master` | Мастер |
| `executor` | Исполнитель |
| `director` | Руководство |

## CLI

```bash
python -m flask db upgrade
python -m flask db migrate -m "..."
python -m flask seed-admin
python -m flask seed-reference-data
python -m flask sync-security
python -m flask init-db
```

## Переменные окружения

Полный список — в `.env.example`. Основные:

| Переменная | Назначение |
|------------|------------|
| `SECRET_KEY` | Секрет Flask |
| `DATABASE_URL` / `POSTGRES_*` | Подключение к БД |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Первый администратор |
| `INQUIRY_IMAP_*` | Почта обращений |
| `EIS_YEAR_FROM` / `EIS_YEAR_TO` | Окно лет для импорта ЕИС |

## Документация

- [Установка на сервер](docs/SERVER_SETUP.md)
- [Процесс разработки](docs/DEV_PROCESS.md)
- [Производительность](docs/PERFORMANCE.md)
- [Дорожные маршруты (Valhalla)](docs/ROUTING_SETUP.md)

## Лицензия

Проприетарное ПО. Все права защищены.

# Опора — Корпоративная информационная система

Корпоративная информационная система для муниципального предприятия.

## Стек технологий

| Слой | Технологии |
|------|-----------|
| Backend | Python 3.12, Flask, SQLAlchemy, Flask-Migrate, Flask-Login |
| Frontend | Bootstrap 5, Jinja2, JavaScript, Bootstrap Icons |
| БД | PostgreSQL 16 |
| Инфраструктура | Docker, Docker Compose, Gunicorn |

## Архитектура

Проект построен на **модульной архитектуре** с использованием Flask Blueprint. Каждый модуль — независимый функциональный блок со своей бизнес-логикой, моделями, маршрутами и шаблонами.

### Принципы

- **SOLID** — разделение ответственности между слоями
- **Application Factory** — создание приложения через `create_app()`
- **Repository Pattern** — абстракция доступа к данным
- **Service Layer** — бизнес-логика отделена от контроллеров
- **Модульность** — каждый Blueprint независим и подключается через реестр

### Структура модуля

```
app/modules/<module_name>/
├── __init__.py          # Экспорт Blueprint
├── blueprint.py         # Определение Blueprint
├── models.py            # SQLAlchemy-модели
├── repositories.py      # Слой доступа к данным
├── services.py          # Бизнес-логика
├── forms.py             # WTForms (при необходимости)
├── routes.py            # Контроллеры (маршруты)
└── templates/<module>/    # Шаблоны модуля
```

### Добавление нового модуля

1. Создайте директорию `app/modules/<name>/` по шаблону выше
2. Определите Blueprint в `blueprint.py`
3. Импортируйте Blueprint в `app/modules/registry.py` и добавьте в `ALL_BLUEPRINTS`
4. Создайте миграцию: `flask db migrate -m "Add <name> module"`
5. Примените миграцию: `flask db upgrade`

## Быстрый старт

### Docker (рекомендуется)

```bash
# Клонировать и перейти в директорию проекта
cd sait

# Скопировать конфигурацию
cp .env.example .env

# Запустить
docker compose up --build
```

Приложение доступно по адресу: http://localhost:5000

### Локальная разработка (PostgreSQL)

```bash
# Создать виртуальное окружение
python -m venv .venv

# Активировать (Windows)
.venv\Scripts\activate

# Активировать (Linux/macOS)
source .venv/bin/activate

# Установить зависимости
pip install -r requirements.txt

# Скопировать и заполнить .env (DATABASE_URL / POSTGRES_*)
cp .env.example .env

# Применить миграции, справочники и администратора
python -m flask db upgrade
python -m flask seed-reference-data
python -m flask sync-security
python -m flask seed-admin

# Запустить сервер разработки
python run.py
```

Либо одной командой после `db upgrade`: `python -m flask init-db`.

## Учётные данные по умолчанию

| Поле | Значение |
|------|----------|
| Email | admin@opora.ru |
| Пароль | admin123 |

> Измените пароль администратора в `.env` перед развёртыванием в production.

## CLI-команды

```bash
python -m flask db upgrade           # Применить миграции (создать/обновить таблицы)
python -m flask db migrate -m "..."  # Создать новую миграцию
python -m flask seed-admin           # Создать администратора по умолчанию
python -m flask seed-reference-data  # Справочники
python -m flask sync-security        # Роли и разрешения
python -m flask init-db              # Сиды после db upgrade
```

## Переменные окружения

См. `.env.example` для полного списка переменных.

| Переменная | Описание | По умолчанию |
|-----------|----------|-------------|
| `SECRET_KEY` | Секретный ключ Flask | — |
| `DATABASE_URL` | URL PostgreSQL | — |
| `POSTGRES_SCHEMA` | Схема PostgreSQL (по умолчанию `opora`) | opora |
| `FLASK_ENV` | Окружение (development/production) | development |
| `ADMIN_EMAIL` | Email администратора | admin@opora.ru |
| `ADMIN_PASSWORD` | Пароль администратора | admin123 |

## Роли пользователей

| Роль | Описание |
|------|----------|
| `admin` | Полный доступ к системе |
| `manager` | Управление подразделением |
| `employee` | Стандартный сотрудник |
| `viewer` | Только просмотр |

## Лицензия

Проприетарное ПО. Все права защищены.

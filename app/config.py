"""Конфигурация приложения «Опора»."""

import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)


def _use_sqlite() -> bool:
    """Временный локальный режим без PostgreSQL (USE_SQLITE=1 / true / yes)."""
    return os.getenv("USE_SQLITE", "").strip().lower() in {"1", "true", "yes", "on"}


def _sqlite_url() -> str:
    """Файл SQLite в instance/opora.db (или DATABASE_URL=sqlite:///...)."""
    raw = os.getenv("DATABASE_URL", "").strip()
    if raw.startswith("sqlite:"):
        return raw
    db_path = (INSTANCE_DIR / "opora.db").resolve()
    return f"sqlite:///{db_path.as_posix()}"


def _build_postgres_url() -> str | None:
    """Собирает URL из POSTGRES_* (пароль с спецсимволами кодируется)."""
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    if not user or password is None:
        return None
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "opora")
    return (
        f"postgresql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{db_name}"
    )


def _default_database_url() -> str:
    """DATABASE_URL / USE_SQLITE / POSTGRES_*."""
    if _use_sqlite():
        return _sqlite_url()

    raw = os.getenv("DATABASE_URL", "").strip()
    if raw:
        if raw.startswith("sqlite:"):
            return raw
        # heroku-style postgres:// → postgresql://
        if raw.startswith("postgres://"):
            raw = "postgresql://" + raw[len("postgres://") :]
        return raw

    built = _build_postgres_url()
    if built:
        return built

    raise RuntimeError(
        "Не задана база данных. Укажите USE_SQLITE=1, DATABASE_URL или "
        "POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_HOST / POSTGRES_DB в .env"
    )


def _engine_options(database_url: str) -> dict:
    """Параметры движка: SQLite или PostgreSQL (search_path схемы opora)."""
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}

    schema = os.getenv("POSTGRES_SCHEMA", "opora").strip() or "public"
    options: dict = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    if schema and schema != "public":
        # Таблицы создаются в схеме, которой владеет приложение
        options["connect_args"] = {"options": f"-csearch_path={schema},public"}
    return options


_DATABASE_URL = _default_database_url()


class Config:
    """Базовая конфигурация."""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    APP_NAME = os.getenv("APP_NAME", "Опора")
    APP_VERSION = os.getenv("APP_VERSION", "0.1.0")

    SQLALCHEMY_DATABASE_URI = _DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = _engine_options(_DATABASE_URL)
    POSTGRES_SCHEMA = os.getenv("POSTGRES_SCHEMA", "opora").strip() or "public"
    USE_SQLITE = _DATABASE_URL.startswith("sqlite")

    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "False").lower() == "true"
    REMEMBER_COOKIE_SECURE = os.getenv("REMEMBER_COOKIE_SECURE", "False").lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_NAME = "opora_session"
    REMEMBER_COOKIE_NAME = "opora_remember"

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@opora.ru")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
    ADMIN_FULL_NAME = os.getenv("ADMIN_FULL_NAME", "Администратор системы")

    UPLOAD_FOLDER = INSTANCE_DIR / "uploads"
    # Лимит всего запроса (несколько файлов). По умолчанию 64 МБ, через .env: MAX_UPLOAD_MB=100
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "64")) * 1024 * 1024
    MAX_UPLOAD_FILES = int(os.getenv("MAX_UPLOAD_FILES", "20"))
    MAX_UPLOAD_FILE_MB = int(os.getenv("MAX_UPLOAD_FILE_MB", "32"))
    MESSENGER_ONLINE_TIMEOUT = int(os.getenv("MESSENGER_ONLINE_TIMEOUT", "120"))
    MESSENGER_POLL_INTERVAL_MS = int(os.getenv("MESSENGER_POLL_INTERVAL_MS", "8000"))
    MESSENGER_UNREAD_INTERVAL_MS = int(os.getenv("MESSENGER_UNREAD_INTERVAL_MS", "45000"))


class DevelopmentConfig(Config):
    """Конфигурация для разработки (PostgreSQL)."""

    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Конфигурация для production (PostgreSQL)."""

    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True


class TestingConfig(Config):
    """Конфигурация для тестов (отдельный URL или in-memory SQLite)."""

    TESTING = True
    DEBUG = True
    WTF_CSRF_ENABLED = False

    @classmethod
    def _test_uri(cls) -> str:
        raw = os.getenv("TEST_DATABASE_URL", "").strip()
        if raw:
            return raw
        return "sqlite:///:memory:"

    SQLALCHEMY_DATABASE_URI = None  # задаётся в get_config
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"check_same_thread": False}}


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}


def get_config(config_name: str | None = None) -> type[Config]:
    """Возвращает класс конфигурации по имени окружения."""
    name = config_name or os.getenv("FLASK_ENV", "development")
    config_cls = config_by_name.get(name, DevelopmentConfig)

    if config_cls is TestingConfig:
        uri = TestingConfig._test_uri()
        config_cls.SQLALCHEMY_DATABASE_URI = uri
        if uri.startswith("sqlite"):
            config_cls.SQLALCHEMY_ENGINE_OPTIONS = {
                "connect_args": {"check_same_thread": False}
            }
        else:
            config_cls.SQLALCHEMY_ENGINE_OPTIONS = {
                "pool_pre_ping": True,
                "pool_recycle": 300,
            }
    return config_cls

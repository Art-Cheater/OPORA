"""Application factory — точка входа в приложение «Опора»."""

from pathlib import Path

from flask import Flask

from app.config import get_config
from app.extensions import csrf, db, login_manager, migrate
from app.modules.auth.repositories import UserRepository
from app.modules.registry import register_blueprints


def create_app(config_name: str | None = None) -> Flask:
    """Создаёт и настраивает экземпляр Flask-приложения."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.config.from_object(get_config(config_name))
    _configure_email_validator()

    _init_extensions(app)
    register_blueprints(app)
    _register_audit_hooks(app)
    _register_security_hooks(app)
    _register_error_handlers(app)
    _register_context_processors(app)
    _register_cli_commands(app)
    _ensure_upload_folder(app)

    return app


def _configure_email_validator() -> None:
    """Разрешает корпоративные зоны (.local) для внутренних email."""
    try:
        import email_validator

        special = list(email_validator.SPECIAL_USE_DOMAIN_NAMES)
        if "local" in special:
            special.remove("local")
            email_validator.SPECIAL_USE_DOMAIN_NAMES = special
    except Exception:
        pass


def _ensure_upload_folder(app: Flask) -> None:
    upload_folder = app.config.get("UPLOAD_FOLDER")
    if upload_folder:
        Path(upload_folder).mkdir(parents=True, exist_ok=True)


def _register_audit_hooks(app: Flask) -> None:
    from app.core.audit_hooks import register_audit_hooks

    register_audit_hooks(app)


def _init_extensions(app: Flask) -> None:
    """Инициализация Flask-расширений."""
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    _configure_sqlite(app)
    _ensure_postgres_schema(app)

    from app.models import (  # noqa: F401
        Attachment,
        AuditLog,
        Comment,
        Contract,
        CustomField,
        CustomFieldValue,
        FieldDefinition,
        FieldOption,
        LoginLog,
        Message,
        MessengerConversation,
        MessengerMessage,
        Notification,
        Permission,
        Position,
        Project,
        ProjectMember,
        Request,
        RequestHistory,
        RequestStatus,
        Role,
        RoleFieldPermission,
        RolePermission,
        SystemModule,
        User,
        UserPresence,
        UserRole,
    )

    @login_manager.user_loader
    def load_user(user_id: str):
        return UserRepository.get_by_id(user_id)


def _configure_sqlite(app: Flask) -> None:
    """Включает FK и прочие pragma для SQLite."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if not uri.startswith("sqlite"):
        return

    # Регистрируем один раз на уровне Engine (не дублируем при повторном create_app)
    if getattr(_configure_sqlite, "_registered", False):
        return

    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        module = getattr(dbapi_connection, "__class__", type(None)).__module__
        if not str(module).startswith("sqlite3"):
            return
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _configure_sqlite._registered = True  # type: ignore[attr-defined]


def _ensure_postgres_schema(app: Flask) -> None:
    """Создаёт рабочую схему PostgreSQL, если задана POSTGRES_SCHEMA ≠ public."""
    from sqlalchemy import text

    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if not uri.startswith("postgresql"):
        return

    schema = str(app.config.get("POSTGRES_SCHEMA") or "public").strip()
    if not schema or schema == "public":
        return
    if not schema.replace("_", "").isalnum():
        raise RuntimeError(f"Недопустимое имя схемы PostgreSQL: {schema!r}")

    with app.app_context():
        with db.engine.begin() as conn:
            conn.execute(
                text(f'CREATE SCHEMA IF NOT EXISTS "{schema}" AUTHORIZATION CURRENT_USER')
            )


def _register_security_hooks(app: Flask) -> None:
    """Хуки безопасности: проверка блокировки, обработка неавторизованных."""

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import flash, redirect, request, url_for

        flash("Для доступа необходимо войти в систему.", "warning")
        next_url = request.full_path if request.full_path != "/?" else request.path
        if next_url.endswith("?"):
            next_url = next_url[:-1]
        return redirect(url_for("auth.login", next=next_url))

    @app.before_request
    def enforce_user_access():
        from flask import flash, redirect, url_for
        from flask_login import current_user, logout_user

        if not current_user.is_authenticated:
            return

        if current_user.is_blocked or not current_user.is_active:
            logout_user()
            flash("Ваша учётная запись заблокирована или деактивирована.", "danger")
            return redirect(url_for("auth.login"))


def _register_error_handlers(app: Flask) -> None:
    """Регистрация обработчиков ошибок."""

    @app.errorhandler(404)
    def not_found(error):
        from flask import render_template

        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def request_entity_too_large(error):
        from flask import flash, redirect, request, url_for

        limit_mb = int(app.config.get("MAX_CONTENT_LENGTH", 0) / (1024 * 1024)) or 64
        flash(
            f"Файлы слишком большие. Лимит загрузки — {limit_mb} МБ за один запрос "
            f"(можно несколько файлов, но суммарно не больше лимита).",
            "danger",
        )
        ref = request.referrer
        if ref:
            return redirect(ref)
        return redirect(url_for("main.index"))

    @app.errorhandler(500)
    def internal_error(error):
        from flask import render_template

        db.session.rollback()
        return render_template("errors/500.html"), 500

    @app.errorhandler(400)
    def bad_request(error):
        from flask import render_template
        from flask_wtf.csrf import CSRFError

        if isinstance(error, CSRFError):
            return _csrf_response()

        return render_template("errors/404.html"), 400

    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return _csrf_response()

    def _csrf_response():
        from flask import flash, redirect, render_template, request

        flash(
            "Сессия формы устарела. Обновите страницу и повторите действие — повторный вход не требуется.",
            "warning",
        )
        ref = request.referrer
        if ref and request.url_root in ref and "/auth/login" not in ref:
            return redirect(ref)
        return render_template("errors/csrf.html", back_url=ref), 400


def _register_context_processors(app: Flask) -> None:
    """Глобальные переменные для шаблонов."""

    @app.context_processor
    def inject_globals():
        max_upload_mb = int(app.config.get("MAX_CONTENT_LENGTH", 0) / (1024 * 1024)) or 64
        return {
            "app_name": app.config["APP_NAME"],
            "app_version": app.config["APP_VERSION"],
            "max_upload_mb": max_upload_mb,
            "max_upload_files": int(app.config.get("MAX_UPLOAD_FILES", 20)),
            "messenger_poll_interval_ms": int(app.config.get("MESSENGER_POLL_INTERVAL_MS", 8000)),
            "messenger_unread_interval_ms": int(app.config.get("MESSENGER_UNREAD_INTERVAL_MS", 45000)),
        }


def _register_cli_commands(app: Flask) -> None:
    """Регистрация CLI-команд."""

    @app.cli.command("seed-admin")
    def seed_admin():
        """Создаёт администратора по умолчанию и назначает роль admin."""
        from app.modules.auth.services import AuthService

        AuthService.create_default_admin()
        print("Администратор создан или обновлён (роль admin назначена).")

    @app.cli.command("repair-user-access")
    def repair_user_access():
        """Назначает роль admin пользователям без ролей."""
        from app.modules.auth.services import AuthService

        fixed = AuthService.repair_users_without_roles()
        print(f"Восстановлен доступ для пользователей: {fixed}")

    @app.cli.command("seed-reference-data")
    def seed_reference_data():
        """Заполняет справочники (статусы, роли, разрешения)."""
        from app.seed.reference_data import ReferenceDataService

        ReferenceDataService.seed_all()
        print("Справочные данные заполнены.")

    @app.cli.command("sync-security")
    def sync_security():
        """Синхронизирует роли и разрешения безопасности."""
        from app.seed.reference_data import ReferenceDataService

        ReferenceDataService.sync_security_roles()
        print("Роли и разрешения синхронизированы.")

    @app.cli.command("init-db")
    def init_db():
        """Создаёт схему (SQLite: create_all) и заполняет справочники + админа."""
        from sqlalchemy import inspect

        from app.modules.auth.services import AuthService
        from app.seed.reference_data import ReferenceDataService

        uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
        if uri.startswith("sqlite"):
            db.create_all()
            print("SQLite: таблицы созданы через create_all().")
        else:
            inspector = inspect(db.engine)
            if "users" not in inspector.get_table_names():
                print("Таблицы не найдены. Сначала выполните: python -m flask db upgrade")
                return

        ReferenceDataService.seed_all()
        ReferenceDataService.sync_security_roles()
        AuthService.create_default_admin()
        # Не логируем полный URL с паролем
        safe = uri.split("@")[-1] if "@" in uri else uri
        print(f"База готова: {safe}")
        print("Администратор: см. ADMIN_EMAIL / ADMIN_PASSWORD в .env")

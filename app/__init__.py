"""Application factory — точка входа в приложение «Опора»."""

from pathlib import Path

from flask import Flask

from app.config import get_config
from app.extensions import csrf, db, login_manager, migrate
from app.modules.auth.repositories import UserRepository
from app.modules.registry import register_blueprints


def _is_static_request(request) -> bool:
    """True для CSS/JS/шрифтов: без сессии, аудита и запросов в БД."""
    return request.endpoint == "static" or (request.path or "").startswith("/static/")


def create_app(config_name: str | None = None) -> Flask:
    """Создаёт и настраивает экземпляр Flask-приложения."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.config.from_object(get_config(config_name))
    _reject_insecure_production_secrets(app)
    _configure_email_validator()

    _init_extensions(app)
    _register_performance_profiler(app)
    _configure_static_assets(app)
    register_blueprints(app)
    _register_audit_hooks(app)
    _register_security_hooks(app)
    _register_spa_nav(app)
    _register_error_handlers(app)
    _register_context_processors(app)
    _register_template_filters(app)
    _register_cli_commands(app)
    _ensure_upload_folder(app)

    return app


_INSECURE_SECRET_KEYS = {
    "dev-secret-key-change-in-production",
    "change-me-to-a-random-secret-key",
}
_INSECURE_ADMIN_PASSWORDS = {
    "admin123",
    "change-me-strong-password",
}


def _reject_insecure_production_secrets(app: Flask) -> None:
    if app.testing or app.debug:
        return
    if (app.config.get("SECRET_KEY") or "") in _INSECURE_SECRET_KEYS:
        raise RuntimeError(
            "В production нельзя оставлять SECRET_KEY по умолчанию. Задайте свой ключ в .env."
        )
    admin_pw = (app.config.get("ADMIN_PASSWORD") or "").strip()
    if admin_pw in _INSECURE_ADMIN_PASSWORDS:
        raise RuntimeError(
            "В production задайте свой ADMIN_PASSWORD в .env (не значение из .env.example)."
        )


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


def _configure_static_assets(app: Flask) -> None:
    """Кэш статики с cache-bust (?v=RELEASE), иначе nginx immutable залипает на старом JS."""
    from app.release import RELEASE

    app.config.setdefault("SEND_FILE_MAX_AGE_DEFAULT", 60 * 60 * 24 * 30)
    # Не APP_VERSION из .env — он почти не меняется и после деплоя браузер держит битый JS.
    version = str(RELEASE)

    @app.url_defaults
    def _static_cache_bust(endpoint, values):
        if endpoint != "static" or "filename" not in values or "v" in values:
            return
        values["v"] = version

    @app.template_global()
    def static_url(filename: str) -> str:
        from flask import url_for

        return url_for("static", filename=filename, v=version)

    @app.after_request
    def _cache_static_assets(response):
        from flask import request

        if request.endpoint == "static" and response.status_code in (200, 304):
            response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
        return response


def _register_audit_hooks(app: Flask) -> None:
    from app.core.audit_hooks import register_audit_hooks

    register_audit_hooks(app)


def _register_performance_profiler(app: Flask) -> None:
    from app.core.performance import register_performance_profiler

    register_performance_profiler(app)


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
        PersonalContract,
        Permission,
        Position,
        Project,
        ProjectMember,
        Defect,
        DefectCategory,
        DefectHistory,
        DefectStatus,
        Request,
        RequestDispatcher,
        RequestHistory,
        RequestJournal,
        RequestJournalCounter,
        RequestStatus,
        Waybill,
        WaybillHistory,
        WaybillMember,
        WaybillStop,
        Role,
        RoleFieldPermission,
        RolePermission,
        SystemModule,
        TenderApplication,
        TenderDocument,
        TenderProject,
        User,
        UserPresence,
        UserRole,
        Wallpaper,
        WorkObject,
    )

    @login_manager.user_loader
    def load_user(user_id: str):
        from flask import has_request_context, request

        # CSS/JS не должны грузить RBAC: иначе 304 статики ждут SQLite и висят по 5–6 с.
        if has_request_context() and _is_static_request(request):
            return None
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
        # WAL: читатели не ждут писателей. Без этого threaded Flask + запись
        # (создание, heartbeat) стопорят соседние запросы на ~5 с (busy timeout).
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=MEMORY")
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
        from flask import flash, redirect, request, url_for
        from flask_login import current_user, logout_user

        # CSS/JS не должны ходить в БД за current_user — иначе статика встаёт в очередь за HTML.
        if _is_static_request(request) or request.path == "/health":
            return

        if not current_user.is_authenticated:
            return

        if current_user.is_blocked or not current_user.is_active:
            logout_user()
            flash("Ваша учётная запись заблокирована или деактивирована.", "danger")
            return redirect(url_for("auth.login"))

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # Базовый CSP: приложение — server-rendered + inline scripts в шаблонах.
        response.headers.setdefault(
            "Content-Security-Policy",
            "frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
        )
        return response


def _register_spa_nav(app: Flask) -> None:
    """Клиентский кабинет: по заголовку отдаём только середину страницы, без сайдбара."""

    @app.before_request
    def detect_spa_nav():
        from flask import g, request
        from flask_login import current_user

        g.spa_nav = False
        if request.method != "GET":
            return
        if request.headers.get("X-Opora-Nav") != "1":
            return
        if _is_static_request(request) or request.path == "/health":
            return
        path = request.path or ""
        if (path.startswith("/messenger") or path.startswith("/auth") or path.startswith("/work-orders")):
            return
        if "/download" in path or path.rstrip("/").endswith("/export"):
            return
        if not getattr(current_user, "is_authenticated", False):
            return
        g.spa_nav = True

    @app.after_request
    def spa_nav_headers(response):
        from flask import g

        if getattr(g, "spa_nav", False):
            response.headers["X-Opora-Partial"] = "1"
            response.headers["Vary"] = "X-Opora-Nav, Cookie"
            response.headers["Cache-Control"] = "private, max-age=30, stale-while-revalidate=90"
        return response


def _register_error_handlers(app: Flask) -> None:
    """Регистрация обработчиков ошибок."""

    @app.errorhandler(404)
    def not_found(error):
        from flask import render_template
        from app.core.http import ajax_error, is_ajax

        if is_ajax():
            return ajax_error("Запрошенные данные не найдены.", status=404)

        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def request_entity_too_large(error):
        from flask import flash, redirect, request, url_for
        from app.core.http import ajax_error, is_ajax

        limit_mb = int(app.config.get("MAX_CONTENT_LENGTH", 0) / (1024 * 1024)) or 64
        message = (
            f"Файлы слишком большие. Лимит загрузки — {limit_mb} МБ за один запрос "
            "(можно несколько файлов, но суммарно не больше лимита)."
        )
        if is_ajax():
            return ajax_error(message, status=413)
        flash(message, "danger")
        ref = request.referrer
        if ref:
            return redirect(ref)
        return redirect(url_for("main.index"))

    @app.errorhandler(500)
    def internal_error(error):
        from flask import render_template
        from app.core.http import ajax_error, is_ajax

        app.logger.exception("Unhandled server error: %s", error)
        db.session.rollback()
        if is_ajax():
            return ajax_error(
                "Внутренняя ошибка сервера. Повторите попытку позже.",
                status=500,
            )
        return render_template("errors/500.html"), 500

    @app.errorhandler(400)
    def bad_request(error):
        from flask import render_template
        from flask_wtf.csrf import CSRFError
        from app.core.http import ajax_error, is_ajax

        if isinstance(error, CSRFError):
            return _csrf_response()
        if is_ajax():
            return ajax_error("Некорректный запрос.", status=400)

        return render_template("errors/404.html"), 400

    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return _csrf_response()

    def _csrf_response():
        from flask import flash, redirect, render_template, request
        from app.core.http import ajax_error, is_ajax

        message = (
            "Сессия формы устарела. Обновите страницу и повторите действие — "
            "повторный вход не требуется."
        )
        if is_ajax():
            return ajax_error(message, status=400)
        flash(message, "warning")
        ref = request.referrer
        if ref and request.url_root in ref and "/auth/login" not in ref:
            return redirect(ref)
        return render_template("errors/csrf.html", back_url=ref), 400


def _register_context_processors(app: Flask) -> None:
    """Глобальные переменные для шаблонов."""

    @app.context_processor
    def inject_globals():
        from flask_login import current_user

        from app.core.builtin_field_service import BuiltinFieldService
        from app.core.ui_backgrounds import build_background_options, resolve_user_background_url

        max_upload_mb = int(app.config.get("MAX_CONTENT_LENGTH", 0) / (1024 * 1024)) or 64
        ui_bg_url = None
        ui_theme = None
        ui_background = "none"
        bg_options = []
        if getattr(current_user, "is_authenticated", False):
            ui_bg_url = resolve_user_background_url(current_user)
            ui_theme = current_user.ui_theme
            ui_background = current_user.ui_background or "none"
            bg_options = build_background_options(current_user)
        return {
            "app_name": app.config["APP_NAME"],
            "app_version": app.config["APP_VERSION"],
            "max_upload_mb": max_upload_mb,
            "max_upload_files": int(app.config.get("MAX_UPLOAD_FILES", 20)),
            "messenger_poll_interval_ms": int(app.config.get("MESSENGER_POLL_INTERVAL_MS", 8000)),
            "messenger_unread_interval_ms": int(app.config.get("MESSENGER_UNREAD_INTERVAL_MS", 45000)),
            "is_builtin_visible": BuiltinFieldService.is_visible,
            "builtin_label": BuiltinFieldService.label,
            "ui_background_url": ui_bg_url,
            "ui_theme_pref": ui_theme,
            "ui_background_id": ui_background,
            "ui_background_options": bg_options,
        }


def _register_template_filters(app: Flask) -> None:
    @app.template_filter("local_dt")
    def local_dt(value, fmt="%d.%m.%Y %H:%M"):
        from app.models.base import format_local_dt

        tz_name = app.config.get("EIS_SYNC_TIMEZONE") or "Europe/Moscow"
        return format_local_dt(value, fmt=fmt, tz_name=tz_name)


def _register_cli_commands(app: Flask) -> None:
    """Регистрация CLI-команд."""
    import click

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

    @app.cli.command("seed-wallpapers")
    def seed_wallpapers():
        """Добавляет реальные фото Кирова в каталог обоев."""
        from app.modules.wallpapers.seed import WallpaperSeedService

        n = WallpaperSeedService.ensure_kirov_wallpapers()
        print(f"Обои Кирова: создано новых {n}, каталог обновлён.")

    @app.cli.command("sync-security")
    def sync_security():
        """Синхронизирует каталог модулей и разрешений (без сброса ролей)."""
        from app.seed.reference_data import ReferenceDataService

        ReferenceDataService.sync_security_roles()
        print("Каталог модулей и прав обновлён (назначения ролей не сброшены).")

    @app.cli.command("import-lighting-plan")
    @click.option(
        "--path",
        "file_path",
        required=True,
        help="Путь к Excel «План работ освещение …»",
    )
    @click.option("--user-email", default=None, help="Email пользователя для аудита (по умолчанию admin)")
    def import_lighting_plan(file_path: str, user_email: str | None):
        """Импорт объектов из Excel-плана освещения."""
        from pathlib import Path

        from app.models.auth.user import User
        from app.modules.objects.services import ObjectService

        path = Path(file_path)
        user = None
        if user_email:
            user = db.session.scalar(
                db.select(User).where(User.email == user_email.lower().strip(), User.active_filter())
            )
        if user is None:
            user = db.session.scalar(
                db.select(User).where(User.active_filter()).order_by(User.created_at.asc()).limit(1)
            )
        if user is None:
            click.echo("Нет пользователей в БД — сначала seed-admin.")
            return
        result = ObjectService.import_from_lighting_plan(path, user.id)
        click.echo(
            f"Готово: создано {result.created}, обновлено {result.updated}, "
            f"пропущено {result.skipped}, строк в файле {result.total}."
        )

    @app.cli.command("wipe-work-objects")
    def wipe_work_objects():
        """Мягко удалить все объекты (перед повторным импортом)."""
        from app.models.auth.user import User
        from app.modules.objects.services import ObjectService

        user = db.session.scalar(
            db.select(User).where(User.active_filter()).order_by(User.created_at.asc()).limit(1)
        )
        if user is None:
            click.echo("Нет пользователей в БД.")
            return
        count = ObjectService.wipe_all(user.id)
        click.echo(f"Удалено объектов: {count}")

    @app.cli.command("wipe-requests")
    def wipe_requests():
        """Полностью удалить все заявки из БД."""
        from app.models.auth.user import User
        from app.modules.requests.services import RequestService

        user = db.session.scalar(
            db.select(User).where(User.active_filter()).order_by(User.created_at.asc()).limit(1)
        )
        if user is None:
            click.echo("Нет пользователей в БД.")
            return
        count = RequestService.wipe_all(user.id)
        click.echo(f"Удалено заявок: {count}")

    @app.cli.command("eis-sync")
    @click.option("--loop", "as_loop", is_flag=True, help="Ждать 12:00 и 18:00 и запускать снова")
    @click.option("--user-email", default=None, help="Пользователь для аудита")
    def eis_sync(as_loop: bool, user_email: str | None):
        """Импорт закупок и контрактов ЕИС в Опору."""
        from app.modules.eis.scheduler import run_loop, run_once

        if as_loop:
            run_loop()
            return
        try:
            run_once(trigger="manual", user_email=user_email)
        except Exception as exc:
            click.echo(f"Ошибка импорта ЕИС: {exc}")
            raise
        click.echo("Импорт ЕИС завершён.")

    @app.cli.command("inquiry-sync")
    @click.option("--loop", "as_loop", is_flag=True, help="Забирать письма по кругу")
    def inquiry_sync(as_loop: bool):
        """Забор писем с корпоративного ящика в раздел «Обращения»."""
        from app.modules.inquiries.scheduler import run_loop, run_once

        if as_loop:
            run_loop()
            return
        run_once()
        click.echo("Забор писем завершён.")

    @app.cli.command("inquiry-purge")
    def inquiry_purge():
        """Удалить обращения старше INQUIRY_YEAR_FROM (по умолчанию 2026)."""
        from app.modules.inquiries.services import InquiryService

        removed = InquiryService.purge_older_than_year()
        year = InquiryService.mailbox_config()["year_from"]
        click.echo(f"Удалены письма старше {year}: {removed}.")

    @app.cli.command("inquiry-test")
    def inquiry_test():
        """Проверить вход в mail.ru по IMAP, письма не забирать."""
        from app.modules.inquiries.services import InquiryService

        ok, message = InquiryService.test_connection()
        click.echo(message)
        if not ok:
            raise SystemExit(1)

    @app.cli.command("dedupe-agreements")
    def dedupe_agreements():
        """Скрыть повторные договора с одним номером, оставить экземпляр с большей адресной программой."""
        from app.modules.agreements.services import AgreementService

        hidden = AgreementService.collapse_duplicates()
        click.echo(f"Убраны повторы: {hidden}.")

    @app.cli.command("documents-notify")
    @click.option("--loop", "as_loop", is_flag=True, help="Проверять сроки по кругу")
    def documents_notify(as_loop: bool):
        """Напоминания о сроках личных договоров (за месяц и за 2 недели)."""
        from app.modules.documents.scheduler import run_loop, run_once

        if as_loop:
            run_loop()
            return
        result = run_once()
        click.echo(
            f"Напоминания: месяц={result.get('month', 0)}, две недели={result.get('two_weeks', 0)}"
        )

    @app.cli.command("repair-request-districts")
    @click.option("--dry-run", is_flag=True, help="Только показать, без записи в БД")
    @click.option("--limit", default=0, show_default=True, help="Максимум заявок (0 = все)")
    def repair_request_districts(dry_run: bool, limit: int):
        """Пересчитать район по адресу (с домом — через геокодер)."""
        import time

        from app.core.address import get_address_suggestion_service
        from app.models.requests.request import Request
        from app.modules.requests.address_format import split_address_query
        from app.modules.requests.districts import normalize_request_district

        service = get_address_suggestion_service()
        stmt = (
            db.select(Request)
            .where(Request.active_filter())
            .order_by(Request.created_at.desc())
        )
        if limit and limit > 0:
            stmt = stmt.limit(limit)
        rows = list(db.session.scalars(stmt))
        changed = 0
        skipped = 0
        for index, req in enumerate(rows, 1):
            address = (req.address or req.normalized_address or "").strip()
            if not address:
                skipped += 1
                continue
            _kind, _name, house = split_address_query(address)
            try:
                hits = service.suggest(address, limit=5)
            except Exception as exc:
                click.echo(f"#{req.number}: ошибка геокодера: {exc}")
                skipped += 1
                continue
            if house:
                # Не чаще 1 запроса в секунду к Nominatim
                time.sleep(1.05)
            if not hits:
                skipped += 1
                continue
            new_district = normalize_request_district(hits[0].district)
            old_district = normalize_request_district(req.district)
            if not new_district or new_district == old_district:
                skipped += 1
                continue
            click.echo(
                f"{req.number}: {old_district or '—'} → {new_district} ({address[:80]})"
            )
            if not dry_run:
                req.district = new_district
                changed += 1
            else:
                changed += 1
            if index % 20 == 0 and not dry_run:
                db.session.commit()
        if not dry_run:
            db.session.commit()
        click.echo(f"Готово: обновлено {changed}, без изменений/пропуск {skipped}, всего {len(rows)}.")

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

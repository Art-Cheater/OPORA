"""Сервис начального заполнения справочных данных."""

from app.extensions import db
from app.models.auth.associations import RolePermission
from app.models.auth.constants import (
    ALL_ROLE_CODES,
    PERM_AUDIT_VIEW,
    PERM_AUDIT_EXPORT,
    PERM_AUTH_LOGIN_LOGS_VIEW,
    PERM_CONTRACTS_CREATE,
    PERM_CONTRACTS_DELETE,
    PERM_CONTRACTS_EDIT,
    PERM_CONTRACTS_VIEW,
    PERM_DEFECTS_CREATE,
    PERM_DEFECTS_DELETE,
    PERM_DEFECTS_EDIT,
    PERM_DEFECTS_FILE_DELETE,
    PERM_DEFECTS_FILE_UPLOAD,
    PERM_DEFECTS_STATUS_CHANGE,
    PERM_DEFECTS_VIEW,
    PERM_MESSENGER_USE,
    PERM_DOCUMENTS_USE,
    PERM_OBJECTS_CREATE,
    PERM_OBJECTS_EDIT,
    PERM_OBJECTS_VIEW,
    PERM_SEARCH_USE,
    PERM_PROFILE_EDIT,
    PERM_PROFILE_VIEW,
    PERM_PROJECTS_CREATE,
    PERM_PROJECTS_DELETE,
    PERM_PROJECTS_EDIT,
    PERM_PROJECTS_VIEW,
    PERM_REQUESTS_APPROVE,
    PERM_REQUESTS_CREATE,
    PERM_REQUESTS_DELETE,
    PERM_REQUESTS_DISPATCH,
    PERM_REQUESTS_EDIT,
    PERM_REQUESTS_VIEW,
    PERM_ROLES_MANAGE,
    PERM_ROLES_VIEW,
    PERM_TENDERS_CREATE,
    PERM_TENDERS_EDIT,
    PERM_TENDERS_VIEW,
    PERM_USERS_BLOCK,
    PERM_USERS_CREATE,
    PERM_USERS_DELETE,
    PERM_USERS_EDIT,
    PERM_USERS_VIEW,
    PERM_WAYBILLS_CREATE,
    PERM_WAYBILLS_DELETE,
    PERM_WAYBILLS_EDIT,
    PERM_WAYBILLS_STATUS_CHANGE,
    PERM_WAYBILLS_VIEW,
    ROLE_ADMIN,
    ROLE_DIRECTOR,
    ROLE_DISPATCHER,
    ROLE_EXECUTOR,
    ROLE_LABELS,
    ROLE_MASTER,
)
from app.models.auth.field_definition import FieldDefinition
from app.models.auth.permission import Permission
from app.models.auth.position import Position
from app.models.auth.role import Role
from app.models.auth.system_module import SystemModule
from app.models.defects.defect_category import DefectCategory
from app.models.defects.defect_status import DefectStatus
from app.models.requests.request_status import RequestStatus
from app.models.requests.request_dispatcher import RequestDispatcher
from app.models.requests.request_journal import RequestJournal
from app.modules.defects.workflow import DEFECT_CATEGORIES, DEFECT_STATUSES
from app.modules.requests.journals import REQUEST_JOURNALS
from app.seed.security_catalog import (
    MODULE_FIELDS,
    POSITIONS,
    REQUEST_DISPATCHERS,
    SYSTEM_MODULES,
    build_permission_catalog,
)


class ReferenceDataService:
    """Заполнение справочников (идемпотентно)."""

    REQUEST_STATUSES = [
        ("new", "Новая", "Заявка создана диспетчером", "#DC3545", 10, False),
        (
            "emergency_dispatched",
            "Выехала аварийная бригада",
            "Аварийная бригада выехала на место",
            "#E6A700",
            20,
            False,
        ),
        (
            "accepted_by_master",
            "Передана мастеру",
            "Заявка передана районному мастеру",
            "#E6A700",
            30,
            False,
        ),
        (
            "in_progress",
            "В работе",
            "Мастер выполняет работы",
            "#E6A700",
            40,
            False,
        ),
        (
            "completed",
            "Выполнено",
            "Работы завершены",
            "#2E7D32",
            50,
            True,
        ),
        (
            "cancelled",
            "Отменена",
            "Заявка отменена",
            "#78909C",
            60,
            True,
        ),
    ]

    ROLES = [
        (ROLE_ADMIN, ROLE_LABELS[ROLE_ADMIN], "Полный доступ к системе", True),
        (ROLE_DIRECTOR, ROLE_LABELS[ROLE_DIRECTOR], "Руководство и контроль", True),
        (ROLE_DISPATCHER, ROLE_LABELS[ROLE_DISPATCHER], "Диспетчеризация заявок", True),
        (ROLE_MASTER, ROLE_LABELS[ROLE_MASTER], "Руководство бригадой", True),
        (ROLE_EXECUTOR, ROLE_LABELS[ROLE_EXECUTOR], "Исполнение заявок", True),
    ]

    ALL_PERMISSION_CODES = [p[0] for p in build_permission_catalog()]

    ROLE_PERMISSIONS = {
        ROLE_ADMIN: ALL_PERMISSION_CODES,
        ROLE_DIRECTOR: [
            PERM_USERS_VIEW, PERM_USERS_BLOCK,
            PERM_ROLES_VIEW,
            PERM_PROFILE_VIEW, PERM_PROFILE_EDIT,
            PERM_AUTH_LOGIN_LOGS_VIEW,
            PERM_REQUESTS_VIEW, PERM_REQUESTS_CREATE, PERM_REQUESTS_EDIT,
            PERM_REQUESTS_DELETE, PERM_REQUESTS_APPROVE, PERM_REQUESTS_DISPATCH,
            PERM_DEFECTS_VIEW, PERM_DEFECTS_CREATE, PERM_DEFECTS_EDIT, PERM_DEFECTS_DELETE,
            PERM_DEFECTS_STATUS_CHANGE, "defects.export", "defects.print",
            PERM_WAYBILLS_VIEW, PERM_WAYBILLS_CREATE, PERM_WAYBILLS_EDIT, PERM_WAYBILLS_DELETE,
            PERM_WAYBILLS_STATUS_CHANGE, "waybills.export", "waybills.print",
            PERM_OBJECTS_VIEW, PERM_OBJECTS_CREATE, PERM_OBJECTS_EDIT,
            PERM_PROJECTS_VIEW, PERM_PROJECTS_CREATE, PERM_PROJECTS_EDIT,
            PERM_TENDERS_VIEW, PERM_TENDERS_CREATE, PERM_TENDERS_EDIT,
            PERM_CONTRACTS_VIEW, PERM_CONTRACTS_CREATE, PERM_CONTRACTS_EDIT,
            PERM_AUDIT_VIEW, PERM_AUDIT_EXPORT,
            PERM_MESSENGER_USE, PERM_DOCUMENTS_USE, PERM_SEARCH_USE,
            "materials.view", "reports.view",
            "contractors.view", "eis.view", "agreements.view", "agreements.create", "agreements.delete",
            "inquiries.view", "inquiries.edit", "inquiries.delete", "inquiries.sync",
        ],
        ROLE_DISPATCHER: [
            PERM_PROFILE_VIEW, PERM_PROFILE_EDIT, PERM_USERS_VIEW,
            PERM_REQUESTS_VIEW, PERM_REQUESTS_CREATE, PERM_REQUESTS_EDIT,
            PERM_REQUESTS_DISPATCH, PERM_OBJECTS_VIEW, PERM_PROJECTS_VIEW,
            PERM_DEFECTS_VIEW, PERM_DEFECTS_CREATE, PERM_DEFECTS_EDIT,
            PERM_DEFECTS_FILE_UPLOAD, PERM_DEFECTS_FILE_DELETE,
            PERM_WAYBILLS_VIEW,
            PERM_TENDERS_VIEW,
            PERM_MESSENGER_USE, PERM_DOCUMENTS_USE, PERM_SEARCH_USE,
            "contractors.view",
            "agreements.view", "agreements.create",
            "inquiries.view", "inquiries.edit", "inquiries.sync",
        ],
        ROLE_MASTER: [
            PERM_PROFILE_VIEW, PERM_PROFILE_EDIT,
            PERM_REQUESTS_VIEW, PERM_REQUESTS_CREATE, PERM_REQUESTS_EDIT,
            PERM_REQUESTS_APPROVE, PERM_OBJECTS_VIEW, PERM_PROJECTS_VIEW,
            PERM_DEFECTS_VIEW, PERM_DEFECTS_CREATE, PERM_DEFECTS_EDIT,
            PERM_DEFECTS_STATUS_CHANGE, PERM_DEFECTS_FILE_UPLOAD,
            PERM_WAYBILLS_VIEW, PERM_WAYBILLS_CREATE, PERM_WAYBILLS_EDIT,
            PERM_WAYBILLS_STATUS_CHANGE, "waybills.file_upload", "waybills.print", "waybills.export",
            PERM_TENDERS_VIEW,
            PERM_MESSENGER_USE, PERM_DOCUMENTS_USE, PERM_SEARCH_USE,
            "contractors.view",
            "agreements.view",
            "inquiries.view",
        ],
        ROLE_EXECUTOR: [
            PERM_PROFILE_VIEW, PERM_PROFILE_EDIT,
            PERM_REQUESTS_VIEW, PERM_REQUESTS_CREATE, PERM_REQUESTS_EDIT,
            PERM_REQUESTS_DISPATCH,
            PERM_DEFECTS_VIEW, PERM_WAYBILLS_VIEW,
            PERM_OBJECTS_VIEW, PERM_PROJECTS_VIEW, PERM_MESSENGER_USE, PERM_DOCUMENTS_USE, PERM_SEARCH_USE,
            "inquiries.view",
        ],
    }

    @classmethod
    def seed_all(cls) -> None:
        cls._seed_request_statuses()
        cls._seed_request_journals()
        cls._seed_request_dispatchers()
        cls._seed_defect_statuses()
        cls._seed_defect_categories()
        cls._seed_security_catalog()
        cls._seed_roles_and_permissions()
        db.session.commit()
        cls._clear_permission_cache()
        try:
            from app.modules.wallpapers.seed import WallpaperSeedService

            WallpaperSeedService.ensure_kirov_wallpapers()
        except Exception:
            # seed обоев не должен ломать весь reference seed
            from flask import current_app

            current_app.logger.exception("Не удалось засеять обои Кирова")

    @classmethod
    def sync_security_roles(cls) -> None:
        """Добавляет недостающие модули и права. Назначения ролей не сбрасывает."""
        cls._seed_security_catalog()
        cls._ensure_admin_full_access()
        cls._grant_missing_role_permissions()
        cls._grant_personal_documents_to_all_roles()
        db.session.commit()
        cls._clear_permission_cache()

    @classmethod
    def ensure_security_catalog(cls) -> None:
        """Досеивает каталог, если не хватает модулей/прав или устарели названия."""
        existing_names = {
            row[0]: row[1]
            for row in db.session.execute(
                db.select(SystemModule.code, SystemModule.name).where(SystemModule.active_filter())
            )
        }
        expected_names = {code: name for code, name, _icon, _sort, _desc in SYSTEM_MODULES}
        missing_modules = any(code not in existing_names for code in expected_names)
        renamed = any(existing_names.get(code) != name for code, name in expected_names.items())
        perm_count = db.session.scalar(
            db.select(db.func.count()).select_from(Permission).where(Permission.active_filter())
        ) or 0
        if not missing_modules and not renamed and perm_count >= len(build_permission_catalog()):
            return
        cls.sync_security_roles()

    @classmethod
    def _ensure_admin_full_access(cls) -> None:
        admin = db.session.scalar(db.select(Role).where(Role.code == ROLE_ADMIN, Role.active_filter()))
        if admin is None:
            return
        permissions = list(
            db.session.scalars(db.select(Permission).where(Permission.active_filter()))
        )
        have = {
            rp.permission_id
            for rp in db.session.scalars(
                db.select(RolePermission).where(
                    RolePermission.role_id == admin.id,
                    RolePermission.active_filter(),
                )
            )
        }
        for perm in permissions:
            if perm.id in have:
                continue
            db.session.add(RolePermission(role_id=admin.id, permission_id=perm.id))

    @classmethod
    def _grant_missing_role_permissions(cls) -> None:
        """Добавляет права из ROLE_PERMISSIONS, ничего не снимает."""
        roles = {
            role.code: role
            for role in db.session.scalars(db.select(Role).where(Role.active_filter()))
        }
        permissions = {
            perm.code: perm
            for perm in db.session.scalars(db.select(Permission).where(Permission.active_filter()))
        }
        have = {
            (rp.role_id, rp.permission_id)
            for rp in db.session.scalars(
                db.select(RolePermission).where(RolePermission.active_filter())
            )
        }
        for role_code, perm_codes in cls.ROLE_PERMISSIONS.items():
            role = roles.get(role_code)
            if role is None:
                continue
            for perm_code in perm_codes:
                perm = permissions.get(perm_code)
                if perm is None or (role.id, perm.id) in have:
                    continue
                db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))
                have.add((role.id, perm.id))

    @classmethod
    def _grant_personal_documents_to_all_roles(cls) -> None:
        perm = db.session.scalar(
            db.select(Permission).where(Permission.code == PERM_DOCUMENTS_USE, Permission.active_filter())
        )
        if perm is None:
            return
        have = {
            rp.role_id
            for rp in db.session.scalars(
                db.select(RolePermission).where(
                    RolePermission.permission_id == perm.id,
                    RolePermission.active_filter(),
                )
            )
        }
        for role in db.session.scalars(db.select(Role).where(Role.active_filter())):
            if role.id in have:
                continue
            db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))

    @staticmethod
    def _clear_permission_cache() -> None:
        try:
            from app.core.permission_service import PermissionService

            PermissionService.clear_cache()
            from app.core.field_catalog import clear_catalog_cache
            from app.models.auth import field_registry

            clear_catalog_cache()
            field_registry.MODULE_LABELS = field_registry.get_module_labels()
            field_registry.MODULE_FIELDS = field_registry.get_module_fields()
        except Exception:
            pass

    @classmethod
    def _seed_security_catalog(cls) -> None:
        modules: dict[str, SystemModule] = {}
        existing_modules = {
            m.code: m
            for m in db.session.scalars(db.select(SystemModule).where(SystemModule.active_filter()))
        }
        for code, name, icon, sort_order, description in SYSTEM_MODULES:
            if code in existing_modules:
                mod = existing_modules[code]
                mod.name = name
                mod.icon = icon
                mod.sort_order = sort_order
                mod.description = description
            else:
                mod = SystemModule(
                    code=code,
                    name=name,
                    icon=icon,
                    sort_order=sort_order,
                    description=description,
                )
                db.session.add(mod)
            modules[code] = mod
        db.session.flush()

        existing_fields = {
            (str(f.module_id), f.code): f
            for f in db.session.scalars(db.select(FieldDefinition).where(FieldDefinition.active_filter()))
        }
        for module_code, field_rows in MODULE_FIELDS.items():
            mod = modules.get(module_code)
            if mod is None:
                continue
            for field_code, field_name, sort_order in field_rows:
                key = (str(mod.id), field_code)
                if key in existing_fields:
                    # Не затираем ручные правки (название, порядок, видимость)
                    continue
                hidden_defaults = {
                    "responsible_id",
                    "executor_id",
                    "latitude",
                    "longitude",
                    "original_address",
                    "normalized_address",
                    "region",
                    "settlement",
                    "street",
                    "house",
                    "address_source",
                    "address_external_id",
                }
                db.session.add(
                    FieldDefinition(
                        module_id=mod.id,
                        code=field_code,
                        name=field_name,
                        sort_order=sort_order,
                        is_visible=field_code not in hidden_defaults,
                    )
                )
        db.session.flush()

        existing_positions = {
            p.code: p
            for p in db.session.scalars(db.select(Position).where(Position.active_filter()))
        }
        for code, name, sort_order in POSITIONS:
            if code in existing_positions:
                pos = existing_positions[code]
                pos.name = name
                pos.sort_order = sort_order
            else:
                db.session.add(Position(code=code, name=name, sort_order=sort_order))
        db.session.flush()

        existing_perms = {
            p.code: p
            for p in db.session.scalars(db.select(Permission).where(Permission.active_filter()))
        }
        for code, name, module_code, action in build_permission_catalog():
            mod = modules.get(module_code)
            if code in existing_perms:
                perm = existing_perms[code]
                perm.name = name
                perm.module = module_code
                perm.action = action
                perm.module_id = mod.id if mod else None
            else:
                db.session.add(
                    Permission(
                        code=code,
                        name=name,
                        module=module_code,
                        action=action,
                        module_id=mod.id if mod else None,
                    )
                )
        db.session.flush()

    @classmethod
    def _seed_request_statuses(cls) -> None:
        """Создаёт или обновляет статусы workflow (идемпотентно)."""
        existing = {
            item.code: item
            for item in db.session.scalars(
                db.select(RequestStatus).where(RequestStatus.active_filter())
            )
        }
        desired = {row[0] for row in cls.REQUEST_STATUSES}
        for code, name, desc, color, order, is_final in cls.REQUEST_STATUSES:
            if code in existing:
                status = existing[code]
                status.name = name
                status.description = desc
                status.color = color
                status.sort_order = order
                status.is_final = is_final
                status.is_active = True
            else:
                db.session.add(
                    RequestStatus(
                        code=code,
                        name=name,
                        description=desc,
                        color=color,
                        sort_order=order,
                        is_final=is_final,
                    )
                )
        for code, status in existing.items():
            if code not in desired:
                status.is_active = False
        db.session.flush()

    @classmethod
    def _seed_request_journals(cls) -> None:
        existing = {
            item.code: item
            for item in db.session.scalars(
                db.select(RequestJournal).where(RequestJournal.active_filter())
            )
        }
        for code, name, sort_order in REQUEST_JOURNALS:
            if code in existing:
                existing[code].name = name
                existing[code].sort_order = sort_order
                existing[code].is_active = True
            else:
                db.session.add(
                    RequestJournal(code=code, name=name, sort_order=sort_order, is_active=True)
                )
        db.session.flush()

    @classmethod
    def _seed_defect_statuses(cls) -> None:
        existing = {
            item.code: item
            for item in db.session.scalars(
                db.select(DefectStatus).where(DefectStatus.active_filter())
            )
        }
        desired = {row[0] for row in DEFECT_STATUSES}
        for code, name, desc, color, order, is_final in DEFECT_STATUSES:
            if code in existing:
                status = existing[code]
                status.name = name
                status.description = desc
                status.color = color
                status.sort_order = order
                status.is_final = is_final
                status.is_active = True
            else:
                db.session.add(
                    DefectStatus(
                        code=code,
                        name=name,
                        description=desc,
                        color=color,
                        sort_order=order,
                        is_final=is_final,
                    )
                )
        for code, status in existing.items():
            if code not in desired:
                status.is_active = False
        db.session.flush()

    @classmethod
    def _seed_defect_categories(cls) -> None:
        existing = {
            item.code: item
            for item in db.session.scalars(
                db.select(DefectCategory).where(DefectCategory.active_filter())
            )
        }
        for code, name, sort_order in DEFECT_CATEGORIES:
            if code in existing:
                existing[code].name = name
                existing[code].sort_order = sort_order
                existing[code].is_active = True
            else:
                db.session.add(
                    DefectCategory(code=code, name=name, sort_order=sort_order, is_active=True)
                )
        db.session.flush()

    @classmethod
    def _seed_request_dispatchers(cls) -> None:
        """Справочник ФИО диспетчеров для выбора в заявке."""
        existing = {
            item.name: item
            for item in db.session.scalars(
                db.select(RequestDispatcher).where(RequestDispatcher.active_filter())
            )
        }
        for name, sort_order in REQUEST_DISPATCHERS:
            if name in existing:
                existing[name].sort_order = sort_order
                existing[name].is_active = True
            else:
                db.session.add(
                    RequestDispatcher(name=name, sort_order=sort_order, is_active=True)
                )
        db.session.flush()

    @classmethod
    def _seed_roles_and_permissions(cls, force_sync: bool = False) -> None:
        existing_roles = {
            r.code: r
            for r in db.session.scalars(db.select(Role).where(Role.active_filter()))
        }

        if existing_roles and not force_sync:
            if all(code in existing_roles for code in ALL_ROLE_CODES):
                return

        roles: dict[str, Role] = {}
        for code, name, desc, is_system in cls.ROLES:
            if code in existing_roles:
                role = existing_roles[code]
                role.name = name
                role.description = desc
                role.is_system = is_system
            else:
                role = Role(code=code, name=name, description=desc, is_system=is_system)
                db.session.add(role)
            roles[code] = role

        db.session.flush()

        permissions: dict[str, Permission] = {
            p.code: p
            for p in db.session.scalars(db.select(Permission).where(Permission.active_filter()))
        }

        if force_sync:
            system_role_ids = [roles[code].id for code in ALL_ROLE_CODES if code in roles]
            for rp in db.session.scalars(
                db.select(RolePermission).where(
                    RolePermission.active_filter(),
                    RolePermission.role_id.in_(system_role_ids),
                )
            ):
                db.session.delete(rp)
            db.session.flush()

        existing_rp = set()
        if not force_sync:
            for rp in db.session.scalars(db.select(RolePermission).where(RolePermission.active_filter())):
                existing_rp.add((str(rp.role_id), str(rp.permission_id)))

        for role_code, perm_codes in cls.ROLE_PERMISSIONS.items():
            for perm_code in perm_codes:
                if perm_code not in permissions:
                    continue
                role_id = roles[role_code].id
                perm_id = permissions[perm_code].id
                if (str(role_id), str(perm_id)) not in existing_rp:
                    db.session.add(RolePermission(role_id=role_id, permission_id=perm_id))

"""Универсальный сервис журнала действий."""

from __future__ import annotations

import uuid
from typing import Any

from flask import g, has_request_context, request

from app.extensions import db
from app.models.audit.audit_log import AuditLog
from app.models.enums import AuditAction, EntityType

# Человекочитаемые подписи
ACTION_LABELS: dict[str, str] = {
    AuditAction.CREATE.value: "Создание",
    AuditAction.UPDATE.value: "Изменение",
    AuditAction.DELETE.value: "Удаление",
    AuditAction.SOFT_DELETE.value: "Мягкое удаление",
    AuditAction.RESTORE.value: "Восстановление",
    AuditAction.LOGIN.value: "Вход",
    AuditAction.LOGOUT.value: "Выход",
    AuditAction.STATUS_CHANGE.value: "Смена статуса",
    AuditAction.VIEW.value: "Просмотр",
    AuditAction.EXPORT.value: "Экспорт",
}

ENTITY_LABELS: dict[str, str] = {
    EntityType.USER.value: "Пользователь",
    EntityType.ROLE.value: "Роль",
    EntityType.PERMISSION.value: "Разрешение",
    EntityType.REQUEST.value: "Заявка",
    EntityType.REQUEST_JOURNAL.value: "Журнал заявок",
    EntityType.DEFECT.value: "Дефект",
    EntityType.WAYBILL.value: "Путевой лист",
    EntityType.WORK_OBJECT.value: "Объект",
    EntityType.PROJECT.value: "Проект",
    EntityType.TENDER_APPLICATION.value: "Заявка на торги",
    EntityType.CONTRACT.value: "Контракт",
    EntityType.MESSAGE.value: "Сообщение",
    EntityType.NOTIFICATION.value: "Уведомление",
    EntityType.COMMENT.value: "Комментарий",
    EntityType.ATTACHMENT.value: "Файл",
    EntityType.MESSENGER_MESSAGE.value: "Сообщение мессенджера",
    "system": "Система",
    "audit": "Журнал аудита",
}

# Автоописание HTTP-действий по endpoint
HTTP_ENDPOINT_META: dict[str, tuple[str, str, str]] = {
    "requests.create": (AuditAction.CREATE.value, EntityType.REQUEST.value, "Создание заявки"),
    "requests.edit": (AuditAction.UPDATE.value, EntityType.REQUEST.value, "Редактирование заявки"),
    "requests.add_comment": (AuditAction.UPDATE.value, EntityType.REQUEST.value, "Комментарий к заявке"),
    "requests.add_material": (AuditAction.UPDATE.value, EntityType.REQUEST.value, "Добавление материала к заявке"),
    "requests.add_attachment": (AuditAction.UPDATE.value, EntityType.ATTACHMENT.value, "Загрузка файла к заявке"),
    "requests.delete_attachment": (AuditAction.SOFT_DELETE.value, EntityType.ATTACHMENT.value, "Удаление файла заявки"),
    "requests.mark_emergency_departed": (AuditAction.STATUS_CHANGE.value, EntityType.REQUEST.value, "Выезд аварийной бригады"),
    "requests.assign_master": (AuditAction.STATUS_CHANGE.value, EntityType.REQUEST.value, "Передача заявки мастеру"),
    "requests.accept_request": (AuditAction.STATUS_CHANGE.value, EntityType.REQUEST.value, "Принятие заявки мастером"),
    "requests.start_work": (AuditAction.STATUS_CHANGE.value, EntityType.REQUEST.value, "Старт работ по заявке"),
    "requests.complete_request": (AuditAction.STATUS_CHANGE.value, EntityType.REQUEST.value, "Выполнение заявки"),
    "requests.cancel_request": (AuditAction.STATUS_CHANGE.value, EntityType.REQUEST.value, "Отмена заявки"),
    "defects.create": (AuditAction.CREATE.value, EntityType.DEFECT.value, "Создание дефекта"),
    "defects.edit": (AuditAction.UPDATE.value, EntityType.DEFECT.value, "Редактирование дефекта"),
    "defects.change_status": (AuditAction.STATUS_CHANGE.value, EntityType.DEFECT.value, "Смена статуса дефекта"),
    "defects.add_comment": (AuditAction.UPDATE.value, EntityType.DEFECT.value, "Комментарий к дефекту"),
    "defects.add_attachment": (AuditAction.UPDATE.value, EntityType.ATTACHMENT.value, "Загрузка файла к дефекту"),
    "defects.delete_attachment": (AuditAction.SOFT_DELETE.value, EntityType.ATTACHMENT.value, "Удаление файла дефекта"),
    "waybills.create": (AuditAction.CREATE.value, EntityType.WAYBILL.value, "Создание путевого листа"),
    "waybills.edit": (AuditAction.UPDATE.value, EntityType.WAYBILL.value, "Редактирование путевого листа"),
    "waybills.change_status": (AuditAction.STATUS_CHANGE.value, EntityType.WAYBILL.value, "Смена статуса путевого листа"),
    "waybills.add_stop": (AuditAction.UPDATE.value, EntityType.WAYBILL.value, "Добавление точки путевого листа"),
    "waybills.remove_stop": (AuditAction.UPDATE.value, EntityType.WAYBILL.value, "Удаление точки путевого листа"),
    "waybills.reorder": (AuditAction.UPDATE.value, EntityType.WAYBILL.value, "Порядок точек путевого листа"),
    "projects.create": (AuditAction.CREATE.value, EntityType.PROJECT.value, "Создание проекта"),
    "projects.edit": (AuditAction.UPDATE.value, EntityType.PROJECT.value, "Редактирование проекта"),
    "projects.add_comment": (AuditAction.UPDATE.value, EntityType.PROJECT.value, "Комментарий к проекту"),
    "projects.add_document": (AuditAction.UPDATE.value, EntityType.PROJECT.value, "Добавление документа к проекту"),
    "projects.add_attachment": (AuditAction.UPDATE.value, EntityType.ATTACHMENT.value, "Загрузка файла к проекту"),
    "objects.create": (AuditAction.CREATE.value, EntityType.WORK_OBJECT.value, "Создание объекта"),
    "objects.edit": (AuditAction.UPDATE.value, EntityType.WORK_OBJECT.value, "Редактирование объекта"),
    "tenders.create": (AuditAction.CREATE.value, EntityType.TENDER_APPLICATION.value, "Создание заявки на торги"),
    "tenders.edit": (AuditAction.UPDATE.value, EntityType.TENDER_APPLICATION.value, "Редактирование заявки на торги"),
    "tenders.add_document": (AuditAction.UPDATE.value, EntityType.TENDER_APPLICATION.value, "Документ заявки на торги"),
    "contracts.create": (AuditAction.CREATE.value, EntityType.CONTRACT.value, "Создание контракта"),
    "contracts.edit": (AuditAction.UPDATE.value, EntityType.CONTRACT.value, "Редактирование контракта"),
    "contracts.add_comment": (AuditAction.UPDATE.value, EntityType.CONTRACT.value, "Комментарий к контракту"),
    "contracts.add_document": (AuditAction.UPDATE.value, EntityType.CONTRACT.value, "Добавление документа к контракту"),
    "contracts.add_attachment": (AuditAction.UPDATE.value, EntityType.ATTACHMENT.value, "Загрузка файла к контракту"),
    "auth.login": (AuditAction.LOGIN.value, EntityType.USER.value, "Вход в систему"),
    "auth.logout": (AuditAction.LOGOUT.value, EntityType.USER.value, "Выход из системы"),
    "auth.change_password": (AuditAction.UPDATE.value, EntityType.USER.value, "Смена пароля"),
    "auth.profile": (AuditAction.UPDATE.value, EntityType.USER.value, "Обновление профиля"),
    "messenger.send_message": ("create", EntityType.MESSENGER_MESSAGE.value, "Отправка сообщения"),
    "messenger.send_attachment": ("create", EntityType.ATTACHMENT.value, "Отправка файла в мессенджере"),
    "audit.export": ("export", "audit", "Экспорт журнала действий"),
}

SKIP_AUTO_AUDIT_ENDPOINTS = frozenset(
    {
        "static",
        "main.health",
        "messenger.heartbeat",
        "messenger.unread_count",
        "messenger.events_stream",
        "search.api",
        "audit.table",
        "requests.table",
        "requests.index",
        "projects.table",
        "projects.index",
        "contracts.table",
        "contracts.index",
        "tenders.table",
        "tenders.index",
        "objects.table",
        "objects.index",
        "employees.table",
        "employees.index",
        "roles.table",
        "roles.index",
        "reports.index",
        "audit.index",
    }
)


class AuditService:
    """Единая точка записи в журнал действий."""

    @staticmethod
    def _client_ip() -> str | None:
        if not has_request_context():
            return None
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.remote_addr

    @staticmethod
    def _user_agent() -> str | None:
        if not has_request_context():
            return None
        return request.headers.get("User-Agent")

    @classmethod
    def log(
        cls,
        *,
        user_id: uuid.UUID | None,
        action: str,
        description: str,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        commit: bool = False,
    ) -> AuditLog:
        entry = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description.strip(),
            old_values=old_values,
            new_values=new_values,
            ip_address=ip_address if ip_address is not None else cls._client_ip(),
            user_agent=user_agent if user_agent is not None else cls._user_agent(),
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(entry)
        if has_request_context():
            g.audit_logged = True
        if commit:
            db.session.commit()
        return entry

    @classmethod
    def log_http_action(cls, user_id: uuid.UUID, endpoint: str, method: str) -> AuditLog | None:
        if endpoint in SKIP_AUTO_AUDIT_ENDPOINTS:
            return None

        meta = HTTP_ENDPOINT_META.get(endpoint)
        if meta:
            action, entity_type, description = meta
        elif method == "GET":
            action, entity_type, description = "view", "system", f"Просмотр: {endpoint}"
        else:
            action, entity_type, description = (
                AuditAction.UPDATE.value,
                "system",
                f"HTTP {method} {endpoint}",
            )

        entity_id = None
        if has_request_context():
            for key in ("request_id", "project_id", "contract_id", "user_id", "message_id"):
                val = request.view_args.get(key) if request.view_args else None
                if val:
                    try:
                        entity_id = uuid.UUID(str(val))
                        break
                    except ValueError:
                        pass

        return cls.log(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
        )

    @staticmethod
    def action_label(action: str) -> str:
        return ACTION_LABELS.get(action, action)

    @staticmethod
    def entity_label(entity_type: str | None) -> str:
        if not entity_type:
            return "—"
        return ENTITY_LABELS.get(entity_type, entity_type)

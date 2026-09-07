"""API уведомлений (колокольчик в шапке)."""

from __future__ import annotations

import uuid

from flask import current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func, select

from app.extensions import db
from app.models.base import utcnow
from app.models.communication.notification import Notification
from app.modules.notifications.blueprint import notifications_bp
from app.modules.notifications.push_service import PushNotificationService


@notifications_bp.route("/push/config")
@login_required
def push_config():
    configured = PushNotificationService.is_configured()
    return jsonify({"configured": configured, "public_key": current_app.config.get("WEB_PUSH_VAPID_PUBLIC_KEY", "") if configured else ""})


@notifications_bp.route("/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    if not PushNotificationService.is_configured():
        return jsonify({"ok": False, "message": "Системные push-уведомления не настроены на сервере."}), 503
    try:
        PushNotificationService.subscribe(current_user.id, request.get_json(silent=True) or {}, request.headers.get("User-Agent"))
    except PermissionError:
        return jsonify({"ok": False, "message": "Подписка принадлежит другому пользователю."}), 403
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    return jsonify({"ok": True})


@notifications_bp.route("/push/unsubscribe", methods=["POST"])
@login_required
def push_unsubscribe():
    endpoint = str((request.get_json(silent=True) or {}).get("endpoint") or "")
    if not endpoint:
        return jsonify({"ok": False, "message": "Не указан endpoint."}), 400
    return jsonify({"ok": PushNotificationService.unsubscribe(current_user.id, endpoint)})


@notifications_bp.route("/api/unread")
@login_required
def unread_api():
    rows = list(
        db.session.scalars(
            select(Notification)
            .where(
                Notification.user_id == current_user.id,
                Notification.is_read.is_(False),
                Notification.active_filter(),
            )
            .order_by(Notification.created_at.desc())
            .limit(20)
        )
    )
    total = (
        db.session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == current_user.id,
                Notification.is_read.is_(False),
                Notification.active_filter(),
            )
        )
        or 0
    )
    items = [
        {
            "id": str(row.id),
            "title": row.title,
            "message": row.message,
            "type": row.type,
            "link": row.link or "#",
            "created_at": row.created_at.strftime("%d.%m.%Y %H:%M") if row.created_at else "",
        }
        for row in rows
    ]
    return jsonify({"total": total, "items": items})


@notifications_bp.route("/api/<uuid:notification_id>/read", methods=["POST"])
@login_required
def mark_read(notification_id: uuid.UUID):
    row = db.session.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
            Notification.active_filter(),
        )
    )
    if row is None:
        return jsonify({"ok": False}), 404
    if not row.is_read:
        row.is_read = True
        row.read_at = utcnow()
        row.updated_by = current_user.id
        db.session.commit()
    return jsonify({"ok": True})


@notifications_bp.route("/api/read-all", methods=["POST"])
@login_required
def mark_all_read():
    rows = list(
        db.session.scalars(
            select(Notification).where(
                Notification.user_id == current_user.id,
                Notification.is_read.is_(False),
                Notification.active_filter(),
            )
        )
    )
    now = utcnow()
    for row in rows:
        row.is_read = True
        row.read_at = now
        row.updated_by = current_user.id
    db.session.commit()
    return jsonify({"ok": True, "marked": len(rows)})

"""API уведомлений (колокольчик в шапке)."""

from __future__ import annotations

import uuid

from flask import jsonify
from flask_login import current_user, login_required
from sqlalchemy import func, select

from app.extensions import db
from app.models.base import utcnow
from app.models.communication.notification import Notification
from app.modules.notifications.blueprint import notifications_bp


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

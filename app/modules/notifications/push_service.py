"""Единая отправка Web Push, не влияющая на обычный мессенджер."""

from __future__ import annotations

import uuid

from flask import current_app

from app.extensions import db
from app.models.base import utcnow
from app.models.communication.push_subscription import PushSubscription


class PushNotificationService:
    @staticmethod
    def is_configured() -> bool:
        config = current_app.config
        return bool(config.get("WEB_PUSH_VAPID_PUBLIC_KEY") and config.get("WEB_PUSH_VAPID_PRIVATE_KEY") and config.get("WEB_PUSH_VAPID_SUBJECT"))

    @classmethod
    def subscribe(cls, user_id: uuid.UUID, subscription: dict, user_agent: str | None) -> PushSubscription:
        endpoint = str(subscription.get("endpoint") or "").strip()
        keys = subscription.get("keys") or {}
        p256dh, auth = str(keys.get("p256dh") or "").strip(), str(keys.get("auth") or "").strip()
        if not endpoint or not p256dh or not auth or len(endpoint) > 4000:
            raise ValueError("Некорректная подписка браузера.")
        item = db.session.scalar(db.select(PushSubscription).where(PushSubscription.endpoint == endpoint))
        if item is None:
            item = PushSubscription(user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=(user_agent or "")[:500], is_active=True, created_by=user_id, updated_by=user_id)
            db.session.add(item)
        elif item.user_id == user_id:
            item.p256dh, item.auth, item.user_agent, item.is_active, item.updated_by = p256dh, auth, (user_agent or "")[:500], True, user_id
        else:
            # Endpoint belongs to another account: it must never be reassigned by a client.
            raise PermissionError("Эта подписка уже принадлежит другому пользователю.")
        item.last_used_at = utcnow()
        db.session.commit()
        return item

    @classmethod
    def unsubscribe(cls, user_id: uuid.UUID, endpoint: str) -> bool:
        item = db.session.scalar(db.select(PushSubscription).where(PushSubscription.endpoint == endpoint, PushSubscription.user_id == user_id, PushSubscription.active_filter()))
        if item is None:
            return False
        item.is_active = False
        item.updated_by = user_id
        item.last_used_at = utcnow()
        db.session.commit()
        return True

    @classmethod
    def send_to_user(cls, user_id: uuid.UUID, *, title: str, body: str, url: str, icon: str) -> int:
        if not cls.is_configured() or not url.startswith("/"):
            return 0
        try:
            from pywebpush import WebPushException, webpush
        except ImportError:
            current_app.logger.warning("Web Push включён в env, но пакет pywebpush не установлен")
            return 0
        sent = 0
        rows = list(db.session.scalars(db.select(PushSubscription).where(PushSubscription.user_id == user_id, PushSubscription.is_active.is_(True), PushSubscription.active_filter())))
        payload = {"title": title[:120], "body": body[:140], "url": url, "icon": icon}
        for item in rows:
            try:
                webpush(subscription_info={"endpoint": item.endpoint, "keys": {"p256dh": item.p256dh, "auth": item.auth}}, data=__import__("json").dumps(payload, ensure_ascii=False), vapid_private_key=current_app.config["WEB_PUSH_VAPID_PRIVATE_KEY"], vapid_claims={"sub": current_app.config["WEB_PUSH_VAPID_SUBJECT"]})
                item.last_used_at = utcnow(); sent += 1
            except WebPushException as exc:
                if getattr(getattr(exc, "response", None), "status_code", None) in {404, 410}:
                    item.is_active = False
            except Exception:
                current_app.logger.exception("Не удалось отправить Web Push")
        if rows:
            db.session.commit()
        return sent

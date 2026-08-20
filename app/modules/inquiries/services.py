"""Забор писем с kirovsvet@mail.ru и карточки обращений."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ValidationError
from app.core.upload_utils import safe_upload_filename
from app.extensions import db
from app.models.base import utcnow
from app.models.files.attachment import Attachment
from app.models.inquiries.inquiry import STATUS_DONE, STATUS_NEW, STATUS_SEEN, Inquiry
from app.models.inquiries.mailbox_state import InquiryMailboxState
from app.modules.inquiries.imap_client import ImapError, ImapMailbox, connect_mailbox
from app.modules.inquiries.parse_email import parse_rfc822

logger = logging.getLogger(__name__)

_sync_lock = threading.Lock()
_sync_running = False

ENTITY_TYPE = "inquiry"
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


@dataclass
class SyncResult:
    fetched: int = 0
    skipped: int = 0
    error: str | None = None
    configured: bool = True


class InquiryService:
    @staticmethod
    def mailbox_config(app=None) -> dict[str, object]:
        from flask import current_app

        cfg = app.config if app is not None else current_app.config
        user = str(cfg.get("INQUIRY_IMAP_USER") or cfg.get("INQUIRY_MAILBOX") or "").strip()
        password = str(cfg.get("INQUIRY_IMAP_PASSWORD") or "").strip().strip('"').strip("'")
        return {
            "mailbox": str(cfg.get("INQUIRY_MAILBOX") or user or "kirovsvet@mail.ru").strip().lower(),
            "host": str(cfg.get("INQUIRY_IMAP_HOST") or "imap.mail.ru").strip(),
            "port": int(cfg.get("INQUIRY_IMAP_PORT") or 993),
            "user": user,
            "password": password,
            "folder": str(cfg.get("INQUIRY_IMAP_FOLDER") or "INBOX").strip() or "INBOX",
            "limit": int(cfg.get("INQUIRY_FETCH_LIMIT") or 40),
        }

    @classmethod
    def is_configured(cls) -> bool:
        cfg = cls.mailbox_config()
        return bool(cfg["user"] and cfg["password"])

    @classmethod
    def test_connection(cls) -> tuple[bool, str]:
        cfg = cls.mailbox_config()
        if not cfg["user"] or not cfg["password"]:
            return False, "В .env нет INQUIRY_IMAP_PASSWORD."
        mailbox_client = None
        try:
            mailbox_client = connect_mailbox(
                host=str(cfg["host"]),
                port=int(cfg["port"]),
                user=str(cfg["user"]),
                password=str(cfg["password"]),
            )
            snapshot = mailbox_client.snapshot(str(cfg["folder"]), after_uid=0, limit=1)
            return True, (
                f"Вход в {cfg['user']} успешен. Папка {cfg['folder']}, "
                f"UIDVALIDITY {snapshot.uidvalidity}."
            )
        except ImapError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"Вход в ящик не удался: {exc}"
        finally:
            if mailbox_client is not None:
                mailbox_client.close()

    @classmethod
    def mailbox_state(cls) -> InquiryMailboxState | None:
        cfg = cls.mailbox_config()
        return db.session.scalar(
            db.select(InquiryMailboxState).where(
                InquiryMailboxState.mailbox == cfg["mailbox"],
                InquiryMailboxState.folder == cfg["folder"],
                InquiryMailboxState.deleted_at.is_(None),
            )
        )

    @classmethod
    def is_running(cls) -> bool:
        return _sync_running

    @classmethod
    def sync(cls, *, client: ImapMailbox | None = None, user_id: uuid.UUID | None = None) -> SyncResult:
        global _sync_running
        if not _sync_lock.acquire(blocking=False):
            return SyncResult(error="Забор писем уже идёт.")
        _sync_running = True
        own_client = client is None
        try:
            return cls._sync_locked(client=client, own_client=own_client, user_id=user_id)
        finally:
            _sync_running = False
            _sync_lock.release()

    @classmethod
    def _sync_locked(
        cls,
        *,
        client: ImapMailbox | None,
        own_client: bool,
        user_id: uuid.UUID | None,
    ) -> SyncResult:
        from flask import current_app

        cfg = cls.mailbox_config()
        if client is None and (not cfg["user"] or not cfg["password"]):
            return SyncResult(
                configured=False,
                error="В .env нет пароля ящика (INQUIRY_IMAP_PASSWORD).",
            )
        state = cls._get_or_create_state(str(cfg["mailbox"]), str(cfg["folder"]))
        mailbox_client = client
        try:
            if mailbox_client is None:
                mailbox_client = connect_mailbox(
                    host=str(cfg["host"]),
                    port=int(cfg["port"]),
                    user=str(cfg["user"]),
                    password=str(cfg["password"]),
                )
            snapshot = mailbox_client.snapshot(
                str(cfg["folder"]),
                after_uid=state.last_uid if state.uidvalidity else 0,
                limit=int(cfg["limit"]),
            )
            if state.uidvalidity and snapshot.uidvalidity and state.uidvalidity != snapshot.uidvalidity:
                state.last_uid = 0
                snapshot = mailbox_client.snapshot(str(cfg["folder"]), after_uid=0, limit=int(cfg["limit"]))
            state.uidvalidity = snapshot.uidvalidity
            fetched = 0
            skipped = 0
            max_uid = state.last_uid
            upload_root: Path = current_app.config["UPLOAD_FOLDER"]
            for uid in snapshot.uids:
                if cls._exists(str(cfg["mailbox"]), snapshot.uidvalidity, uid):
                    skipped += 1
                    max_uid = max(max_uid, uid)
                    continue
                raw = mailbox_client.fetch_rfc822(uid)
                parsed = parse_rfc822(raw)
                inquiry = Inquiry(
                    mailbox=str(cfg["mailbox"]),
                    imap_uid=uid,
                    imap_uidvalidity=snapshot.uidvalidity,
                    message_id=parsed.message_id,
                    from_name=(parsed.from_name or "")[:500] or None,
                    from_email=(parsed.from_email or "")[:255] or None,
                    to_email=parsed.to_email,
                    subject=parsed.subject[:1000],
                    body_text=parsed.body_text,
                    body_html=parsed.body_html,
                    received_at=parsed.received_at or utcnow(),
                    status=STATUS_NEW,
                    parse_warning=parsed.warning,
                    created_by=user_id,
                    updated_by=user_id,
                )
                db.session.add(inquiry)
                try:
                    db.session.flush()
                except IntegrityError:
                    db.session.rollback()
                    state = cls._get_or_create_state(str(cfg["mailbox"]), str(cfg["folder"]))
                    skipped += 1
                    max_uid = max(max_uid, uid)
                    continue
                saved = 0
                for index, item in enumerate(parsed.attachments, start=1):
                    if len(item.payload) > MAX_ATTACHMENT_BYTES:
                        continue
                    name = safe_upload_filename(item.file_name, default_stem=f"file-{index}")
                    relative = f"inquiries/{inquiry.id}/{uuid.uuid4().hex[:8]}_{name}"
                    path = upload_root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(item.payload)
                    db.session.add(
                        Attachment(
                            uploaded_by=user_id,
                            entity_type=ENTITY_TYPE,
                            entity_id=inquiry.id,
                            file_name=name[:500],
                            storage_key=relative.replace("\\", "/"),
                            mime_type=(item.mime_type or "application/octet-stream")[:100],
                            file_size=len(item.payload),
                        )
                    )
                    saved += 1
                inquiry.attachment_count = saved
                db.session.commit()
                fetched += 1
                max_uid = max(max_uid, uid)
            state = cls._get_or_create_state(str(cfg["mailbox"]), str(cfg["folder"]))
            state.last_uid = max_uid
            state.uidvalidity = snapshot.uidvalidity
            state.touch_ok()
            db.session.commit()
            return SyncResult(fetched=fetched, skipped=skipped)
        except ImapError as exc:
            db.session.rollback()
            state = cls._get_or_create_state(str(cfg["mailbox"]), str(cfg["folder"]))
            state.last_error = str(exc)[:1000]
            db.session.commit()
            logger.warning("IMAP обращений: %s", exc)
            return SyncResult(error=str(exc))
        except Exception as exc:
            db.session.rollback()
            logger.exception("Синхронизация обращений")
            return SyncResult(error=str(exc))
        finally:
            if own_client and mailbox_client is not None:
                mailbox_client.close()

    @staticmethod
    def _get_or_create_state(mailbox: str, folder: str) -> InquiryMailboxState:
        state = db.session.scalar(
            db.select(InquiryMailboxState).where(
                InquiryMailboxState.mailbox == mailbox,
                InquiryMailboxState.folder == folder,
                InquiryMailboxState.deleted_at.is_(None),
            )
        )
        if state is None:
            state = InquiryMailboxState(mailbox=mailbox, folder=folder, last_uid=0)
            db.session.add(state)
            db.session.flush()
        return state

    @staticmethod
    def _exists(mailbox: str, uidvalidity: int, uid: int) -> bool:
        return (
            db.session.scalar(
                db.select(Inquiry.id).where(
                    Inquiry.mailbox == mailbox,
                    Inquiry.imap_uidvalidity == uidvalidity,
                    Inquiry.imap_uid == uid,
                    Inquiry.deleted_at.is_(None),
                )
            )
            is not None
        )

    @staticmethod
    def attachments(inquiry_id: uuid.UUID) -> list[Attachment]:
        return list(
            db.session.scalars(
                db.select(Attachment).where(
                    Attachment.entity_type == ENTITY_TYPE,
                    Attachment.entity_id == inquiry_id,
                    Attachment.deleted_at.is_(None),
                )
            )
        )

    @classmethod
    def set_status(cls, inquiry: Inquiry, status: str, user_id: uuid.UUID | None) -> None:
        if status not in {STATUS_NEW, STATUS_SEEN, STATUS_DONE}:
            raise ValidationError("Неизвестный статус обращения.")
        inquiry.status = status
        inquiry.updated_by = user_id
        if status == STATUS_DONE:
            inquiry.processed_by = user_id
        db.session.commit()

    @classmethod
    def mark_seen(cls, inquiry: Inquiry, user_id: uuid.UUID | None) -> None:
        if inquiry.status == STATUS_NEW:
            inquiry.status = STATUS_SEEN
            inquiry.updated_by = user_id
            db.session.commit()

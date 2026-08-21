"""Забор писем с kirovsvet@mail.ru и карточки обращений."""

from __future__ import annotations

import logging
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ValidationError
from app.core.upload_utils import safe_upload_filename
from app.extensions import db
from app.models.base import utcnow
from app.models.files.attachment import Attachment
from app.models.inquiries.inquiry import STATUS_DONE, STATUS_NEW, STATUS_SEEN, Inquiry
from app.models.inquiries.mailbox_state import InquiryMailboxState
from app.modules.inquiries.imap_client import ImapError, ImapMailbox, connect_mailbox
from app.modules.inquiries.parse_email import parse_headers_only, parse_rfc822

logger = logging.getLogger(__name__)

_sync_lock = threading.Lock()
_sync_running = False

ENTITY_TYPE = "inquiry"
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
ADVISORY_LOCK_KEY = 82917701


@dataclass
class SyncResult:
    fetched: int = 0
    skipped: int = 0
    skipped_old: int = 0
    purged: int = 0
    restored: int = 0
    error: str | None = None
    configured: bool = True


def _year_cutoff(year: int) -> datetime:
    return datetime(int(year), 1, 1, tzinfo=timezone.utc)


def _is_recent(value: datetime | None, year_from: int) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value >= _year_cutoff(year_from)


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
            "limit": int(cfg.get("INQUIRY_FETCH_LIMIT") or 15),
            "year_from": int(cfg.get("INQUIRY_YEAR_FROM") or 2026),
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
            since = date(int(cfg["year_from"]), 1, 1)
            snapshot = mailbox_client.snapshot(str(cfg["folder"]), after_uid=0, limit=1, since=since)
            return True, (
                f"Вход в {cfg['user']} успешен. Папка {cfg['folder']}, "
                f"с {cfg['year_from']} года, UIDVALIDITY {snapshot.uidvalidity}."
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
    def purge_older_than_year(cls, year_from: int | None = None) -> int:
        cfg = cls.mailbox_config()
        year = int(year_from or cfg["year_from"])
        cutoff = _year_cutoff(year)
        ids = list(
            db.session.scalars(
                db.select(Inquiry.id).where(
                    Inquiry.received_at.is_not(None),
                    Inquiry.received_at < cutoff,
                )
            )
        )
        if not ids:
            return 0
        from flask import current_app

        upload_root: Path = current_app.config["UPLOAD_FOLDER"]
        files = list(
            db.session.scalars(
                db.select(Attachment).where(
                    Attachment.entity_type == ENTITY_TYPE,
                    Attachment.entity_id.in_(ids),
                )
            )
        )
        for item in files:
            path = upload_root / item.storage_key
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                pass
            folder = upload_root / "inquiries" / str(item.entity_id)
            if folder.is_dir():
                shutil.rmtree(folder, ignore_errors=True)
        db.session.execute(
            delete(Attachment).where(
                Attachment.entity_type == ENTITY_TYPE,
                Attachment.entity_id.in_(ids),
            )
        )
        db.session.execute(delete(Inquiry).where(Inquiry.id.in_(ids)))
        db.session.commit()
        logger.info("Обращения: удалены письма старше %s, %s шт.", year, len(ids))
        return len(ids)

    @classmethod
    def sync(cls, *, client: ImapMailbox | None = None, user_id: uuid.UUID | None = None) -> SyncResult:
        global _sync_running
        if not cls._acquire_lock():
            return SyncResult(error="Забор писем уже идёт.")
        _sync_running = True
        own_client = client is None
        try:
            return cls._sync_locked(client=client, own_client=own_client, user_id=user_id)
        finally:
            _sync_running = False
            cls._release_lock()

    @staticmethod
    def _acquire_lock() -> bool:
        bind = db.session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            got = db.session.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY}
            ).scalar()
            return bool(got)
        return _sync_lock.acquire(blocking=False)

    @staticmethod
    def _release_lock() -> None:
        bind = db.session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            try:
                db.session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})
            except Exception:
                pass
            return
        if _sync_lock.locked():
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
        year_from = int(cfg["year_from"])
        purged = cls.purge_older_than_year(year_from)
        if client is None and (not cfg["user"] or not cfg["password"]):
            return SyncResult(
                configured=False,
                purged=purged,
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
            since = date(year_from, 1, 1)
            snapshot = mailbox_client.snapshot(
                str(cfg["folder"]),
                after_uid=0,
                limit=int(cfg["limit"]),
                since=since,
            )
            upload_root: Path = current_app.config["UPLOAD_FOLDER"]
            restored = cls.restore_missing_attachments(
                mailbox_client,
                upload_root,
                limit=int(cfg["limit"]),
            )
            if state.uidvalidity and snapshot.uidvalidity and state.uidvalidity != snapshot.uidvalidity:
                state.uidvalidity = snapshot.uidvalidity
            state.uidvalidity = snapshot.uidvalidity
            imported = set()
            if snapshot.uids:
                imported = set(
                    db.session.scalars(
                        db.select(Inquiry.imap_uid).where(
                            Inquiry.mailbox == str(cfg["mailbox"]),
                            Inquiry.imap_uidvalidity == snapshot.uidvalidity,
                            Inquiry.imap_uid.in_(list(snapshot.uids)),
                        )
                    )
                )
            batch = [uid for uid in reversed(snapshot.uids) if uid not in imported][: int(cfg["limit"])]
            fetched = 0
            skipped = 0
            skipped_old = 0
            max_uid = state.last_uid
            for uid in batch:
                header_raw = mailbox_client.peek_headers(uid)
                header_date, header_subject, header_from, header_mid = (
                    parse_headers_only(header_raw) if header_raw else (None, "(без темы)", None, None)
                )
                if header_date is not None and not _is_recent(header_date, year_from):
                    skipped_old += 1
                    max_uid = max(max_uid, uid)
                    continue
                size = mailbox_client.message_size(uid)
                if size > MAX_MESSAGE_BYTES:
                    inquiry = Inquiry(
                        mailbox=str(cfg["mailbox"]),
                        imap_uid=uid,
                        imap_uidvalidity=snapshot.uidvalidity,
                        message_id=header_mid,
                        from_email=(header_from or "")[:255] or None,
                        subject=(header_subject or "(без темы)")[:1000],
                        received_at=header_date or utcnow(),
                        status=STATUS_NEW,
                        parse_warning="Письмо больше 8 МБ — не скачивали, чтобы не класть сервер.",
                        created_by=user_id,
                        updated_by=user_id,
                    )
                    db.session.add(inquiry)
                    try:
                        db.session.commit()
                    except IntegrityError:
                        db.session.rollback()
                    skipped += 1
                    max_uid = max(max_uid, uid)
                    continue
                raw = mailbox_client.fetch_rfc822(uid)
                parsed = parse_rfc822(raw)
                received_at = parsed.received_at or header_date
                if not _is_recent(received_at, year_from):
                    skipped_old += 1
                    max_uid = max(max_uid, uid)
                    continue
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
                    body_html=None,
                    received_at=received_at or utcnow(),
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
            return SyncResult(
                fetched=fetched,
                skipped=skipped,
                skipped_old=skipped_old,
                purged=purged,
                restored=restored,
            )
        except ImapError as exc:
            db.session.rollback()
            state = cls._get_or_create_state(str(cfg["mailbox"]), str(cfg["folder"]))
            state.last_error = str(exc)[:1000]
            db.session.commit()
            logger.warning("IMAP обращений: %s", exc)
            return SyncResult(error=str(exc), purged=purged)
        except Exception as exc:
            db.session.rollback()
            logger.exception("Синхронизация обращений")
            return SyncResult(error=str(exc), purged=purged)
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
    def attachment_disk_path(item: Attachment, upload_root: Path | None = None) -> Path:
        from flask import current_app

        root = Path(upload_root or current_app.config["UPLOAD_FOLDER"])
        key = str(item.storage_key or "").replace("\\", "/").lstrip("/")
        return root / key

    @classmethod
    def restore_missing_attachments(
        cls,
        mailbox_client: ImapMailbox,
        upload_root: Path,
        *,
        limit: int = 15,
    ) -> int:
        """Перекачать с ящика файлы, которые есть в БД, но нет на диске.

        inquiry-sync раньше писал вложения в свой контейнер без тома uploads.
        """
        files = list(
            db.session.scalars(
                db.select(Attachment).where(
                    Attachment.entity_type == ENTITY_TYPE,
                    Attachment.deleted_at.is_(None),
                )
            )
        )
        missing: dict[uuid.UUID, list[Attachment]] = {}
        for item in files:
            if not cls.attachment_disk_path(item, upload_root).is_file():
                missing.setdefault(item.entity_id, []).append(item)
        if not missing:
            return 0

        inquiry_ids = list(missing.keys())[: max(1, min(int(limit), 50))]
        inquiries = list(
            db.session.scalars(
                db.select(Inquiry).where(
                    Inquiry.id.in_(inquiry_ids),
                    Inquiry.deleted_at.is_(None),
                )
            )
        )
        restored = 0
        for inquiry in inquiries:
            uid = inquiry.imap_uid
            if not uid:
                continue
            try:
                raw = mailbox_client.fetch_rfc822(uid)
            except ImapError as exc:
                logger.warning("Обращения: не скачали вложения UID %s: %s", uid, exc)
                continue
            parsed = parse_rfc822(raw)
            unused = [part for part in parsed.attachments if len(part.payload) <= MAX_ATTACHMENT_BYTES]
            for item in missing.get(inquiry.id, []):
                wanted = (item.file_name or "").casefold()
                match = next(
                    (part for part in unused if (part.file_name or "").casefold() == wanted),
                    None,
                )
                if match is None and unused:
                    match = unused[0]
                if match is None:
                    continue
                unused.remove(match)
                path = cls.attachment_disk_path(item, upload_root)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(match.payload)
                restored += 1
        if restored:
            logger.info("Обращения: восстановлено файлов с ящика: %s", restored)
        return restored

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

    @classmethod
    def forward(cls, inquiry: Inquiry, *, to_user_id: uuid.UUID, actor) -> dict:
        from flask import url_for

        from app.modules.auth.repositories import UserRepository
        from app.modules.inquiries.access import can_access_inquiry
        from app.modules.messenger.cards import snapshot_inquiry
        from app.modules.messenger.repositories import MessengerRepository
        from app.modules.messenger.services import MessengerService

        if not can_access_inquiry(actor, inquiry):
            raise ValidationError("Нет доступа к письму.")
        if to_user_id == actor.id:
            raise ValidationError("Нельзя переслать письмо себе.")
        peer = UserRepository.get_by_id(to_user_id)
        if peer is None or peer.deleted_at is not None or not peer.is_active or peer.is_blocked:
            raise ValidationError("Сотрудник не найден.")

        card = snapshot_inquiry(inquiry)
        inquiry.assigned_to = peer.id
        inquiry.forwarded_by = actor.id
        inquiry.forwarded_at = utcnow()
        inquiry.updated_by = actor.id
        db.session.flush()

        conversation = MessengerRepository.get_or_create_conversation(
            actor.id,
            peer.id,
            created_by=actor.id,
        )
        message = MessengerService.send_card(
            conversation,
            sender_id=actor.id,
            card=card,
            body=f"Переслал письмо: {inquiry.subject}",
        )
        return {
            "conversation_id": str(conversation.id),
            "message_id": str(message.id),
            "url": url_for("messenger.index", c=conversation.id),
            "assignee_name": peer.full_name,
        }

"""Обращения: разбор писем и забор с ящика без сети."""

from __future__ import annotations

from datetime import date, datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.extensions import db
from app.models.files.attachment import Attachment
from app.models.inquiries.inquiry import Inquiry
from app.modules.inquiries.imap_client import MailboxSnapshot, _login_error, _password_variants, imap_since_token
from app.modules.inquiries.parse_email import parse_rfc822
from app.modules.inquiries.services import InquiryService


def _sample_message(*, subject: str = "Свет не горит", with_file: bool = False, date: str = "Thu, 20 Aug 2026 10:00:00 +0300") -> bytes:
    if with_file:
        message = MIMEMultipart()
        message.attach(MIMEText("Прошу посмотреть опору на ул. Ленина.", "plain", "utf-8"))
        part = MIMEText("файл", "plain", "utf-8")
        part.add_header("Content-Disposition", "attachment", filename="zametka.txt")
        message.attach(part)
    else:
        message = MIMEText("Прошу посмотреть опору на ул. Ленина.", "plain", "utf-8")
    message["From"] = "Иван Петров <ivan@example.com>"
    message["To"] = "kirovsvet@mail.ru"
    message["Subject"] = subject
    message["Message-ID"] = f"<{subject.replace(' ', '-')}@example.com>"
    message["Date"] = date
    return message.as_bytes()


class FakeMailbox:
    def __init__(self, messages: dict[int, bytes], uidvalidity: int = 7) -> None:
        self.messages = messages
        self.uidvalidity = uidvalidity

    def snapshot(self, folder: str, after_uid: int, limit: int, since=None) -> MailboxSnapshot:
        uids = [uid for uid in sorted(self.messages) if uid > after_uid]
        if since is not None:
            cutoff = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)
            kept = []
            for uid in uids:
                parsed = parse_rfc822(self.messages[uid])
                if parsed.received_at is not None and parsed.received_at >= cutoff:
                    kept.append(uid)
            uids = kept
        return MailboxSnapshot(uidvalidity=self.uidvalidity, uids=uids)

    def peek_headers(self, uid: int) -> bytes:
        return self.messages[uid]

    def message_size(self, uid: int) -> int:
        return len(self.messages[uid])

    def fetch_rfc822(self, uid: int) -> bytes:
        return self.messages[uid]

    def select_folder(self, folder: str) -> int:
        return self.uidvalidity

    def close(self) -> None:
        return None


def test_mailru_app_password_variants():
    assert _password_variants(' "ab cd ef" ') == ["ab cd ef", "abcdef"]
    assert _password_variants("abcdef") == ["abcdef"]
    assert "пароль для внешних приложений" in _login_error(Exception("AUTHENTICATIONFAILED"))
    assert imap_since_token(date(2026, 1, 1)) == "01-Jan-2026"


def test_sync_skips_old_mail_and_purges_db(admin_client, app):
    with app.app_context():
        old = Inquiry(
            mailbox="kirovsvet@mail.ru",
            imap_uid=1,
            imap_uidvalidity=7,
            subject="Старое",
            received_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        )
        db.session.add(old)
        db.session.commit()
        result = InquiryService.sync(
            client=FakeMailbox(
                {
                    11: _sample_message(subject="Старое IMAP", date="Mon, 01 Mar 2025 10:00:00 +0300"),
                    12: _sample_message(subject="Новое"),
                }
            )
        )
        assert result.error is None
        assert result.purged == 1
        assert result.fetched == 1
        subjects = [row.subject for row in db.session.scalars(db.select(Inquiry))]
        assert subjects == ["Новое"]
        assert db.session.scalar(db.select(Inquiry).where(Inquiry.subject == "Старое")) is None


def test_parse_plain_and_attachment():
    parsed = parse_rfc822(_sample_message(with_file=True))
    assert parsed.from_email == "ivan@example.com"
    assert "Ленина" in (parsed.body_text or "")
    assert parsed.subject == "Свет не горит"
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].file_name == "zametka.txt"


def test_inquiries_page(admin_client):
    resp = admin_client.get("/inquiries/")
    assert resp.status_code == 200
    assert "Обращения".encode("utf-8") in resp.data
    assert b"kirovsvet@mail.ru" in resp.data
    assert "Загрузка писем".encode("utf-8") in resp.data


def test_inquiries_table_json(admin_client, app):
    with app.app_context():
        InquiryService.sync(
            client=FakeMailbox({11: _sample_message(subject="Первое")})
        )
    table = admin_client.get("/inquiries/table?q=Первое")
    assert table.status_code == 200
    payload = table.get_json()
    assert "Первое" in payload["table_html"]


def test_sync_fake_mailbox_creates_inquiry(admin_client, app):
    mailbox = FakeMailbox(
        {
            11: _sample_message(subject="Первое"),
            12: _sample_message(subject="Второе", with_file=True),
        }
    )
    with app.app_context():
        result = InquiryService.sync(client=mailbox)
        assert result.error is None
        assert result.fetched == 2
        rows = list(db.session.scalars(db.select(Inquiry).order_by(Inquiry.imap_uid)))
        assert [item.subject for item in rows] == ["Первое", "Второе"]
        files = list(db.session.scalars(db.select(Attachment)))
        assert len(files) == 1

        again = InquiryService.sync(client=FakeMailbox({11: _sample_message(), 12: _sample_message()}))
        assert again.fetched == 0

    listing = admin_client.get("/inquiries/table?q=Первое")
    assert listing.status_code == 200
    assert "Первое" in listing.get_json()["table_html"]

    with app.app_context():
        item = db.session.scalar(db.select(Inquiry).where(Inquiry.subject == "Второе"))
        files = InquiryService.attachments(item.id)
        assert files
        file_id = files[0].id
        page = admin_client.get(f"/inquiries/{item.id}")
        downloaded = admin_client.get(f"/inquiries/{item.id}/files/{file_id}")
        inline = admin_client.get(f"/inquiries/{item.id}/files/{file_id}?inline=1")
    assert page.status_code == 200
    assert "Ленина".encode("utf-8") in page.data
    assert b"zametka.txt" in page.data
    assert b"file-gallery" in page.data
    assert downloaded.status_code == 200
    assert downloaded.data
    assert inline.status_code == 200


def test_restore_missing_inquiry_files(admin_client, app):
    mailbox = FakeMailbox({12: _sample_message(subject="Файл", with_file=True)})
    with app.app_context():
        InquiryService.sync(client=mailbox)
        inquiry = db.session.scalar(db.select(Inquiry).where(Inquiry.subject == "Файл"))
        attachment = InquiryService.attachments(inquiry.id)[0]
        path = InquiryService.attachment_disk_path(attachment)
        assert path.is_file()
        path.unlink()
        inquiry_id = inquiry.id
        file_id = attachment.id

    missing = admin_client.get(f"/inquiries/{inquiry_id}/files/{file_id}")
    assert missing.status_code == 404

    with app.app_context():
        result = InquiryService.sync(client=mailbox)
        assert result.restored == 1
        assert InquiryService.attachment_disk_path(
            InquiryService.attachments(inquiry_id)[0]
        ).is_file()

    restored = admin_client.get(f"/inquiries/{inquiry_id}/files/{file_id}")
    assert restored.status_code == 200
    assert restored.data


def _login(client, email: str, password: str = "pass12345") -> None:
    client.get("/auth/logout", follow_redirects=True)
    resp = client.post(
        "/auth/login",
        data={"email": email, "password": password, "submit": "Войти"},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_forward_inquiry_to_executor_chat_and_scoped_list(admin_client, app):
    from app.models.auth.user import User
    from app.models.messenger.messenger_message import MessengerMessage

    with app.app_context():
        item = Inquiry(
            mailbox="kirovsvet@mail.ru",
            imap_uid=88,
            imap_uidvalidity=7,
            subject="Переслать это",
            from_name="Город",
            from_email="city@example.com",
            received_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
        db.session.add(item)
        db.session.commit()
        inquiry_id = item.id
        executor_id = db.session.scalar(db.select(User.id).where(User.email == "executor@test.local"))

    _login(admin_client, "executor@test.local")
    assert admin_client.get("/inquiries/").status_code == 200
    table = admin_client.get("/inquiries/table")
    assert table.status_code == 200
    assert "Переслать это" not in table.get_json()["table_html"]
    assert admin_client.get(f"/inquiries/{inquiry_id}").status_code == 404

    _login(admin_client, "dispatcher@test.local")
    forwarded = admin_client.post(
        f"/inquiries/{inquiry_id}/forward",
        json={"user_id": str(executor_id)},
    )
    assert forwarded.status_code == 200, forwarded.get_data(as_text=True)[:2000]
    payload = forwarded.get_json()
    assert payload["ok"] is True
    conversation_id = payload["conversation_id"]
    assert conversation_id
    assert "/messenger/" in payload["url"]

    messages = admin_client.get(f"/messenger/api/conversations/{conversation_id}/messages")
    assert messages.status_code == 200
    cards = [row["card"] for row in messages.get_json()["messages"] if row.get("card")]
    assert cards and cards[0]["type"] == "inquiry"
    assert "Переслать это" in cards[0]["title"]

    _login(admin_client, "executor@test.local")
    table = admin_client.get("/inquiries/table")
    html = table.get_json()["table_html"]
    assert "Переслать это" in html
    assert "Исполнитель QA" in html
    page = admin_client.get(f"/inquiries/{inquiry_id}")
    assert page.status_code == 200
    assert "Переслать это".encode("utf-8") in page.data

    attached = admin_client.post(
        f"/messenger/api/conversations/{conversation_id}/cards",
        json={"type": "inquiry", "id": str(inquiry_id)},
    )
    assert attached.status_code == 201, attached.get_data(as_text=True)[:2000]
    assert attached.get_json()["message"]["card"]["type"] == "inquiry"

    _login(admin_client, "master@test.local")
    assert admin_client.get(f"/inquiries/{inquiry_id}").status_code == 404
    master_table = admin_client.get("/inquiries/table").get_json()["table_html"]
    assert "Переслать это" not in master_table

    with app.app_context():
        stored = db.session.get(Inquiry, inquiry_id)
        assert stored.assigned_to == executor_id
        assert db.session.scalar(
            db.select(db.func.count())
            .select_from(MessengerMessage)
            .where(MessengerMessage.card_id == inquiry_id, MessengerMessage.card_type == "inquiry")
        ) == 2

"""Обращения: разбор писем и забор с ящика без сети."""

from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.extensions import db
from app.models.files.attachment import Attachment
from app.models.inquiries.inquiry import Inquiry
from app.modules.inquiries.imap_client import MailboxSnapshot, _login_error, _password_variants
from app.modules.inquiries.parse_email import parse_rfc822
from app.modules.inquiries.services import InquiryService


def _sample_message(*, subject: str = "Свет не горит", with_file: bool = False) -> bytes:
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
    message["Date"] = "Thu, 20 Aug 2026 10:00:00 +0300"
    return message.as_bytes()


class FakeMailbox:
    def __init__(self, messages: dict[int, bytes], uidvalidity: int = 7) -> None:
        self.messages = messages
        self.uidvalidity = uidvalidity

    def snapshot(self, folder: str, after_uid: int, limit: int) -> MailboxSnapshot:
        uids = [uid for uid in sorted(self.messages) if uid > after_uid][:limit]
        return MailboxSnapshot(uidvalidity=self.uidvalidity, uids=uids)

    def fetch_rfc822(self, uid: int) -> bytes:
        return self.messages[uid]

    def close(self) -> None:
        return None


def test_mailru_app_password_variants():
    assert _password_variants(' "ab cd ef" ') == ["ab cd ef", "abcdef"]
    assert _password_variants("abcdef") == ["abcdef"]
    assert "пароль для внешних приложений" in _login_error(Exception("AUTHENTICATIONFAILED"))


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
        page = admin_client.get(f"/inquiries/{item.id}")
    assert page.status_code == 200
    assert "Ленина".encode("utf-8") in page.data
    assert b"zametka.txt" in page.data

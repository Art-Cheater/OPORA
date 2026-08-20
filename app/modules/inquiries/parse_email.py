"""Разбор RFC822 письма во входящее обращение."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

_SPACE = re.compile(r"\s+")
_EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)


def _split_address(raw: str | None) -> tuple[str | None, str | None]:
    text = decode_header_value(raw) if raw else ""
    name, addr = parseaddr(text)
    if addr and "@" in addr and "<" not in addr:
        return (name or None), addr
    match = _EMAIL_RE.search(text)
    if match:
        email = match.group(0)
        leftover = text.replace(email, "").replace("<>", "").strip(" <>\"'")
        return (leftover or name or None), email
    return (name or text or None), (addr or None)


@dataclass
class ParsedAttachment:
    file_name: str
    mime_type: str
    payload: bytes


@dataclass
class ParsedMail:
    message_id: str | None
    from_name: str | None
    from_email: str | None
    to_email: str | None
    subject: str
    body_text: str | None
    body_html: str | None
    received_at: datetime | None
    attachments: list[ParsedAttachment] = field(default_factory=list)
    warning: str | None = None


class _HtmlToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self._chunks.append(text)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"p", "br", "div", "tr", "li", "h1", "h2", "h3"}:
            self._chunks.append("\n")

    def text(self) -> str:
        return _SPACE.sub(" ", " ".join(self._chunks)).strip()


def decode_header_value(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except Exception:
        return raw.strip()


def html_to_text(html: str) -> str:
    parser = _HtmlToText()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return _SPACE.sub(" ", re.sub(r"<[^>]+>", " ", html)).strip()
    return parser.text()


def _part_charset(part: Message) -> str:
    charset = part.get_content_charset() or "utf-8"
    return charset


def _decode_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        data = part.get_payload()
        return data if isinstance(data, str) else ""
    for encoding in (_part_charset(part), "utf-8", "cp1251", "latin-1"):
        try:
            return payload.decode(encoding, errors="replace")
        except LookupError:
            continue
    return payload.decode("utf-8", errors="replace")


def _safe_filename(name: str | None, index: int) -> str:
    text = decode_header_value(name) or f"file-{index}"
    text = text.replace("\\", "_").replace("/", "_").strip() or f"file-{index}"
    return text[:200]


def parse_header_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        received_at = parsedate_to_datetime(raw)
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        return received_at
    except (TypeError, ValueError, OverflowError, IndexError):
        return None


def parse_headers_only(raw: bytes) -> tuple[datetime | None, str, str | None, str | None]:
    """Дата, тема, from, Message-ID из заголовков без тела."""
    message: EmailMessage | Message = BytesParser(policy=policy.default).parsebytes(raw)
    received_at = parse_header_datetime(str(message.get("Date") or "") or None)
    subject = decode_header_value(message.get("Subject")) or "(без темы)"
    _name, from_email = _split_address(str(message.get("From") or ""))
    message_id = (message.get("Message-ID") or message.get("Message-Id") or "").strip() or None
    return received_at, subject[:1000], from_email, (message_id[:500] if message_id else None)


def parse_rfc822(raw: bytes) -> ParsedMail:
    message: EmailMessage | Message = BytesParser(policy=policy.default).parsebytes(raw)
    from_name, from_email = _split_address(str(message.get("From") or ""))
    to_raw = decode_header_value(str(message.get("To") or ""))
    subject = decode_header_value(message.get("Subject")) or "(без темы)"
    message_id = (message.get("Message-ID") or message.get("Message-Id") or "").strip() or None

    received_at = parse_header_datetime(str(message.get("Date") or "") or None)

    body_text = None
    body_html = None
    attachments: list[ParsedAttachment] = []
    part_index = 0

    parts = [message]
    if message.is_multipart():
        parts = list(message.walk())

    for part in parts:
        if part.is_multipart():
            continue
        disposition = str(part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        content_type = (part.get_content_type() or "application/octet-stream").lower()
        if disposition == "attachment" or (filename and content_type not in {"text/plain", "text/html"}):
            payload = part.get_payload(decode=True) or b""
            part_index += 1
            attachments.append(
                ParsedAttachment(
                    file_name=_safe_filename(filename, part_index),
                    mime_type=content_type[:100],
                    payload=payload,
                )
            )
            continue
        if content_type == "text/plain" and body_text is None:
            body_text = _decode_payload(part).strip() or None
        elif content_type == "text/html" and body_html is None:
            body_html = _decode_payload(part).strip() or None

    if not body_text and body_html:
        body_text = html_to_text(body_html) or None

    warning = None
    if not body_text and not attachments:
        warning = "Пустое письмо"

    return ParsedMail(
        message_id=message_id[:500] if message_id else None,
        from_name=(from_name or None),
        from_email=(from_email or None),
        to_email=(to_raw or None)[:1000] if to_raw else None,
        subject=subject[:1000],
        body_text=body_text[:100_000] if body_text else None,
        body_html=None,
        received_at=received_at,
        attachments=attachments,
        warning=warning,
    )

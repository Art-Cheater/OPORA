"""IMAP-клиент для mail.ru (и совместимых ящиков)."""

from __future__ import annotations

import imaplib
import ssl
from dataclasses import dataclass
from datetime import date, datetime

from app.modules.inquiries.parse_email import parse_header_datetime


@dataclass(frozen=True)
class MailboxSnapshot:
    uidvalidity: int
    uids: list[int]


class ImapError(RuntimeError):
    """Не удалось прочитать ящик."""


_IMAP_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_MAX_UIDS = 30000


def imap_since_token(value: date) -> str:
    """IMAP SINCE без локали: 01-Jan-2026."""
    return f"{value.day:02d}-{_IMAP_MONTHS[value.month - 1]}-{value.year}"


class ImapMailbox:
    def snapshot(
        self,
        folder: str,
        after_uid: int,
        limit: int,
        since: date | None = None,
    ) -> MailboxSnapshot:
        raise NotImplementedError

    def peek_headers(self, uid: int) -> bytes:
        return b""

    def message_size(self, uid: int) -> int:
        return 0

    def fetch_rfc822(self, uid: int) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        return None


class StdlibImapMailbox(ImapMailbox):
    def __init__(self, client: imaplib.IMAP4) -> None:
        self._client = client
        self._folder: str | None = None

    @classmethod
    def connect(cls, *, host: str, port: int, user: str, password: str) -> "StdlibImapMailbox":
        context = ssl.create_default_context()
        last_error: Exception | None = None
        client = None
        for secret in _password_variants(password):
            try:
                client = imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=30)
                client.login(user, secret)
                return cls(client)
            except Exception as exc:
                last_error = exc
                if client is not None:
                    try:
                        client.logout()
                    except Exception:
                        pass
                    client = None
        raise ImapError(_login_error(last_error)) from last_error

    def snapshot(
        self,
        folder: str,
        after_uid: int,
        limit: int,
        since: date | None = None,
    ) -> MailboxSnapshot:
        code, _ = self._client.select(folder, readonly=True)
        if code != "OK":
            raise ImapError(f"Папка {folder} недоступна.")
        self._folder = folder
        uidvalidity = 0
        typ, data = self._client.response("UIDVALIDITY")
        if data and data[0] not in (None, b""):
            try:
                uidvalidity = int(data[0])
            except (TypeError, ValueError):
                uidvalidity = 0
        terms: list[str] = []
        if after_uid > 0:
            terms.extend(["UID", f"{after_uid + 1}:*"])
        if since is not None:
            terms.extend(["SINCE", imap_since_token(since)])
        if not terms:
            raise ImapError("Поиск писем без даты запрещён: так можно уложить ящик.")
        code, payload = self._client.uid("SEARCH", None, *terms)
        if code != "OK":
            raise ImapError("Поиск писем не удался.")
        raw = payload[0] if payload else b""
        if not raw:
            return MailboxSnapshot(uidvalidity=uidvalidity, uids=[])
        uids = [int(part) for part in raw.split() if part.isdigit()]
        uids = [uid for uid in uids if uid > after_uid]
        if len(uids) > _MAX_UIDS:
            uids = uids[-_MAX_UIDS:]
        return MailboxSnapshot(uidvalidity=uidvalidity, uids=uids)

    def peek_headers(self, uid: int) -> bytes:
        code, payload = self._client.uid(
            "FETCH",
            str(uid),
            "(BODY.PEEK[HEADER.FIELDS (DATE FROM TO SUBJECT MESSAGE-ID)])",
        )
        if code != "OK" or not payload:
            return b""
        for item in payload:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                return bytes(item[1])
        return b""

    def message_size(self, uid: int) -> int:
        code, payload = self._client.uid("FETCH", str(uid), "(RFC822.SIZE)")
        if code != "OK" or not payload or payload[0] is None:
            return 0
        raw = payload[0]
        text = raw.decode("ascii", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        marker = "RFC822.SIZE"
        if marker in text:
            tail = text.split(marker, 1)[1]
            digits = "".join(ch for ch in tail if ch.isdigit() or ch == " ")
            try:
                return int(digits.split()[0])
            except (IndexError, ValueError):
                return 0
        return 0

    def fetch_rfc822(self, uid: int) -> bytes:
        code, payload = self._client.uid("FETCH", str(uid), "(BODY.PEEK[])")
        if code != "OK" or not payload or payload[0] is None:
            code, payload = self._client.uid("FETCH", str(uid), "(RFC822)")
        if code != "OK" or not payload or payload[0] is None:
            raise ImapError(f"Не удалось скачать письмо UID {uid}.")
        for item in payload:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                return bytes(item[1])
        raise ImapError(f"Пустой ответ IMAP для UID {uid}.")

    def close(self) -> None:
        try:
            self._client.logout()
        except Exception:
            try:
                self._client.shutdown()
            except Exception:
                pass


def connect_mailbox(*, host: str, port: int, user: str, password: str) -> ImapMailbox:
    return StdlibImapMailbox.connect(host=host, port=port, user=user, password=password)


def _password_variants(password: str) -> list[str]:
    text = (password or "").strip().strip('"').strip("'")
    variants = [text]
    compact = text.replace(" ", "")
    if compact and compact != text:
        variants.append(compact)
    return variants


def _login_error(exc: Exception | None) -> str:
    text = str(exc or "неизвестная ошибка")
    low = text.casefold()
    if "authentication" in low or "invalid credentials" in low or "auth" in low:
        return (
            "Mail.ru не принял пароль. Нужен пароль для внешних приложений "
            "(Система «Опора»), не основной пароль ящика. Логин — полный адрес kirovsvet@mail.ru."
        )
    return f"Вход в ящик не удался: {text}"

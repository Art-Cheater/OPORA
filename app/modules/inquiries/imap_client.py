"""IMAP-клиент для mail.ru (и совместимых ящиков)."""

from __future__ import annotations

import imaplib
import ssl
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class MailboxSnapshot:
    uidvalidity: int
    uids: list[int]


class ImapError(RuntimeError):
    """Не удалось прочитать ящик."""


class ImapMailbox:
    def snapshot(self, folder: str, after_uid: int, limit: int) -> MailboxSnapshot:
        raise NotImplementedError

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

    def snapshot(self, folder: str, after_uid: int, limit: int) -> MailboxSnapshot:
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
        if after_uid > 0:
            criteria = ("UID", f"{after_uid + 1}:*")
        else:
            criteria = ("UID", "1:*")
        code, payload = self._client.uid("SEARCH", None, *criteria)
        if code != "OK":
            raise ImapError("Поиск писем не удался.")
        raw = payload[0] if payload else b""
        if not raw:
            return MailboxSnapshot(uidvalidity=uidvalidity, uids=[])
        uids = [int(part) for part in raw.split() if part.isdigit()]
        uids = [uid for uid in uids if uid > after_uid]
        if limit > 0:
            uids = uids[:limit]
        return MailboxSnapshot(uidvalidity=uidvalidity, uids=uids)

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

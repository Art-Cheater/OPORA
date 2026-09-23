"""Server-side verification for the optional Cloudflare Turnstile challenge."""

from __future__ import annotations

import json
import socket
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app


class CaptchaVerdict:
    def __init__(self, ok: bool, code: str):
        self.ok = ok
        self.code = code


def captcha_message(code: str) -> str:
    return {
        "missing": "Подтвердите проверку, прежде чем войти.",
        "invalid": "Проверка не пройдена. Повторите попытку.",
        "timeout": "Сервис проверки не ответил вовремя. Повторите попытку. Вход без проверки невозможен.",
        "unavailable": "Сервис проверки временно недоступен. Вход без проверки невозможен.",
        "not_configured": "Проверка входа на сервере не настроена. Обратитесь к администратору.",
    }.get(code, "Не удалось подтвердить проверку. Повторите попытку.")


def verify_turnstile_result(token: str | None, remote_ip: str | None) -> CaptchaVerdict:
    """Проверка только ответом провайдера. С клиента флаг «проверка пройдена» не принимается."""

    if not current_app.config.get("CAPTCHA_ENABLED"):
        return CaptchaVerdict(True, "disabled")
    secret = current_app.config.get("TURNSTILE_SECRET_KEY", "")
    if not secret:
        return CaptchaVerdict(False, "not_configured")
    if not token:
        return CaptchaVerdict(False, "missing")
    payload = {"secret": secret, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip
    try:
        site_request = Request(
            current_app.config["TURNSTILE_VERIFY_URL"],
            data=urlencode(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(site_request, timeout=current_app.config["TURNSTILE_TIMEOUT_SECONDS"]) as response:  # nosec B310
            data = json.loads(response.read().decode("utf-8"))
    except (TimeoutError, socket.timeout):
        current_app.logger.warning("Turnstile verification timed out")
        return CaptchaVerdict(False, "timeout")
    except (URLError, OSError, ValueError, json.JSONDecodeError):
        current_app.logger.warning("Turnstile verification was unavailable")
        return CaptchaVerdict(False, "unavailable")
    if bool(data.get("success")):
        return CaptchaVerdict(True, "ok")
    current_app.logger.info("Turnstile verification rejected the token")
    return CaptchaVerdict(False, "invalid")


def verify_turnstile(token: str | None, remote_ip: str | None) -> bool:
    return verify_turnstile_result(token, remote_ip).ok

"""Server-side verification for the optional Cloudflare Turnstile challenge."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app


def verify_turnstile(token: str | None, remote_ip: str |None) -> bool:
    """Return True only after a successful provider response (fail closed)."""
    if not current_app.config.get("CAPTCHA_ENABLED"):
        return True
    secret = current_app.config.get("TURNSTILE_SECRET_KEY", "")
    if not token or not secret:
        return False
    payload = {"secret": secret, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip
    try:
        request = Request(
            current_app.config["TURNSTILE_VERIFY_URL"],
            data=urlencode(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(request, timeout=current_app.config["TURNSTILE_TIMEOUT_SECONDS"]) as response:  # nosec B310
            data = json.loads(response.read().decode("utf-8"))
        return bool(data.get("success"))
    except Exception:
        current_app.logger.warning("Turnstile verification was unavailable")
        return False

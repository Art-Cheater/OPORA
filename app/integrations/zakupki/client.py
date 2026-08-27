"""HTTP-клиент ЕИС: пауза между запросами, повтор при сбое."""

from __future__ import annotations

import os
import ssl
import time
import urllib.error
import urllib.request

from app.integrations.zakupki.config import USER_AGENT


class EisFetchError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        status: int | None = None,
        attempts: int = 0,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status = status
        self.attempts = attempts


def _ssl_context() -> ssl.SSLContext | None:
    """По умолчанию проверяем TLS. EIS_SSL_VERIFY=0 — только для сломанных корп. MITM."""
    if os.environ.get("EIS_SSL_VERIFY", "1").strip().lower() in {"0", "false", "no"}:
        return ssl._create_unverified_context()
    return ssl.create_default_context()


class EisClient:
    def __init__(self, delay: float = 1.2, timeout: int = 45, retries: int = 3) -> None:
        self.delay = delay
        self.timeout = timeout
        self.retries = max(1, min(int(retries), 5))
        self._last_request_at = 0.0
        self._context = _ssl_context()

    def get(self, url: str) -> str:
        last_error: Exception | None = None
        last_status: int | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                    "Connection": "close",
                },
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout, context=self._context
                ) as response:
                    status = getattr(response, "status", None) or response.getcode()
                    raw = response.read()
                if status and int(status) >= 400:
                    last_status = int(status)
                    raise EisFetchError(
                        f"HTTP {status}",
                        url=url,
                        status=last_status,
                        attempts=attempt,
                    )
                return raw.decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                last_error = exc
                last_status = int(exc.code)
                # 4xx кроме 408/429 обычно не ретраим бесконечно
                if exc.code in {403, 404, 410}:
                    short = url if len(url) <= 120 else f"{url[:117]}..."
                    raise EisFetchError(
                        f"Не удалось скачать {short}: HTTP {exc.code}",
                        url=url,
                        status=exc.code,
                        attempts=attempt,
                    ) from exc
                time.sleep(min(8.0, (0.8 * attempt) ** 1.5))
            except (urllib.error.URLError, TimeoutError, OSError, EisFetchError) as exc:
                last_error = exc
                if isinstance(exc, EisFetchError) and exc.status:
                    last_status = exc.status
                time.sleep(min(8.0, (0.8 * attempt) ** 1.5))
        short = url if len(url) <= 120 else f"{url[:117]}..."
        raise EisFetchError(
            f"Не удалось скачать {short}: {last_error}",
            url=url,
            status=last_status,
            attempts=self.retries,
        ) from last_error

    def _throttle(self) -> None:
        if self.delay <= 0:
            self._last_request_at = time.monotonic()
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self.delay - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

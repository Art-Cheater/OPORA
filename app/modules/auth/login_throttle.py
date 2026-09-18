"""Short-lived process-local throttle for login attempts.

Keys contain only SHA-256 digests of the IP, login and their pair. It is a
baseline for the single-web-service Compose deployment; a future multi-instance
deployment should replace it with shared Redis storage.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict, deque

from flask import current_app


class LoginThrottle:
    _lock = threading.Lock()
    _attempts: dict[str, deque[float]] = defaultdict(deque)
    _blocked_until: dict[str, float] = {}

    @staticmethod
    def _key(scope: str, value: str) -> str:
        return f"{scope}:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"

    @classmethod
    def _keys(cls, ip: str, email: str) -> tuple[str, str, str]:
        normalized = email.strip().lower()
        return cls._key("ip", ip or "unknown"), cls._key("login", normalized or "unknown"), cls._key("pair", f"{ip}|{normalized}")

    @classmethod
    def retry_after(cls, ip: str, email: str) -> int:
        now = time.monotonic()
        with cls._lock:
            until = max((cls._blocked_until.get(key, 0) for key in cls._keys(ip, email)), default=0)
        return max(0, int(until - now))

    @classmethod
    def record_failure(cls, ip: str, email: str) -> None:
        now = time.monotonic()
        with cls._lock:
            for key in cls._keys(ip, email):
                attempts = cls._attempts[key]
                while attempts and attempts[0] <= now - current_app.config["LOGIN_RATE_LIMIT_WINDOW_SECONDS"]:
                    attempts.popleft()
                attempts.append(now)
                if len(attempts) >= current_app.config["LOGIN_RATE_LIMIT_MAX_ATTEMPTS"]:
                    cls._blocked_until[key] = now + current_app.config["LOGIN_RATE_LIMIT_COOLDOWN_SECONDS"]
                    attempts.clear()

    @classmethod
    def clear_success(cls, ip: str, email: str) -> None:
        with cls._lock:
            for key in cls._keys(ip, email):
                cls._attempts.pop(key, None)
                cls._blocked_until.pop(key, None)

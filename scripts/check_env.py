#!/usr/bin/env python3
"""Validate an OPORA dotenv file without revealing its secrets."""

from __future__ import annotations

import re
import sys
from pathlib import Path


KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
ASSIGNMENT_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$")
EMBEDDED_ASSIGNMENT_RE = re.compile(r"\s+[A-Z_][A-Z0-9_]*=")
ADJACENT_ASSIGNMENT_RE = re.compile(r"[\"'][A-Z_][A-Z0-9_]*=")
SECRET_KEY_NAMES = {"SECRET_KEY", "POSTGRES_PASSWORD", "ADMIN_PASSWORD", "INQUIRY_IMAP_PASSWORD"}
INSECURE_SECRETS = {
    "",
    "dev-secret-key-change-in-production",
    "change-me-to-a-random-secret-key",
    "change-me-to-a-long-random-secret",
}
REQUIRED = {"ADMIN_EMAIL", "ADMIN_PASSWORD", "FLASK_ENV", "SECRET_KEY", "USE_SQLITE"}
POSTGRES_REQUIRED = {"POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"}


def _display_assignment(key: str, value: str) -> str:
    if key in SECRET_KEY_NAMES or "PASSWORD" in key or "SECRET" in key:
        return f"{key}=********"
    return f"{key}={value[:40]}" if value else f"{key}=<пусто>"


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def validate_env(path: Path) -> list[str]:
    """Return human-readable validation errors, always masking secret values."""
    errors: list[str] = []
    values: dict[str, str] = {}

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [f"Не удалось прочитать {path}: {exc}"]

    for number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = ASSIGNMENT_RE.match(line)
        if not match:
            errors.append(f"Строка {number}: ожидается формат KEY=value.")
            continue

        key, raw_value = match.groups()
        if not KEY_RE.fullmatch(key):
            errors.append(f"Строка {number}: недопустимое имя переменной {key!r}.")
            continue
        if EMBEDDED_ASSIGNMENT_RE.search(raw_value) or ADJACENT_ASSIGNMENT_RE.search(raw_value):
            shown = _display_assignment(key, "" if key in SECRET_KEY_NAMES else "<скрыто>")
            errors.append(
                f"Строка {number} ({shown}): похоже, несколько переменных записаны в одну строку."
            )
            continue
        shown = _display_assignment(key, raw_value)
        if raw_value.count('"') % 2 or raw_value.count("'") % 2:
            errors.append(f"Строка {number} ({shown}): несбалансированные кавычки.")
            continue
        values[key] = _unquote(raw_value)

    missing = sorted(name for name in REQUIRED if not values.get(name, "").strip())
    if missing:
        errors.append("Отсутствуют обязательные отдельные переменные: " + ", ".join(missing) + ".")

    secret = values.get("SECRET_KEY", "").strip()
    if secret in INSECURE_SECRETS or secret.lower().startswith(("change-me", "dev-secret")) or len(secret) < 32:
        errors.append("SECRET_KEY должен быть отдельным, непустым, не стандартным и длиной не менее 32 символов.")

    if values.get("FLASK_ENV") != "production":
        errors.append("FLASK_ENV должен быть ровно production.")
    if values.get("USE_SQLITE") != "0":
        errors.append("USE_SQLITE должен быть равен 0 в production.")
    if values.get("GUNICORN_CMD_ARGS", "").strip():
        errors.append("GUNICORN_CMD_ARGS должен отсутствовать или быть пустым: command line задаёт entrypoint.")

    if not values.get("DATABASE_URL", "").strip():
        missing_postgres = sorted(name for name in POSTGRES_REQUIRED if not values.get(name, "").strip())
        if missing_postgres:
            errors.append("Нужен DATABASE_URL либо полный набор PostgreSQL: " + ", ".join(missing_postgres) + ".")
    elif not values.get("POSTGRES_PASSWORD", "").strip():
        errors.append("POSTGRES_PASSWORD должен существовать отдельной переменной.")

    return errors


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path(".env")
    if not path.is_file():
        print(f"Ошибка .env: файл не найден: {path}", file=sys.stderr)
        return 1
    errors = validate_env(path)
    if errors:
        print("Ошибка .env: похоже, несколько переменных записаны в одну строку. Каждая переменная должна быть отдельной строкой KEY=value.", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"OK: {path} прошёл production pre-flight.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

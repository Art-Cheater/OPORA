"""Утилиты безопасности — хеширование паролей через bcrypt."""

import bcrypt

BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """Хеширует пароль с использованием bcrypt."""
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Проверяет пароль против bcrypt-хеша."""
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False

"""Базовые исключения приложения."""


class OporaException(Exception):
    """Базовое исключение системы «Опора»."""

    def __init__(self, message: str = "Произошла ошибка"):
        self.message = message
        super().__init__(self.message)


class AuthenticationError(OporaException):
    """Ошибка аутентификации."""


class AuthorizationError(OporaException):
    """Ошибка авторизации — недостаточно прав."""


class NotFoundError(OporaException):
    """Сущность не найдена."""


class ValidationError(OporaException):
    """Ошибка валидации данных."""

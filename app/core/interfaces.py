"""Абстрактные интерфейсы (Protocol) для соблюдения DIP."""

from typing import Protocol, TypeVar

T = TypeVar("T")


class Repository(Protocol[T]):
    """Базовый контракт репозитория."""

    def get_by_id(self, entity_id: int) -> T | None: ...

    def get_all(self) -> list[T]: ...

    def save(self, entity: T) -> T: ...

    def delete(self, entity: T) -> None: ...

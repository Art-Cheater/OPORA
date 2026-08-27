"""Модель системных обоев интерфейса (каталог админа)."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String

from app.models.base import BaseModel
from sqlalchemy.orm import Mapped, mapped_column


class Wallpaper(BaseModel):
    """Обои, доступные всем пользователям для выбора фона."""

    __tablename__ = "wallpapers"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="image/jpeg")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<Wallpaper {self.title!r}>"

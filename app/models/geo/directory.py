"""Импортируемый адресный справочник. Ручной список улиц Кирова его не заменяет."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel
from app.models.types import GUID, JSONType


class GeoSettlement(BaseModel):
    __tablename__ = "geo_settlements"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_geo_settlements_source_ext"),
        Index("ix_geo_settlements_name_key", "name_key"),
    )

    source: Mapped[str] = mapped_column(String(32), nullable=False, default="import")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="settlement")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_key: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("geo_settlements.id", ondelete="SET NULL"), nullable=True
    )
    region_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    district_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fias_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    osm_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)


class GeoStreet(BaseModel):
    __tablename__ = "geo_streets"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_geo_streets_source_ext"),
        Index("ix_geo_streets_name_key", "name_key"),
    )

    source: Mapped[str] = mapped_column(String(32), nullable=False, default="import")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("geo_settlements.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_key: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="улица")
    settlement_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    district_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    region_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fias_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    osm_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class GeoHouse(BaseModel):
    __tablename__ = "geo_houses"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_geo_houses_source_ext"),
        Index("ix_geo_houses_street_number", "street_id", "number_key"),
    )

    source: Mapped[str] = mapped_column(String(32), nullable=False, default="import")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    street_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("geo_streets.id", ondelete="SET NULL"), nullable=True
    )
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    number_key: Mapped[str] = mapped_column(String(32), nullable=False)
    building: Mapped[str | None] = mapped_column(String(32), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    structure: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fias_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    osm_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)


class GeoEntrance(BaseModel):
    """Физический вход в здание. Это не точка, куда маршрутизатор подъезжает на автомобиле."""

    __tablename__ = "geo_entrances"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_geo_entrances_source_ext"),
        Index("ix_geo_entrances_lat_lng", "latitude", "longitude"),
    )

    source: Mapped[str] = mapped_column(String(32), nullable=False, default="import")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    house_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("geo_houses.id", ondelete="SET NULL"), nullable=True
    )
    ref: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entrance_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    building_osm_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    settlement_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    street_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    house_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    osm_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class GeoGeocodeCache(BaseModel):
    __tablename__ = "geo_geocode_cache"
    __table_args__ = (UniqueConstraint("cache_key", name="uq_geo_geocode_cache_key"),)

    cache_key: Mapped[str] = mapped_column(String(400), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[list | None] = mapped_column(JSONType, nullable=True)

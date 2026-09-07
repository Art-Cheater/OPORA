"""Создание и синхронизация дополнительных точек без изменения raw address."""
from __future__ import annotations
from decimal import Decimal
from app.extensions import db
from app.models.maps.work_map_point import WorkMapPoint
from app.core.address.map_points import split_map_address_parts


class WorkMapPointService:
    @classmethod
    def sync(cls, entity, entity_type: str, geocode, user_id=None):
        manual = getattr(entity, "coordinates_source", None) == "manual"
        existing = list(db.session.scalars(db.select(WorkMapPoint).where(WorkMapPoint.entity_type == entity_type, WorkMapPoint.entity_id == entity.id, WorkMapPoint.active_filter()).order_by(WorkMapPoint.sequence)))
        if manual and entity.latitude is not None and entity.longitude is not None:
            for point in existing: point.is_primary = False
            point = next((row for row in existing if row.source == "manual"), None)
            if point is None:
                point = WorkMapPoint(entity_type=entity_type, entity_id=entity.id, address_part=entity.address, latitude=entity.latitude, longitude=entity.longitude, source="manual", confidence="exact_house", sequence=0, is_primary=True, created_by=user_id, updated_by=user_id); db.session.add(point)
            else:
                point.latitude, point.longitude, point.address_part, point.is_primary = entity.latitude, entity.longitude, entity.address, True
            return
        for point in existing:
            if point.source != "manual": point.soft_delete(user_id)
        parts, _warning = split_map_address_parts(entity.normalized_address or entity.address or "")
        created = []
        for sequence, part in enumerate(parts, 1):
            coords = geocode(part)
            if not coords: continue
            latitude, longitude = coords
            street_only = not any(char.isdigit() for char in part)
            point = WorkMapPoint(entity_type=entity_type, entity_id=entity.id, address_part=part, latitude=latitude, longitude=longitude, source="geocoder_street" if street_only else ("range_expanded" if len(parts) > 1 else "geocoder_house"), confidence="street_only" if street_only else "exact_house", sequence=sequence, is_primary=False, created_by=user_id, updated_by=user_id)
            db.session.add(point); created.append(point)
        if created:
            primary = created[0]; primary.is_primary = True
            entity.latitude, entity.longitude = primary.latitude, primary.longitude
            entity.coordinates_source = "geocoder"
        elif entity.latitude is not None and entity.longitude is not None:
            db.session.add(WorkMapPoint(entity_type=entity_type, entity_id=entity.id, address_part=entity.address, latitude=entity.latitude, longitude=entity.longitude, source=getattr(entity, "coordinates_source", None) or "unknown", confidence="approximate", sequence=1, is_primary=True, created_by=user_id, updated_by=user_id))

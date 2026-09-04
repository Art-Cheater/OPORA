"""Nearby-поиск: приоритеты SQL, статусы не меняются."""

from __future__ import annotations

from decimal import Decimal

from app.core.nearby import (
    PRIORITY_ADDRESS,
    PRIORITY_DISTRICT,
    PRIORITY_GEO,
    PRIORITY_STREET,
    NearbySearchService,
)
from app.extensions import db
from app.models.defects.defect import Defect
from app.models.defects.defect_category import DefectCategory
from app.models.defects.defect_status import DefectStatus
from app.models.enums import Priority
from app.modules.requests.address_format import normalize_address
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.modules.requests.repositories import RequestRepository


def _new_status():
    return db.session.scalar(db.select(RequestStatus).where(RequestStatus.code == "new"))


def _completed_status():
    return db.session.scalar(db.select(RequestStatus).where(RequestStatus.code == "completed"))


def _open_defect_status():
    return db.session.scalar(db.select(DefectStatus).where(DefectStatus.code == "open"))


def _category():
    return db.session.scalar(db.select(DefectCategory).where(DefectCategory.code == "other"))


def test_nearby_priority_and_does_not_change_status(app):
    with app.app_context():
        journal_id = RequestRepository.get_default_journal().id
        st_new = _new_status()
        st_done = _completed_status()
        d_open = _open_defect_status()
        category = _category()

        same_addr = Request(
            number="NB-1",
            title="Тот же адрес",
            address="улица Мира, 10",
            normalized_address=normalize_address("улица Мира, 10"),
            street="улица Мира",
            district="Ленинский",
            applicant_name="QA",
            priority=Priority.MEDIUM.value,
            status_id=st_new.id,
            journal_id=journal_id,
            latitude=Decimal("58.6035"),
            longitude=Decimal("49.6680"),
        )
        same_street = Request(
            number="NB-2",
            title="Та же улица",
            address="улица Мира, 20",
            normalized_address=normalize_address("улица Мира, 20"),
            street="улица Мира",
            district="Ленинский",
            applicant_name="QA",
            priority=Priority.MEDIUM.value,
            status_id=st_new.id,
            journal_id=journal_id,
        )
        same_district = Request(
            number="NB-3",
            title="Тот же район",
            address="улица Дружбы, 1",
            normalized_address=normalize_address("улица Дружбы, 1"),
            street="улица Дружбы",
            district="Ленинский",
            applicant_name="QA",
            priority=Priority.MEDIUM.value,
            status_id=st_new.id,
            journal_id=journal_id,
        )
        geo = Defect(
            number="DF-NB-1",
            description="Рядом по координатам",
            address="рядом",
            street="улица Лесная",
            district="Октябрьский",
            status_id=d_open.id,
            category_id=category.id,
            latitude=Decimal("58.6040"),
            longitude=Decimal("49.6685"),
        )
        closed = Request(
            number="NB-X",
            title="Закрытая",
            address="улица Мира, 10",
            normalized_address=normalize_address("улица Мира, 10"),
            street="улица Мира",
            district="Ленинский",
            applicant_name="QA",
            priority=Priority.MEDIUM.value,
            status_id=st_done.id,
            journal_id=journal_id,
        )
        db.session.add_all([same_addr, same_street, same_district, geo, closed])
        db.session.commit()
        before = {same_addr.status_id, same_street.status_id, same_district.status_id, geo.status_id, closed.status_id}

        hits = NearbySearchService.suggest(
            address="улица Мира, 10",
            street="улица Мира",
            district="Ленинский",
            latitude=Decimal("58.6035"),
            longitude=Decimal("49.6680"),
        )
        by_id = {(h.entity_type, str(h.entity_id)): h for h in hits}
        assert ("request", str(same_addr.id)) in by_id
        assert by_id[("request", str(same_addr.id))].priority == PRIORITY_ADDRESS
        assert by_id[("request", str(same_street.id))].priority == PRIORITY_STREET
        # Район без координат не является достаточным критерием nearby.
        assert ("request", str(same_district.id)) not in by_id
        assert ("defect", str(geo.id)) in by_id
        assert by_id[("defect", str(geo.id))].priority == PRIORITY_GEO
        assert ("request", str(closed.id)) not in by_id

        db.session.refresh(same_addr)
        db.session.refresh(geo)
        db.session.refresh(closed)
        after = {same_addr.status_id, same_street.status_id, same_district.status_id, geo.status_id, closed.status_id}
        assert before == after
        summary = NearbySearchService.summarize(hits)
        assert "заявок" in summary
        assert "дефект" in summary

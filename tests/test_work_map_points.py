from decimal import Decimal
from app.extensions import db
from app.models.maps.work_map_point import WorkMapPoint
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.models.requests.request_journal import RequestJournal
from app.modules.work_orders.services import WorkOrderFilter, WorkOrderService


def test_request_map_json_expands_active_map_points(admin_client, app):
    with app.app_context():
        status = db.session.scalar(db.select(RequestStatus).where(RequestStatus.code == "new"))
        journal = db.session.scalar(db.select(RequestJournal).where(RequestJournal.deleted_at.is_(None)))
        req = Request(number="26-9901", title="multi", address="Даниловский проезд 7, 9", applicant_name="QA", priority="medium", status_id=status.id, journal_id=journal.id, latitude=Decimal("58.60"), longitude=Decimal("49.67"))
        db.session.add(req); db.session.flush()
        db.session.add_all([WorkMapPoint(entity_type="request", entity_id=req.id, address_part="Даниловский проезд, дом 7", latitude=Decimal("58.6000000"), longitude=Decimal("49.6700000"), source="multi_address", confidence="exact_house", sequence=1, is_primary=True), WorkMapPoint(entity_type="request", entity_id=req.id, address_part="Даниловский проезд, дом 9", latitude=Decimal("58.6010000"), longitude=Decimal("49.6710000"), source="multi_address", confidence="exact_house", sequence=2, is_primary=False)])
        db.session.commit(); request_id = str(req.id)
    points = [row for row in admin_client.get("/requests/map.json").get_json()["points"] if row.get("entity_id") == request_id]
    assert len(points) == 2
    assert all(row["url"].endswith(request_id) and row["point_count"] == 2 for row in points)


def test_work_orders_use_all_entity_map_points_and_keep_entity_id(app):
    with app.app_context():
        status = db.session.scalar(db.select(RequestStatus).where(RequestStatus.code == "new"))
        journal = db.session.scalar(db.select(RequestJournal).where(RequestJournal.deleted_at.is_(None)))
        req = Request(number="26-9902", title="multi", address="Лесная 7, 9", applicant_name="QA", priority="medium", status_id=status.id, journal_id=journal.id, latitude=Decimal("58.61"), longitude=Decimal("49.68"))
        db.session.add(req); db.session.flush()
        db.session.add_all([
            WorkMapPoint(entity_type="request", entity_id=req.id, address_part="Лесная, дом 7", latitude=Decimal("58.6100000"), longitude=Decimal("49.6800000"), source="range_expanded", confidence="exact_house", sequence=1, is_primary=True),
            WorkMapPoint(entity_type="request", entity_id=req.id, address_part="Лесная, дом 9", latitude=Decimal("58.6110000"), longitude=Decimal("49.6810000"), source="range_expanded", confidence="exact_house", sequence=2, is_primary=False),
        ])
        db.session.commit()
        points = [row for row in WorkOrderService.map_points(WorkOrderFilter(), None) if row.get("entity_id") == str(req.id)]
    assert len(points) == 2
    assert all(row["id"] != row["entity_id"] and row["entity_id"] == str(req.id) for row in points)

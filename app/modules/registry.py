"""Реестр модулей — централизованная регистрация Blueprint."""

from flask import Flask

from app.modules.agreements import agreements_bp
from app.modules.auth import auth_bp
from app.modules.contracts import contracts_bp
from app.modules.contractors import contractors_bp
from app.modules.defects import defects_bp
from app.modules.documents import documents_bp
from app.modules.eis import eis_bp
from app.modules.employees import employees_bp
from app.modules.field_builder import field_builder_bp
from app.modules.inquiries import inquiries_bp
from app.modules.main import main_bp
from app.modules.objects import objects_bp
from app.modules.positions import positions_bp
from app.modules.roles import roles_bp
from app.modules.messenger import messenger_bp
from app.modules.notifications import notifications_bp
from app.modules.projects import projects_bp
from app.modules.requests import requests_bp
from app.modules.reports import reports_bp
from app.modules.waybills import waybills_bp
from app.modules.search import search_bp
from app.modules.tenders import tenders_bp
from app.modules.wallpapers import wallpapers_bp
from app.modules.audit import audit_bp

# Список всех модулей системы.
ALL_BLUEPRINTS = [
    main_bp,
    auth_bp,
    requests_bp,
    defects_bp,
    waybills_bp,
    objects_bp,
    projects_bp,
    tenders_bp,
    contracts_bp,
    contractors_bp,
    agreements_bp,
    inquiries_bp,
    eis_bp,
    employees_bp,
    positions_bp,
    roles_bp,
    field_builder_bp,
    wallpapers_bp,
    messenger_bp,
    documents_bp,
    notifications_bp,
    search_bp,
    audit_bp,
    reports_bp,
]


def register_blueprints(app: Flask) -> None:
    """Регистрирует все Blueprint-модули в приложении."""
    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

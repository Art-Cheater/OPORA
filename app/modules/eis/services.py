"""Импорт данных ЕИС в Опору: матчинг адреса и достройка цепочки."""

from __future__ import annotations

import uuid
from datetime import timedelta, timezone
from decimal import Decimal

from flask import current_app
from sqlalchemy.orm.attributes import flag_modified

from app.extensions import db
from app.integrations.zakupki.parse import keep_eis_listing, order_object_names
from app.integrations.zakupki.models import EisContract, EisOrder, EisSupplier
from app.integrations.zakupki.runner import EisParseResult, EisParser
from app.models.base import utcnow
from app.models.contracts.contract import Contract
from app.models.contracts.contract_contractor import ContractContractor
from app.models.contracts.contract_object import ContractObject
from app.models.eis.eis_import_event import EisImportEvent
from app.models.eis.eis_import_run import EisImportRun
from app.models.enums import (
    ContractStatus,
    ContractType,
    ProjectStatus,
    TenderApplicationStatus,
    WorkObjectStatus,
)
from app.models.projects.project import Project
from app.models.tenders.tender_application import TenderApplication
from app.models.tenders.tender_project import TenderProject
from app.models.work_objects.work_object import WorkObject
from app.modules.contractors.repositories import ContractorRepository
from app.modules.contractors.services import ContractorService
from app.modules.eis.matching import match_work_objects
from app.modules.objects.services import ObjectService
from app.modules.projects.repositories import ProjectRepository
from app.modules.tenders.services import TenderPayload, TenderService


class EisSyncLocked(RuntimeError):
    """Уже идёт другой прогон."""


def map_tender_status(eis_status: str | None) -> str:
    text = (eis_status or "").casefold()
    if "отмен" in text:
        return TenderApplicationStatus.CANCELLED.value
    if "завершен" in text or "заключен" in text:
        return TenderApplicationStatus.WON.value
    if text:
        return TenderApplicationStatus.SUBMITTED.value
    return TenderApplicationStatus.DRAFT.value


def map_contract_status(eis_stage: str | None, current: str | None) -> str | None:
    """None — не трогать внутренний workflow."""
    text = (eis_stage or "").casefold()
    busy = {
        ContractStatus.WORK_DOCS_PENDING.value,
        ContractStatus.IN_PROGRESS.value,
        ContractStatus.KS2_PENDING.value,
        ContractStatus.REJECTED.value,
    }
    if current in busy:
        if "расторг" in text:
            return ContractStatus.TERMINATED.value
        if "завершен" in text or "исполнение завершено" in text:
            return ContractStatus.COMPLETED.value
        return None
    if "расторг" in text:
        return ContractStatus.TERMINATED.value
    if "завершен" in text:
        return ContractStatus.COMPLETED.value
    if text:
        return ContractStatus.ACTIVE.value
    return None


class EisImportService:
    def __init__(self, parser: EisParser | None = None) -> None:
        self.parser = parser or EisParser()

    def is_running(self) -> EisImportRun | None:
        stale_min = int(current_app.config.get("EIS_SYNC_STALE_MINUTES", 120))
        cutoff = utcnow() - timedelta(minutes=stale_min)
        running = list(
            db.session.scalars(
                db.select(EisImportRun).where(
                    EisImportRun.status == "running",
                    EisImportRun.active_filter(),
                )
            )
        )
        live = None
        changed = False
        for item in running:
            started = item.started_at
            if started is not None and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if started is None or started < cutoff:
                item.status = "error"
                item.finished_at = utcnow()
                item.error_message = "Прогон прерван по таймауту"
                changed = True
            else:
                live = item
        if changed:
            db.session.commit()
        return live

    def sync(
        self,
        *,
        trigger: str = "manual",
        user_id: uuid.UUID | None = None,
        parse_result: EisParseResult | None = None,
        pages: int | None = None,
        per_page: str | None = None,
        delay: float | None = None,
    ) -> EisImportRun:
        live = self.is_running()
        if live is not None:
            raise EisSyncLocked("Импорт ЕИС уже выполняется.")

        run = EisImportRun(
            trigger=trigger,
            status="running",
            user_id=user_id,
            started_at=utcnow(),
            created_by=user_id,
            updated_by=user_id,
            summary={
                "created_projects": 0,
                "created_tenders": 0,
                "updated_tenders": 0,
                "created_contracts": 0,
                "updated_contracts": 0,
                "created_contractors": 0,
                "unmatched": 0,
                "errors": 0,
                "skipped_old": 0,
            },
        )
        db.session.add(run)
        db.session.commit()

        try:
            result = parse_result
            if result is None:
                cfg = current_app.config
                if delay is not None:
                    self.parser.client.delay = delay
                result = self.parser.run(
                    mode="both",
                    pages=pages or int(cfg.get("EIS_SYNC_PAGES", 20)),
                    limit=None,
                    per_page=per_page or cfg.get("EIS_SYNC_PER_PAGE", "_50"),
                    with_contracts=True,
                    year_from=int(cfg.get("EIS_YEAR_FROM", 2024)),
                    year_to=int(cfg.get("EIS_YEAR_TO", 2100)),
                )
            objects = list(
                db.session.scalars(
                    db.select(WorkObject).where(WorkObject.active_filter())
                )
            )
            for issue in result.issues:
                self._event(
                    run,
                    kind="error",
                    message=issue.message,
                    eis_number=issue.number,
                    url=issue.url,
                    entity_type="fetch",
                )
                self._bump(run, "errors")
            if result.skipped_old:
                run.summary["skipped_old"] = int(run.summary.get("skipped_old") or 0) + int(
                    result.skipped_old
                )
                flag_modified(run, "summary")
            db.session.commit()
            for order in result.orders:
                if self._out_of_year_range(order.reg_number, order.published_at):
                    self._bump(run, "skipped_old")
                    continue
                try:
                    self._sync_order(run, order, objects, user_id)
                except Exception as exc:
                    self._recover_run_error(run, exc, order.reg_number, order.url, "tender")
                    run = db.session.get(EisImportRun, run.id) or run
                    objects = list(
                        db.session.scalars(
                            db.select(WorkObject).where(WorkObject.active_filter())
                        )
                    )
            for contract in result.contracts:
                if self._out_of_year_range(contract.reestr_number, contract.contract_date):
                    self._bump(run, "skipped_old")
                    continue
                try:
                    self._sync_contract(run, contract, objects, user_id, tender=None)
                except Exception as exc:
                    self._recover_run_error(run, exc, contract.reestr_number, contract.url, "contract")
                    run = db.session.get(EisImportRun, run.id) or run
                    objects = list(
                        db.session.scalars(
                            db.select(WorkObject).where(WorkObject.active_filter())
                        )
                    )
            run = db.session.get(EisImportRun, run.id) or run
            run.status = "success"
            run.finished_at = utcnow()
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            run = db.session.get(EisImportRun, run.id) or run
            run.status = "error"
            run.finished_at = utcnow()
            run.error_message = str(exc)[:2000]
            db.session.add(run)
            db.session.commit()
            raise
        return run

    def _recover_run_error(
        self,
        run: EisImportRun,
        exc: Exception,
        number: str | None,
        url: str | None,
        entity_type: str,
    ) -> None:
        db.session.rollback()
        run = db.session.get(EisImportRun, run.id)
        if run is None:
            return
        if run.summary is None:
            run.summary = {}
        run.summary["errors"] = int(run.summary.get("errors") or 0) + 1
        self._event(
            run,
            kind="error",
            message=str(exc)[:2000],
            eis_number=number,
            url=url,
            entity_type=entity_type,
        )
        db.session.commit()

    def _bump(self, run: EisImportRun, key: str) -> None:
        summary = dict(run.summary or {})
        summary[key] = int(summary.get(key) or 0) + 1
        run.summary = summary
        flag_modified(run, "summary")

    def _year_bounds(self) -> tuple[int, int]:
        cfg = current_app.config
        return int(cfg.get("EIS_YEAR_FROM", 2024)), int(cfg.get("EIS_YEAR_TO", 2100))

    def _out_of_year_range(self, number: str | None, listed_date=None) -> bool:
        year_from, year_to = self._year_bounds()
        return not keep_eis_listing(number, listed_date, year_from, year_to)

    def _event(
        self,
        run: EisImportRun,
        *,
        kind: str,
        message: str,
        eis_number: str | None = None,
        url: str | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        extra: dict | None = None,
        user_id: uuid.UUID | None = None,
    ) -> None:
        db.session.add(
            EisImportEvent(
                run_id=run.id,
                kind=kind,
                message=message,
                eis_number=eis_number,
                url=url,
                entity_type=entity_type,
                entity_id=entity_id,
                extra=extra,
                created_by=user_id,
                updated_by=user_id,
            )
        )

    def _sync_order(
        self,
        run: EisImportRun,
        order: EisOrder,
        objects: list[WorkObject],
        user_id: uuid.UUID | None,
    ) -> None:
        names = order_object_names(order)
        matched: list[tuple[str, WorkObject]] = []
        seen_ids: set[uuid.UUID] = set()
        if not names:
            self._event(
                run,
                kind="unmatched",
                message="В извещении нет таблицы объектов закупки",
                eis_number=order.reg_number,
                url=order.url,
                entity_type="tender",
                extra={"object_title": order.object_title, "status": order.status},
                user_id=user_id,
            )
            self._bump(run, "unmatched")
            db.session.commit()
            return

        for name in names:
            hit = match_work_objects([name], objects)
            if hit.work_object is None:
                self._event(
                    run,
                    kind="unmatched",
                    message=f"{hit.reason}: {name}",
                    eis_number=order.reg_number,
                    url=order.url,
                    entity_type="tender",
                    extra={"purchase_object": name, "status": order.status},
                    user_id=user_id,
                )
                self._bump(run, "unmatched")
                continue
            if hit.work_object.id in seen_ids:
                continue
            seen_ids.add(hit.work_object.id)
            matched.append((name, hit.work_object))

        if not matched:
            db.session.commit()
            return

        projects: list[Project] = []
        for name, obj in matched:
            projects.append(self._ensure_project(run, obj, name, user_id))
            if order.nmck is not None and len(matched) == 1:
                obj.budget_amount = order.nmck

        primary_obj = matched[0][1]
        primary_project = projects[0]
        tender, created = self._ensure_tender(
            run, primary_obj, primary_project, order, user_id, extra_projects=projects[1:]
        )
        if created:
            self._bump(run, "created_tenders")
            kind = "created"
        else:
            self._bump(run, "updated_tenders")
            kind = "updated"
        self._event(
            run,
            kind=kind,
            message=f"Заявка {tender.number}: {tender.status} ({len(matched)} объект.)",
            eis_number=order.reg_number,
            url=order.url,
            entity_type="tender",
            entity_id=tender.id,
            extra={"objects": [name for name, _ in matched]},
            user_id=user_id,
        )
        if map_tender_status(order.status) == TenderApplicationStatus.WON.value:
            linked = [item[1] for item in matched]
            for eis_contract in order.contracts:
                if self._out_of_year_range(eis_contract.reestr_number, eis_contract.contract_date):
                    self._bump(run, "skipped_old")
                    continue
                self._sync_contract(
                    run, eis_contract, objects, user_id, tender=tender, obj=primary_obj
                )
                saved = self._find_contract(eis_contract)
                if saved is not None:
                    for extra in linked[1:]:
                        ContractServiceLink.ensure_object(saved, extra, user_id)
                    db.session.commit()
        db.session.commit()

    def _ensure_project(
        self,
        run: EisImportRun,
        obj: WorkObject,
        title: str | None,
        user_id: uuid.UUID | None,
    ) -> Project:
        project = ObjectService._active_project(obj)
        if project is not None:
            return project
        project = Project(
            code=ProjectRepository.next_code(),
            name=(title or obj.display_address or obj.name)[:500],
            description=title,
            status=ProjectStatus.ACTIVE.value,
            progress_percent=0,
            object_id=obj.id,
            manager_id=user_id,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(project)
        db.session.flush()
        if obj.status == WorkObjectStatus.FREE.value:
            obj.status = WorkObjectStatus.IN_PROJECT.value
            obj.updated_by = user_id
        self._bump(run, "created_projects")
        self._event(
            run,
            kind="created",
            message=f"Проект {project.code} для {obj.display_address}",
            entity_type="project",
            entity_id=project.id,
            user_id=user_id,
        )
        return project

    def _ensure_tender(
        self,
        run: EisImportRun,
        obj: WorkObject,
        project: Project,
        order: EisOrder,
        user_id: uuid.UUID | None,
        extra_projects: list[Project] | None = None,
    ) -> tuple[TenderApplication, bool]:
        tender = db.session.scalar(
            db.select(TenderApplication).where(
                TenderApplication.eis_reg_number == order.reg_number,
                TenderApplication.active_filter(),
            )
        )
        created = False
        status = map_tender_status(order.status)
        if tender is None:
            tender = ObjectService._active_tender(obj, project)
            if tender is not None and tender.eis_reg_number:
                tender = None
        if tender is None:
            if user_id is None:
                raise RuntimeError("Для создания заявки нужен пользователь аудита.")
            tender = TenderService.create(
                TenderPayload(
                    number=order.reg_number[:50],
                    title=(order.object_title or obj.display_address or order.reg_number)[:500],
                    description=order.object_title,
                    status=status,
                    responsible_id=user_id,
                    project_ids=[project.id],
                    object_id=obj.id,
                    published_at=order.published_at,
                ),
                user_id,
                commit=False,
            )
            created = True
        else:
            tender.status = status
            tender.title = (order.object_title or tender.title)[:500]
            tender.published_at = order.published_at or tender.published_at
            tender.updated_by = user_id
            if user_id is not None:
                TenderService._apply_status_side_effects(tender, user_id)
        tender.eis_reg_number = order.reg_number
        tender.eis_status = order.status
        tender.eis_url = order.url
        tender.nmck = order.nmck
        if extra_projects and user_id is not None:
            self._add_tender_projects(tender, extra_projects, user_id)
        db.session.flush()
        return tender, created

    def _add_tender_projects(
        self,
        tender: TenderApplication,
        projects: list[Project],
        user_id: uuid.UUID,
    ) -> None:
        current = {
            link.project_id
            for link in tender.project_links
            if link.deleted_at is None
        }
        for project in projects:
            if project.id in current:
                continue
            db.session.add(
                TenderProject(
                    tender_id=tender.id,
                    project_id=project.id,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
            current.add(project.id)

    def _sync_contract(
        self,
        run: EisImportRun,
        eis: EisContract,
        objects: list[WorkObject],
        user_id: uuid.UUID | None,
        *,
        tender: TenderApplication | None,
        obj: WorkObject | None = None,
    ) -> None:
        if obj is None:
            match = match_work_objects(
                [eis.delivery_place, eis.subject],
                objects,
            )
            if match.work_object is None:
                self._event(
                    run,
                    kind="unmatched",
                    message=match.reason,
                    eis_number=eis.reestr_number,
                    url=eis.url,
                    entity_type="contract",
                    extra={"subject": eis.subject, "delivery_place": eis.delivery_place},
                    user_id=user_id,
                )
                self._bump(run, "unmatched")
                db.session.commit()
                return
            obj = match.work_object

        project = self._ensure_project(run, obj, eis.subject, user_id)
        if tender is None:
            tender = ObjectService._active_tender(obj, project)

        contract = self._find_contract(eis)
        created = contract is None
        if contract is None:
            number = (eis.number or eis.reestr_number)[:100]
            amount = eis.amount if eis.amount is not None else Decimal("0")
            contract = Contract(
                contract_type=ContractType.WORK.value,
                number=number,
                title=(eis.subject or obj.display_address or number)[:500],
                description=eis.subject,
                status=map_contract_status(eis.stage, ContractStatus.DRAFT.value)
                or ContractStatus.ACTIVE.value,
                contract_date=eis.contract_date,
                start_date=eis.start_date,
                end_date=eis.end_date,
                amount=amount,
                contractor_name="",
                project_id=project.id,
                tender_application_id=tender.id if tender is not None else None,
                responsible_id=user_id,
                created_by=user_id,
                updated_by=user_id,
            )
            db.session.add(contract)
            db.session.flush()
            self._bump(run, "created_contracts")
        else:
            self._update_contract_fields(contract, eis, user_id)
            if contract.project_id is None:
                contract.project_id = project.id
            if tender is not None and contract.tender_application_id is None:
                contract.tender_application_id = tender.id
            self._bump(run, "updated_contracts")

        contract.eis_reestr_number = eis.reestr_number
        contract.eis_stage = eis.stage
        contract.eis_url = eis.url
        if eis.delivery_place:
            contract.delivery_place = eis.delivery_place[:5000]
        ContractServiceLink.ensure_object(contract, obj, user_id)
        contractors = self._sync_suppliers(run, contract, eis.suppliers, user_id)
        if contractors:
            contract.contractor_name = "; ".join(item.name for item in contractors)[:500]
            obj.contractor_name = contract.contractor_name
        if eis.number:
            obj.contract_number = eis.number[:100]
        if eis.contract_date:
            obj.contract_date = eis.contract_date
        if eis.amount is not None:
            obj.contract_amount = eis.amount
        obj.status = WorkObjectStatus.IN_CONTRACT.value
        project.status = ProjectStatus.IN_CONTRACT.value
        if tender is not None and tender.status != TenderApplicationStatus.WON.value:
            if map_tender_status(tender.eis_status) == TenderApplicationStatus.WON.value or eis.reestr_number:
                tender.status = TenderApplicationStatus.WON.value
        self._event(
            run,
            kind="created" if created else "updated",
            message=f"Контракт {contract.number}",
            eis_number=eis.reestr_number,
            url=eis.url,
            entity_type="contract",
            entity_id=contract.id,
            user_id=user_id,
        )
        db.session.commit()

    def _find_contract(self, eis: EisContract) -> Contract | None:
        if eis.reestr_number:
            found = db.session.scalar(
                db.select(Contract).where(
                    Contract.eis_reestr_number == eis.reestr_number,
                    Contract.active_filter(),
                )
            )
            if found is not None:
                return found
        if eis.number:
            return db.session.scalar(
                db.select(Contract).where(
                    Contract.number == eis.number.strip(),
                    Contract.active_filter(),
                )
            )
        return None

    def _update_contract_fields(
        self, contract: Contract, eis: EisContract, user_id: uuid.UUID | None
    ) -> None:
        if eis.number:
            contract.number = eis.number[:100]
        if eis.subject:
            contract.title = eis.subject[:500]
            contract.description = eis.subject
        if eis.contract_date:
            contract.contract_date = eis.contract_date
        if eis.start_date:
            contract.start_date = eis.start_date
        if eis.end_date:
            contract.end_date = eis.end_date
        if eis.amount is not None:
            contract.amount = eis.amount
        mapped = map_contract_status(eis.stage, contract.status)
        if mapped:
            contract.status = mapped
        contract.updated_by = user_id

    def _sync_suppliers(
        self,
        run: EisImportRun,
        contract: Contract,
        suppliers: list[EisSupplier],
        user_id: uuid.UUID | None,
    ) -> list:
        result = []
        seen_inn: set[str] = set()
        for supplier in suppliers:
            inn = (supplier.inn or "").strip()
            if inn and inn in seen_inn:
                continue
            if inn:
                seen_inn.add(inn)
            before = ContractorRepository.get_by_inn(inn) if inn else None
            contractor = ContractorService.upsert_from_eis(
                name=supplier.name,
                inn=supplier.inn,
                kpp=supplier.kpp,
                kpp_largest=supplier.kpp_largest,
                user_id=user_id,
            )
            if before is None:
                self._bump(run, "created_contractors")
            existing = db.session.scalar(
                db.select(ContractContractor).where(
                    ContractContractor.contract_id == contract.id,
                    ContractContractor.contractor_id == contractor.id,
                    ContractContractor.active_filter(),
                )
            )
            if existing is None:
                db.session.add(
                    ContractContractor(
                        contract_id=contract.id,
                        contractor_id=contractor.id,
                        created_by=user_id,
                        updated_by=user_id,
                    )
                )
            result.append(contractor)
        db.session.flush()
        return result


class ContractServiceLink:
    @staticmethod
    def ensure_object(contract: Contract, work_object: WorkObject, user_id: uuid.UUID | None) -> None:
        existing = db.session.scalar(
            db.select(ContractObject).where(
                ContractObject.contract_id == contract.id,
                ContractObject.object_id == work_object.id,
            )
        )
        if existing is None:
            db.session.add(
                ContractObject(
                    contract_id=contract.id,
                    object_id=work_object.id,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
        work_object.status = WorkObjectStatus.IN_CONTRACT.value
        work_object.updated_by = user_id

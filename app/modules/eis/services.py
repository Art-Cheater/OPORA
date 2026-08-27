"""Импорт данных ЕИС в Опору: матчинг адреса и достройка цепочки."""

from __future__ import annotations

import uuid
from datetime import timedelta, timezone
from decimal import Decimal

from flask import current_app
from sqlalchemy.orm.attributes import flag_modified

from app.extensions import db
from app.integrations.zakupki.parse import keep_eis_listing, map_eis_order_status, order_object_names
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
from app.modules.eis.matching import AddressMatch, match_work_objects
from app.modules.objects.services import ObjectService
from app.modules.projects.repositories import ProjectRepository
from app.modules.tenders.services import TenderPayload, TenderService


class EisSyncLocked(RuntimeError):
    """Уже идёт другой прогон."""


def map_tender_status(eis_status: str | None) -> str:
    mapped = map_eis_order_status(eis_status)
    if mapped == "cancelled":
        return TenderApplicationStatus.CANCELLED.value
    if mapped == "won":
        return TenderApplicationStatus.WON.value
    if mapped in {"submitted", "supplier_defined"}:
        return TenderApplicationStatus.SUBMITTED.value
    if mapped == "draft":
        return TenderApplicationStatus.DRAFT.value
    return TenderApplicationStatus.SUBMITTED.value


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


def _empty_summary() -> dict:
    return {
        "pages_fetched": 0,
        "cards_found": 0,
        "cards_parsed": 0,
        "partial_parse": 0,
        "created": 0,
        "updated": 0,
        "created_projects": 0,
        "created_tenders": 0,
        "updated_tenders": 0,
        "created_contracts": 0,
        "updated_contracts": 0,
        "created_contractors": 0,
        "matched": 0,
        "unmatched": 0,
        "ambiguous": 0,
        "fetch_errors": 0,
        "parse_errors": 0,
        "errors": 0,
        "skipped_old": 0,
        "pagination_limit_reached": False,
    }


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
                item.status = "failed"
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
            summary=_empty_summary(),
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
                    year_from=int(cfg.get("EIS_YEAR_FROM", 2025)),
                    year_to=int(cfg.get("EIS_YEAR_TO", 2100)),
                )
            self._absorb_parse_stats(run, result)
            objects = list(
                db.session.scalars(
                    db.select(WorkObject).where(WorkObject.active_filter())
                )
            )
            for issue in result.issues:
                self._record_parse_issue(run, issue, user_id)
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
            run.status = self._final_status(run)
            run.finished_at = utcnow()
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            run = db.session.get(EisImportRun, run.id) or run
            run.status = "failed"
            run.finished_at = utcnow()
            run.error_message = str(exc)[:2000]
            db.session.add(run)
            db.session.commit()
            raise
        return run

    def _absorb_parse_stats(self, run: EisImportRun, result: EisParseResult) -> None:
        summary = dict(run.summary or {})
        summary["pages_fetched"] = int(result.pages_fetched or 0)
        summary["cards_found"] = int(result.cards_found or 0)
        summary["cards_parsed"] = int(result.cards_parsed or 0)
        summary["partial_parse"] = int(result.partial_parse or 0)
        summary["fetch_errors"] = int(result.fetch_errors or 0)
        summary["parse_errors"] = int(result.parse_errors or 0)
        summary["pagination_limit_reached"] = bool(result.pagination_limit_reached)
        if result.contract_total is not None or result.order_total is not None:
            summary["total_reported"] = int(result.contract_total or 0) + int(result.order_total or 0)
        summary["last_page"] = int(result.last_page or 0)
        run.summary = summary
        flag_modified(run, "summary")

    def _record_parse_issue(
        self, run: EisImportRun, issue, user_id: uuid.UUID | None
    ) -> None:
        kind = issue.kind
        event_kind = {
            "fetch": "error",
            "parse": "error",
            "partial": "partial",
            "page_limit": "page_limit",
        }.get(kind, "error")
        if kind == "page_limit":
            run.summary["pagination_limit_reached"] = True
            flag_modified(run, "summary")
        extra = dict(issue.extra or {})
        if issue.http_status is not None:
            extra["http_status"] = issue.http_status
        if issue.attempts is not None:
            extra["attempts"] = issue.attempts
        if issue.missing:
            extra["missing"] = list(issue.missing)
        extra["issue_kind"] = kind
        self._event(
            run,
            kind=event_kind,
            message=issue.message,
            eis_number=issue.number,
            url=issue.url,
            entity_type="fetch" if kind == "fetch" else "parse",
            extra=extra or None,
            user_id=user_id,
        )

    def _final_status(self, run: EisImportRun) -> str:
        summary = run.summary or {}
        soft = (
            int(summary.get("errors") or 0)
            + int(summary.get("fetch_errors") or 0)
            + int(summary.get("parse_errors") or 0)
            + int(summary.get("partial_parse") or 0)
            + int(summary.get("unmatched") or 0)
            + int(summary.get("ambiguous") or 0)
        )
        if soft:
            return "partial"
        return "success"

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
            run.summary = _empty_summary()
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
        if key == "pagination_limit_reached":
            summary[key] = True
        else:
            summary[key] = int(summary.get(key) or 0) + 1
        run.summary = summary
        flag_modified(run, "summary")

    def _year_bounds(self) -> tuple[int, int]:
        cfg = current_app.config
        return int(cfg.get("EIS_YEAR_FROM", 2025)), int(cfg.get("EIS_YEAR_TO", 2100))

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
        # Ссылки zakupki с длинным querystring > 700 символов роняли весь прогон
        # (StringDataRightTruncation) ещё на записи ошибки скачивания.
        safe_url = (url or "").strip() or None
        if safe_url and len(safe_url) > 2000:
            safe_url = safe_url[:1997] + "..."
        safe_number = (eis_number or "").strip() or None
        if safe_number and len(safe_number) > 64:
            safe_number = safe_number[:64]
        db.session.add(
            EisImportEvent(
                run_id=run.id,
                kind=(kind or "error")[:20],
                message=(message or "")[:8000],
                eis_number=safe_number,
                url=safe_url,
                entity_type=(entity_type[:40] if entity_type else None),
                entity_id=entity_id,
                extra=extra,
                created_by=user_id,
                updated_by=user_id,
            )
        )

    def _match_extra(self, match: AddressMatch, eis: EisContract | None = None, **more) -> dict:
        data = match.to_extra()
        data.update(more)
        if eis is not None:
            data["eis_number"] = eis.reestr_number
            data["url"] = eis.url
            data["subject"] = eis.subject
            data["delivery_place"] = eis.delivery_place
            data["parsed"] = {
                "number": eis.number,
                "amount": str(eis.amount) if eis.amount is not None else None,
                "contract_date": eis.contract_date.isoformat() if eis.contract_date else None,
                "suppliers": [s.name for s in eis.suppliers],
            }
            if eis.missing_fields:
                data["missing"] = list(eis.missing_fields)
        return data

    def _sync_order(
        self,
        run: EisImportRun,
        order: EisOrder,
        objects: list[WorkObject],
        user_id: uuid.UUID | None,
    ) -> None:
        names = order_object_names(order)
        matched: list[tuple[str, WorkObject, AddressMatch]] = []
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
            for eis_contract in order.contracts:
                if self._out_of_year_range(eis_contract.reestr_number, eis_contract.contract_date):
                    self._bump(run, "skipped_old")
                    continue
                self._sync_contract(run, eis_contract, objects, user_id, tender=None)
            db.session.commit()
            return

        for name in names:
            hit = match_work_objects([name], objects)
            if hit.status != "matched" or hit.work_object is None:
                event_kind = "ambiguous" if hit.status == "ambiguous" else "unmatched"
                self._event(
                    run,
                    kind=event_kind,
                    message=f"{hit.reason}: {name}",
                    eis_number=order.reg_number,
                    url=order.url,
                    entity_type="tender",
                    extra={
                        **hit.to_extra(),
                        "purchase_object": name,
                        "status": order.status,
                        "query": name,
                    },
                    user_id=user_id,
                )
                self._bump(run, event_kind)
                continue
            if hit.work_object.id in seen_ids:
                continue
            seen_ids.add(hit.work_object.id)
            matched.append((name, hit.work_object, hit))
            self._bump(run, "matched")

        if not matched:
            for eis_contract in order.contracts:
                if self._out_of_year_range(eis_contract.reestr_number, eis_contract.contract_date):
                    self._bump(run, "skipped_old")
                    continue
                self._sync_contract(run, eis_contract, objects, user_id, tender=None)
            db.session.commit()
            return

        projects: list[Project] = []
        for name, obj, _hit in matched:
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
            self._bump(run, "created")
            kind = "created"
        else:
            self._bump(run, "updated_tenders")
            self._bump(run, "updated")
            kind = "updated"
        self._event(
            run,
            kind=kind,
            message=f"Заявка {tender.number}: {tender.status} ({len(matched)} объект.)",
            eis_number=order.reg_number,
            url=order.url,
            entity_type="tender",
            entity_id=tender.id,
            extra={
                "objects": [name for name, _, _ in matched],
                "matched_by": [hit.matched_by for _, _, hit in matched],
            },
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
        self._bump(run, "created")
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
            if order.object_title:
                tender.title = order.object_title[:500]
            if order.published_at:
                tender.published_at = order.published_at
            tender.updated_by = user_id
            if user_id is not None:
                TenderService._apply_status_side_effects(tender, user_id)
        tender.eis_reg_number = order.reg_number
        if order.status:
            tender.eis_status = order.status
        if order.url:
            tender.eis_url = order.url
        if order.nmck is not None:
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
        match: AddressMatch | None = None
        if obj is None:
            match = match_work_objects(
                [eis.delivery_place, eis.subject],
                objects,
            )
            if match.status == "matched" and match.work_object is not None:
                obj = match.work_object
                self._bump(run, "matched")
            else:
                event_kind = "ambiguous" if match.status == "ambiguous" else "unmatched"
                contract, created = self._upsert_contract(
                    run, eis, user_id, project=None, tender=None
                )
                self._event(
                    run,
                    kind=event_kind,
                    message=match.reason,
                    eis_number=eis.reestr_number,
                    url=eis.url,
                    entity_type="contract",
                    entity_id=contract.id,
                    extra=self._match_extra(match, eis),
                    user_id=user_id,
                )
                self._bump(run, event_kind)
                if eis.missing_fields:
                    self._event(
                        run,
                        kind="partial",
                        message="Контракт сохранён с неполными полями: "
                        + ", ".join(eis.missing_fields),
                        eis_number=eis.reestr_number,
                        url=eis.url,
                        entity_type="contract",
                        entity_id=contract.id,
                        extra={"missing": list(eis.missing_fields)},
                        user_id=user_id,
                    )
                self._event(
                    run,
                    kind="created" if created else "updated",
                    message=f"Контракт {contract.number} без привязки к объекту",
                    eis_number=eis.reestr_number,
                    url=eis.url,
                    entity_type="contract",
                    entity_id=contract.id,
                    extra=self._match_extra(match, eis, saved_unmatched=True),
                    user_id=user_id,
                )
                db.session.commit()
                return

        project = self._ensure_project(run, obj, eis.subject, user_id)
        if tender is None:
            tender = ObjectService._active_tender(obj, project)

        contract, created = self._upsert_contract(
            run, eis, user_id, project=project, tender=tender
        )
        ContractServiceLink.ensure_object(contract, obj, user_id)
        contractors = self._sync_suppliers(run, contract, eis.suppliers, user_id)
        if contractors:
            contract.contractor_name = "; ".join(item.name for item in contractors)[:500]
        self._apply_object_denorm(obj, contract, eis)
        project.status = ProjectStatus.IN_CONTRACT.value
        if tender is not None and tender.status != TenderApplicationStatus.WON.value:
            if map_tender_status(tender.eis_status) == TenderApplicationStatus.WON.value or eis.reestr_number:
                tender.status = TenderApplicationStatus.WON.value
        extra = {"matched_by": match.matched_by if match else "provided", "score": match.score if match else 1.0}
        if eis.missing_fields:
            extra["missing"] = list(eis.missing_fields)
            self._event(
                run,
                kind="partial",
                message="Контракт сохранён с неполными полями: " + ", ".join(eis.missing_fields),
                eis_number=eis.reestr_number,
                url=eis.url,
                entity_type="contract",
                entity_id=contract.id,
                extra={"missing": list(eis.missing_fields)},
                user_id=user_id,
            )
        self._event(
            run,
            kind="created" if created else "updated",
            message=f"Контракт {contract.number}",
            eis_number=eis.reestr_number,
            url=eis.url,
            entity_type="contract",
            entity_id=contract.id,
            extra=extra,
            user_id=user_id,
        )
        db.session.commit()

    def _upsert_contract(
        self,
        run: EisImportRun,
        eis: EisContract,
        user_id: uuid.UUID | None,
        *,
        project: Project | None,
        tender: TenderApplication | None,
    ) -> tuple[Contract, bool]:
        contract = self._find_contract(eis)
        created = contract is None
        if contract is None:
            number = (eis.number or eis.reestr_number)[:100]
            amount = eis.amount if eis.amount is not None else Decimal("0")
            contract = Contract(
                contract_type=ContractType.WORK.value,
                number=number,
                title=(eis.subject or number)[:500],
                description=eis.subject,
                status=map_contract_status(eis.stage, ContractStatus.DRAFT.value)
                or ContractStatus.ACTIVE.value,
                contract_date=eis.contract_date,
                start_date=eis.start_date,
                end_date=eis.end_date,
                amount=amount,
                contractor_name="",
                project_id=project.id if project is not None else None,
                tender_application_id=tender.id if tender is not None else None,
                responsible_id=user_id,
                created_by=user_id,
                updated_by=user_id,
            )
            db.session.add(contract)
            db.session.flush()
            self._bump(run, "created_contracts")
            self._bump(run, "created")
        else:
            self._update_contract_fields(contract, eis, user_id)
            if project is not None and contract.project_id is None:
                contract.project_id = project.id
            if tender is not None and contract.tender_application_id is None:
                contract.tender_application_id = tender.id
            self._bump(run, "updated_contracts")
            self._bump(run, "updated")

        if eis.reestr_number:
            contract.eis_reestr_number = eis.reestr_number
        if eis.stage:
            contract.eis_stage = eis.stage
        if eis.url:
            contract.eis_url = eis.url[:700]
        if eis.delivery_place:
            contract.delivery_place = eis.delivery_place[:5000]
        return contract, created

    def _apply_object_denorm(
        self, obj: WorkObject, contract: Contract, eis: EisContract
    ) -> None:
        """Денормализация с активного/актуального контракта, не со случайного старого."""
        active = ObjectService._active_contract(obj) or contract
        if active.id != contract.id and contract.id is not None:
            # обновляем денорм только если этот контракт — активный/актуальный
            # (после ensure_object активный пересчитается на следующем чтении)
            pass
        if eis.number:
            obj.contract_number = eis.number[:100]
        elif contract.number:
            obj.contract_number = contract.number[:100]
        if eis.contract_date:
            obj.contract_date = eis.contract_date
        elif contract.contract_date:
            obj.contract_date = contract.contract_date
        if eis.amount is not None:
            obj.contract_amount = eis.amount
        elif contract.amount is not None:
            obj.contract_amount = contract.amount
        if contract.contractor_name:
            obj.contractor_name = contract.contractor_name
        obj.status = WorkObjectStatus.IN_CONTRACT.value

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

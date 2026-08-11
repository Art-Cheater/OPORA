"""Сервисы модуля объектов."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.audit_service import AuditService
from app.core.exceptions import ValidationError
from app.extensions import db
from app.models.enums import AuditAction, EntityType, WorkObjectStatus
from app.models.work_objects.work_object import WorkObject


@dataclass
class ObjectPayload:
    name: str
    address: str | None
    plan_year: int | None
    notes: str | None
    status: str


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    total: int = 0


class ObjectService:
    @staticmethod
    def _normalize(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None

    @staticmethod
    def _guess_address(name: str) -> str | None:
        """Вытащить адресную часть из типового названия «Устройство … по/в …»."""
        m = re.search(r"\b(?:по|в|на)\b\s+(.+)$", name, flags=re.IGNORECASE)
        if not m:
            return None
        addr = m.group(1).strip(" .;")
        return addr[:500] if addr else None

    @classmethod
    def parse_lighting_plan_xlsx(cls, path: Path) -> list[dict]:
        """Читает «План работ освещение» и возвращает строки {name, plan_year, source_sheet}."""
        try:
            import openpyxl
        except ImportError as exc:
            raise ValidationError("Для импорта нужен пакет openpyxl. Установите зависимости.") from exc

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        rows: list[dict] = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            year_match = re.search(r"(20\d{2})", sheet_name)
            plan_year = int(year_match.group(1)) if year_match else None

            header_row = None
            name_col = None
            for i, row in enumerate(ws.iter_rows(max_row=20, values_only=True), start=1):
                for j, cell in enumerate(row or ()):
                    if isinstance(cell, str) and "Наименование" in cell:
                        header_row = i
                        name_col = j
                        break
                if header_row is not None:
                    break
            if header_row is None or name_col is None:
                continue

            for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
                if not row or name_col >= len(row):
                    continue
                raw = row[name_col]
                if raw is None:
                    continue
                name = str(raw).strip()
                if not name or name.lower().startswith("итого"):
                    continue
                # Схлопываем пробелы/переносы
                name = re.sub(r"\s+", " ", name)
                rows.append(
                    {
                        "name": name[:500],
                        "plan_year": plan_year,
                        "source_sheet": sheet_name.strip(),
                    }
                )
        wb.close()
        return rows

    @classmethod
    def import_from_lighting_plan(cls, path: Path | str, user_id: uuid.UUID) -> ImportResult:
        path = Path(path)
        if not path.is_file():
            raise ValidationError("Файл импорта не найден.")

        parsed = cls.parse_lighting_plan_xlsx(path)
        result = ImportResult(total=len(parsed))
        if not parsed:
            raise ValidationError("В файле не найдено ни одного наименования объекта.")

        # Один объект = уникальное наименование; годы/листы собираем в notes
        by_name: dict[str, dict] = {}
        for item in parsed:
            key = item["name"].casefold()
            bucket = by_name.setdefault(
                key,
                {
                    "name": item["name"],
                    "years": set(),
                    "sheets": set(),
                },
            )
            if item["plan_year"]:
                bucket["years"].add(item["plan_year"])
            bucket["sheets"].add(item["source_sheet"])

        existing = {
            obj.name.casefold(): obj
            for obj in db.session.scalars(
                db.select(WorkObject).where(WorkObject.active_filter())
            ).all()
        }

        for key, data in by_name.items():
            years = sorted(data["years"])
            plan_year = years[0] if years else None
            years_note = ", ".join(str(y) for y in years) if years else "—"
            sheets_note = ", ".join(sorted(data["sheets"]))
            note = f"Импорт из плана освещения. Годы: {years_note}. Листы: {sheets_note}."
            address = cls._guess_address(data["name"])

            obj = existing.get(key)
            if obj is None:
                obj = WorkObject(
                    name=data["name"],
                    address=address,
                    plan_year=plan_year,
                    notes=note,
                    status=WorkObjectStatus.FREE.value,
                    created_by=user_id,
                    updated_by=user_id,
                )
                db.session.add(obj)
                result.created += 1
            else:
                changed = False
                if not obj.address and address:
                    obj.address = address
                    changed = True
                if obj.plan_year is None and plan_year is not None:
                    obj.plan_year = plan_year
                    changed = True
                elif plan_year is not None and years and (
                    obj.plan_year is None or obj.plan_year > plan_year
                ):
                    obj.plan_year = plan_year
                    changed = True
                if not obj.notes or "Импорт из плана освещения" not in obj.notes:
                    obj.notes = note if not obj.notes else f"{obj.notes}\n{note}"
                    changed = True
                if changed:
                    obj.updated_by = user_id
                    result.updated += 1
                else:
                    result.skipped += 1

        AuditService.log(
            user_id=user_id,
            action=AuditAction.CREATE.value,
            entity_type=EntityType.WORK_OBJECT.value,
            description=(
                f"Импорт объектов из плана освещения: "
                f"+{result.created} / ~{result.updated} / skip {result.skipped}"
            ),
            new_values={
                "created": result.created,
                "updated": result.updated,
                "skipped": result.skipped,
                "total_rows": result.total,
                "unique": len(by_name),
            },
        )
        db.session.commit()
        return result

    @classmethod
    def create(cls, payload: ObjectPayload, user_id: uuid.UUID) -> WorkObject:
        if not payload.name.strip():
            raise ValidationError("Наименование объекта обязательно.")
        obj = WorkObject(
            name=payload.name.strip(),
            address=cls._normalize(payload.address),
            plan_year=payload.plan_year,
            notes=cls._normalize(payload.notes),
            status=payload.status or WorkObjectStatus.FREE.value,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(obj)
        db.session.flush()
        AuditService.log(
            user_id=user_id,
            action=AuditAction.CREATE.value,
            entity_type=EntityType.WORK_OBJECT.value,
            entity_id=obj.id,
            description=f"Создан объект {obj.name}",
            new_values={"name": obj.name, "status": obj.status},
        )
        db.session.commit()
        return obj

    @classmethod
    def update(cls, obj: WorkObject, payload: ObjectPayload, user_id: uuid.UUID) -> WorkObject:
        if not payload.name.strip():
            raise ValidationError("Наименование объекта обязательно.")
        old = {"name": obj.name, "status": obj.status, "address": obj.address}
        obj.name = payload.name.strip()
        obj.address = cls._normalize(payload.address)
        obj.plan_year = payload.plan_year
        obj.notes = cls._normalize(payload.notes)
        obj.status = payload.status
        obj.updated_by = user_id
        AuditService.log(
            user_id=user_id,
            action=AuditAction.UPDATE.value,
            entity_type=EntityType.WORK_OBJECT.value,
            entity_id=obj.id,
            description=f"Обновлён объект {obj.name}",
            old_values=old,
            new_values={"name": obj.name, "status": obj.status, "address": obj.address},
        )
        db.session.commit()
        return obj

    @classmethod
    def soft_delete(cls, obj: WorkObject, user_id: uuid.UUID) -> None:
        if obj.status not in (WorkObjectStatus.FREE.value, WorkObjectStatus.ARCHIVED.value):
            raise ValidationError("Можно удалить только свободный или архивный объект.")
        obj.soft_delete(user_id)
        AuditService.log(
            user_id=user_id,
            action=AuditAction.SOFT_DELETE.value,
            entity_type=EntityType.WORK_OBJECT.value,
            entity_id=obj.id,
            description=f"Удалён объект {obj.name}",
        )
        db.session.commit()

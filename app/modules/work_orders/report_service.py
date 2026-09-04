"""Формирование DOCX-отчёта по завершённому плану работ."""

from __future__ import annotations

import re
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from xml.sax.saxutils import escape

from app.models.base import as_utc_aware, format_local_dt
from app.models.enums import EntityType
from app.models.files.attachment import Attachment
from app.models.work_plans.work_plan import WorkPlan
from app.extensions import db


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _xml_text(value) -> str:
    text = str(value or "")
    text = "".join(char for char in text if ord(char) >= 32 or char in "\t\n\r")
    return escape(text)


def _paragraph(text: str = "", *, bold: bool = False, size: int | None = None) -> str:
    properties = ""
    if bold or size:
        parts = ["<w:b/>" if bold else ""]
        if size:
            parts.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
        properties = f"<w:rPr>{''.join(parts)}</w:rPr>"
    return f'<w:p><w:r>{properties}<w:t xml:space="preserve">{_xml_text(text)}</w:t></w:r></w:p>'


def _duration(start, end) -> str:
    start_utc = as_utc_aware(start)
    end_utc = as_utc_aware(end)
    if start_utc is None or end_utc is None or end_utc < start_utc:
        return "не определено"
    total_minutes = int((end_utc - start_utc).total_seconds() // 60)
    days, remainder = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} дн.")
    if hours:
        parts.append(f"{hours} ч")
    parts.append(f"{minutes} мин")
    return " ".join(parts)


def report_filename(plan: WorkPlan) -> str:
    token = re.sub(r"[^A-Za-z0-9_-]+", "_", plan.number or str(plan.id)).strip("_")
    return f"otchet_po_planu_{token or plan.id}.docx"


def build_work_plan_report(plan: WorkPlan) -> bytes:
    """Создать небольшой автономный DOCX без внешней офисной зависимости."""
    started_at = plan.saved_at or plan.created_at
    finished_at = plan.completed_at
    items = [item for item in plan.items if item.deleted_at is None]
    completed = [item for item in items if item.result == "completed"]
    completed_requests = [item for item in completed if item.request_id is not None]
    completed_defects = [item for item in completed if item.defect_id is not None]
    excluded = [item for item in items if item.result == "excluded"]

    body = [
        _paragraph(f"Отчёт по плану работ № {plan.number or '—'}", bold=True, size=32),
        _paragraph(),
        _paragraph(f"Исполнитель плана: {plan.master.full_name if plan.master else '—'}"),
        _paragraph(f"План создан: {format_local_dt(plan.created_at)}"),
        _paragraph(f"Работа начата: {format_local_dt(started_at)}"),
        _paragraph(f"План завершён: {format_local_dt(finished_at)}"),
        _paragraph(f"Общее время выполнения: {_duration(started_at, finished_at)}", bold=True),
        _paragraph(
            f"Итого: {len(items)} работ; выполнено — {len(completed)}; исключено — {len(excluded)}."
        ),
        _paragraph(),
        _paragraph("Закрытые заявки", bold=True, size=26),
    ]
    if completed_requests:
        for item in completed_requests:
            body.append(
                _paragraph(
                    f"• Заявка № {item.number_snapshot}: {item.address_snapshot or 'адрес не указан'}. "
                    f"Закрыта {format_local_dt(item.completed_at)}; время от начала плана — "
                    f"{_duration(started_at, item.completed_at)}; выполнил — "
                    f"{item.completed_by_user.full_name if item.completed_by_user else '—'}."
                )
            )
            if item.complete_comment:
                body.append(_paragraph(f"  Результат: {item.complete_comment}"))
    else:
        body.append(_paragraph("Закрытых заявок в плане нет."))

    body.extend([_paragraph(), _paragraph("Устранённые дефекты", bold=True, size=26)])
    if completed_defects:
        for item in completed_defects:
            body.append(
                _paragraph(
                    f"• Дефект {item.number_snapshot}: {item.address_snapshot or 'адрес не указан'}. "
                    f"Завершён {format_local_dt(item.completed_at)}; время от начала плана — "
                    f"{_duration(started_at, item.completed_at)}."
                )
            )
    else:
        body.append(_paragraph("Устранённых дефектов в плане нет."))

    if excluded:
        body.extend([_paragraph(), _paragraph("Исключённые работы", bold=True, size=26)])
        for item in excluded:
            reason = item.exclude_comment or item.exclude_reason or "причина не указана"
            body.append(_paragraph(f"• {item.number_snapshot}: {reason}."))
            names = list(
                db.session.scalars(
                    db.select(Attachment.file_name).where(
                        Attachment.entity_type == EntityType.WORK_PLAN_ITEM.value,
                        Attachment.entity_id == item.id,
                        Attachment.active_filter(),
                    )
                )
            )
            if names:
                body.append(_paragraph(f"  Приложенные файлы: {', '.join(names)}."))

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body)}"
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
        "</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )

    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document_xml)
    return stream.getvalue()

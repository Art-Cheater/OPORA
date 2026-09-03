"""Просмотр файлов и русские подписи документов заявок на торги."""

from __future__ import annotations

from app.extensions import db
from app.models.auth.user import User
from app.models.enums import TenderApplicationStatus, TenderDocumentType
from app.models.tenders.tender_application import TenderApplication
from app.models.tenders.tender_document import TenderDocument


def test_tender_pdf_has_inline_preview_and_russian_type(app, admin_client):
    with app.app_context():
        admin = db.session.scalar(db.select(User).where(User.email == "admin@opora.ru"))
        tender = TenderApplication(
            number="ТРГ-ПРОСМОТР-1",
            title="Проверка документов",
            status=TenderApplicationStatus.DRAFT.value,
            created_by=admin.id,
            updated_by=admin.id,
        )
        db.session.add(tender)
        db.session.flush()
        storage_key = f"tenders/{tender.id}/request.pdf"
        document = TenderDocument(
            tender_id=tender.id,
            title="Запрос цены",
            document_type=TenderDocumentType.PRICE_REQUEST.value,
            file_name="request.pdf",
            mime_type="application/pdf",
            storage_key=storage_key,
            created_by=admin.id,
            updated_by=admin.id,
        )
        db.session.add(document)
        db.session.commit()
        tender_id = str(tender.id)
        document_id = str(document.id)
        path = app.config["UPLOAD_FOLDER"] / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4 tender preview")

    page = admin_client.get(f"/tenders/{tender_id}")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Запрос ценовой информации" in html
    assert "Просмотр" in html
    assert f"/tenders/{tender_id}/documents/{document_id}/download?inline=1" in html

    preview = admin_client.get(
        f"/tenders/{tender_id}/documents/{document_id}/download?inline=1"
    )
    assert preview.status_code == 200
    assert preview.data == b"%PDF-1.4 tender preview"
    assert "inline" in preview.headers.get("Content-Disposition", "")

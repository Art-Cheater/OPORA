"""Формы заявок на торги."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    MultipleFileField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Optional

from app.models.enums import TenderApplicationStatus, TenderDocumentType

TENDER_STATUS_CHOICES = [
    (TenderApplicationStatus.DRAFT.value, "Черновик"),
    (TenderApplicationStatus.SUBMITTED.value, "Передана в закупки"),
    (TenderApplicationStatus.WON.value, "Торги выиграны"),
    (TenderApplicationStatus.LOST.value, "Торги проиграны"),
    (TenderApplicationStatus.CANCELLED.value, "Отменена"),
]

TENDER_STATUS_LABELS = dict(TENDER_STATUS_CHOICES)

TENDER_DOC_TYPE_CHOICES = [
    (TenderDocumentType.TENDER_APPLICATION.value, "Заявка на электронные торги"),
    (TenderDocumentType.PRICE_REQUEST.value, "Запрос ценовой информации"),
    (TenderDocumentType.OTHER.value, "Прочее"),
]
TENDER_DOC_TYPE_LABELS = dict(TENDER_DOC_TYPE_CHOICES)


class TenderFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional(), Length(max=255)])
    status = SelectField(
        "Статус",
        choices=[("", "Все статусы")] + TENDER_STATUS_CHOICES,
        validators=[Optional()],
    )
    sort_by = SelectField(
        "Сортировка",
        choices=[
            ("created_at", "По дате создания"),
            ("updated_at", "По дате обновления"),
            ("number", "По номеру"),
            ("title", "По названию / объекту"),
            ("status", "По статусу"),
            ("work_deadline", "По сроку"),
        ],
        default="created_at",
        validate_choice=False,
    )
    sort_dir = SelectField(
        "Направление",
        choices=[("desc", "Сначала новые"), ("asc", "Сначала старые")],
        default="desc",
    )


class TenderForm(FlaskForm):
    number = StringField("Номер", validators=[DataRequired(), Length(max=50)])
    title = StringField("Название", validators=[DataRequired(), Length(max=500)])
    object_id = SelectField("Объект", choices=[], validators=[Optional()], validate_choice=False)
    work_deadline = StringField("Срок выполнения работ", validators=[Optional(), Length(max=500)])
    published_at = DateField("Дата публикации заявки", validators=[Optional()], format="%Y-%m-%d")
    description = TextAreaField("Описание", validators=[Optional(), Length(max=10000)])
    status = SelectField("Статус", choices=TENDER_STATUS_CHOICES, validators=[DataRequired()])
    responsible_id = SelectField("Ответственный", choices=[], validators=[Optional()])
    project_ids = SelectMultipleField(
        "Проекты",
        choices=[],
        validators=[Optional()],
        validate_choice=False,
    )
    submit = SubmitField("Сохранить")


class TenderDocumentForm(FlaskForm):
    title = StringField("Название", validators=[DataRequired(), Length(max=500)])
    document_type = SelectField(
        "Тип документа",
        choices=TENDER_DOC_TYPE_CHOICES,
        validators=[DataRequired()],
    )
    document_number = StringField("Номер", validators=[Optional(), Length(max=100)])
    document_date = DateField("Дата документа", validators=[Optional()], format="%Y-%m-%d")
    description = TextAreaField("Описание", validators=[Optional(), Length(max=5000)])
    files = MultipleFileField("Файлы", validators=[Optional()])
    submit = SubmitField("Добавить документ")


class TenderStatusForm(FlaskForm):
    status = SelectField("Статус", choices=TENDER_STATUS_CHOICES, validators=[DataRequired()])
    submit = SubmitField("Обновить статус")

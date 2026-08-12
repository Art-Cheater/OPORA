"""Формы модуля объектов."""

from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    DateField,
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models.enums import WorkObjectStatus

OBJECT_STATUS_CHOICES = [
    (WorkObjectStatus.FREE.value, "Свободен"),
    (WorkObjectStatus.IN_PROJECT.value, "В проекте"),
    (WorkObjectStatus.IN_TENDER.value, "На торгах"),
    (WorkObjectStatus.IN_CONTRACT.value, "В контракте"),
    (WorkObjectStatus.COMPLETED.value, "Выполнен"),
    (WorkObjectStatus.ARCHIVED.value, "В архиве"),
]

OBJECT_STATUS_LABELS = dict(OBJECT_STATUS_CHOICES)


class ObjectFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional(), Length(max=255)])
    status = SelectField(
        "Статус",
        choices=[("", "Все статусы")] + OBJECT_STATUS_CHOICES,
        validators=[Optional()],
    )
    plan_year = StringField("Год плана", validators=[Optional(), Length(max=4)])
    sort_by = SelectField(
        "Сортировка",
        choices=[
            ("created_at", "По дате создания"),
            ("address", "По адресу"),
            ("plan_year", "По году"),
            ("contractor_name", "По подрядчику"),
            ("status", "По статусу"),
        ],
        default="created_at",
    )
    sort_dir = SelectField(
        "Направление",
        choices=[("desc", "Сначала новые"), ("asc", "Сначала старые")],
        default="desc",
    )


class ObjectForm(FlaskForm):
    work_type = StringField(
        "Тип работ",
        validators=[Optional(), Length(max=255)],
        default="Устройство наружного освещения",
    )
    address = StringField("Адрес", validators=[DataRequired(), Length(max=1000)])
    plan_year = IntegerField("Год плана", validators=[Optional(), NumberRange(min=2000, max=2100)])
    work_deadline = StringField("Срок выполнения работ", validators=[Optional(), Length(max=500)])
    contract_number = StringField("Номер контракта", validators=[Optional(), Length(max=100)])
    contract_date = DateField("Дата заключения", validators=[Optional()], format="%Y-%m-%d")
    contractor_name = StringField("Подрядчик", validators=[Optional(), Length(max=500)])
    contract_amount = DecimalField("Сумма контракта", places=2, validators=[Optional()])
    budget_amount = DecimalField("Бюджет / НМЦК", places=2, validators=[Optional()])
    result_text = StringField("Результат", validators=[Optional(), Length(max=500)])
    notes = TextAreaField("Примечание", validators=[Optional(), Length(max=10000)])
    status = SelectField("Статус", choices=OBJECT_STATUS_CHOICES, validators=[DataRequired()])
    submit = SubmitField("Сохранить")


class ObjectImportForm(FlaskForm):
    file = FileField(
        "Файл плана (.xlsx)",
        validators=[
            FileRequired(message="Выберите файл Excel"),
            FileAllowed(["xlsx"], message="Только .xlsx"),
        ],
    )
    submit = SubmitField("Импортировать объекты")

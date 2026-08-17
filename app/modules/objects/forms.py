"""Формы модуля объектов."""

from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    DateField,
    DecimalField,
    IntegerField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models.enums import WorkObjectKind, WorkObjectStatus

OBJECT_STATUS_CHOICES = [
    (WorkObjectStatus.FREE.value, "Свободен"),
    (WorkObjectStatus.IN_PROJECT.value, "В проекте"),
    (WorkObjectStatus.IN_TENDER.value, "В закупках"),
    (WorkObjectStatus.IN_CONTRACT.value, "В контракте"),
    (WorkObjectStatus.COMPLETED.value, "Выполнен"),
    (WorkObjectStatus.ARCHIVED.value, "В архиве"),
]

OBJECT_STATUS_LABELS = dict(OBJECT_STATUS_CHOICES)

OBJECT_KIND_CHOICES = [
    (WorkObjectKind.PLANNED.value, "Плановый"),
    (WorkObjectKind.COURT.value, "Судебный"),
    (WorkObjectKind.TECH_CONNECT.value, "Техническое присоединение"),
]

OBJECT_KIND_LABELS = dict(OBJECT_KIND_CHOICES)


class ObjectFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional(), Length(max=255)])
    status = SelectMultipleField(
        "Статус",
        choices=OBJECT_STATUS_CHOICES,
        validators=[Optional()],
        validate_choice=False,
    )
    object_kind = SelectMultipleField(
        "Тип объекта",
        choices=OBJECT_KIND_CHOICES,
        validators=[Optional()],
        validate_choice=False,
    )
    plan_year = StringField("Год плана", validators=[Optional(), Length(max=4)])
    contractor_name = StringField("Подрядчик", validators=[Optional(), Length(max=500)])
    deadline_from = DateField("Срок с", validators=[Optional()], format="%Y-%m-%d")
    deadline_to = DateField("Срок по", validators=[Optional()], format="%Y-%m-%d")
    sort_by = SelectField(
        "Сортировка",
        choices=[
            ("created_at", "По дате создания"),
            ("address", "По адресу"),
            ("work_deadline", "По сроку"),
            ("contract_number", "По номеру контракта"),
            ("contract_date", "По дате заключения"),
            ("plan_year", "По году"),
            ("contractor_name", "По подрядчику"),
            ("object_kind", "По типу объекта"),
            ("status", "По статусу"),
        ],
        default="created_at",
        validate_choice=False,
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
    object_kind = SelectField(
        "Тип объекта",
        choices=OBJECT_KIND_CHOICES,
        default=WorkObjectKind.PLANNED.value,
        validators=[DataRequired()],
    )
    address = StringField("Адрес", validators=[DataRequired(), Length(max=1000)])
    full_name = StringField(
        "Полное наименование",
        validators=[Optional(), Length(max=1000)],
        description="Как в плане работ; если пусто — соберётся из типа и адреса",
    )
    plan_year = IntegerField("Год плана", validators=[Optional(), NumberRange(min=2000, max=2100)])
    work_deadline = StringField("Срок выполнения работ", validators=[Optional(), Length(max=500)])
    contract_number = StringField("Номер контракта", validators=[Optional(), Length(max=100)])
    contract_date = DateField("Дата заключения", validators=[Optional()], format="%Y-%m-%d")
    contractor_name = StringField("Подрядчик", validators=[Optional(), Length(max=500)])
    contract_amount = DecimalField("Сумма контракта", places=2, validators=[Optional()])
    budget_amount = DecimalField(
        "Расходы бюджета по НМЦК",
        places=2,
        validators=[Optional()],
        description="Не равна сумме контракта, когда контракт уже заключён",
    )
    court_decision_number = StringField(
        "Номер судебного решения",
        validators=[Optional(), Length(max=255)],
        description="Заполняется для типа «Судебный»",
    )
    result_text = StringField("Результат", validators=[Optional(), Length(max=500)])
    notes = TextAreaField(
        "Основание для проведения работ",
        validators=[Optional(), Length(max=10000)],
    )
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

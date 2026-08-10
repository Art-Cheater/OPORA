"""Формы модуля контрактов."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import DateField, MultipleFileField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from app.models.enums import ContractStatus, ContractType


CONTRACT_TYPE_CHOICES = [
    (ContractType.SUPPLY.value, "Поставка"),
    (ContractType.SERVICE.value, "Услуги"),
    (ContractType.WORK.value, "Подряд"),
    (ContractType.LEASE.value, "Аренда"),
    (ContractType.OTHER.value, "Прочее"),
]

CONTRACT_STATUS_CHOICES = [
    (ContractStatus.DRAFT.value, "Черновик"),
    (ContractStatus.ACTIVE.value, "Действует"),
    (ContractStatus.COMPLETED.value, "Завершён"),
    (ContractStatus.TERMINATED.value, "Расторгнут"),
]


class ContractFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional(), Length(max=255)])
    contract_type = SelectField(
        "Тип",
        choices=[("", "Все типы")] + CONTRACT_TYPE_CHOICES,
        validators=[Optional()],
    )
    status = SelectField(
        "Статус",
        choices=[("", "Все статусы")] + CONTRACT_STATUS_CHOICES,
        validators=[Optional()],
    )
    responsible_id = SelectField("Ответственный", choices=[], validators=[Optional()])
    date_from = DateField("Дата с", validators=[Optional()], format="%Y-%m-%d")
    date_to = DateField("Дата по", validators=[Optional()], format="%Y-%m-%d")
    sort_by = SelectField(
        "Сортировка",
        choices=[
            ("created_at", "По дате создания"),
            ("updated_at", "По дате обновления"),
            ("number", "По номеру"),
            ("title", "По названию"),
            ("status", "По статусу"),
            ("contract_type", "По типу"),
            ("contract_date", "По дате контракта"),
        ],
        default="created_at",
    )
    sort_dir = SelectField(
        "Направление",
        choices=[("desc", "Сначала новые"), ("asc", "Сначала старые")],
        default="desc",
    )


class ContractForm(FlaskForm):
    contract_type = SelectField("Тип", choices=CONTRACT_TYPE_CHOICES, validators=[DataRequired()])
    number = StringField("Номер", validators=[DataRequired(), Length(max=100)])
    title = StringField("Название", validators=[DataRequired(), Length(max=500)])
    description = TextAreaField("Описание", validators=[Optional(), Length(max=10000)])
    status = SelectField("Статус", choices=CONTRACT_STATUS_CHOICES, validators=[DataRequired()])
    contract_date = DateField("Дата", validators=[Optional()], format="%Y-%m-%d")
    responsible_id = SelectField("Ответственный", choices=[], validators=[Optional()])
    submit = SubmitField("Сохранить")


class ContractCommentForm(FlaskForm):
    body = TextAreaField("Комментарий", validators=[DataRequired(), Length(max=5000)])
    submit = SubmitField("Добавить комментарий")


class ContractDocumentForm(FlaskForm):
    title = StringField("Название", validators=[DataRequired(), Length(max=500)])
    document_number = StringField("Номер документа", validators=[Optional(), Length(max=100)])
    document_date = DateField("Дата документа", validators=[Optional()], format="%Y-%m-%d")
    description = TextAreaField("Описание", validators=[Optional(), Length(max=5000)])
    files = MultipleFileField("Файлы", validators=[Optional()])
    submit = SubmitField("Добавить документ")

"""Формы модуля контрактов."""

from __future__ import annotations

from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    DecimalField,
    MultipleFileField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional

from app.models.enums import ContractDocumentType, ContractStatus, ContractType


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
    (ContractStatus.WORK_DOCS_PENDING.value, "Согласование рабочей документации"),
    (ContractStatus.IN_PROGRESS.value, "Выполнение работ"),
    (ContractStatus.KS2_PENDING.value, "Приёмка КС-2"),
    (ContractStatus.REJECTED.value, "Отклонено"),
    (ContractStatus.COMPLETED.value, "Закрыт (принято)"),
    (ContractStatus.TERMINATED.value, "Закрыт (с отклонением / расторгнут)"),
]

CONTRACT_STATUS_LABELS = dict(CONTRACT_STATUS_CHOICES)

CONTRACT_DOC_TYPE_CHOICES = [
    (ContractDocumentType.CONTRACT.value, "Контракт"),
    (ContractDocumentType.LOCAL_ESTIMATE.value, "Локальный сметный расчет"),
    (ContractDocumentType.WORK_DOCS.value, "Рабочая документация"),
    (ContractDocumentType.KS2.value, "Акт выполненных работ (КС-2)"),
    (ContractDocumentType.REJECTION_MEMO.value, "Служебная записка (замечания)"),
    (ContractDocumentType.OTHER.value, "Прочее"),
]


class RussianDecimalField(DecimalField):
    """DecimalField с понятной ошибкой вместо англоязычного сообщения WTForms."""

    def process_formdata(self, valuelist):
        try:
            super().process_formdata(valuelist)
        except ValueError as exc:
            raise ValueError("Введите корректную сумму контракта.") from exc


class RussianDateField(DateField):
    """DateField с понятной ошибкой формата даты."""

    def process_formdata(self, valuelist):
        try:
            super().process_formdata(valuelist)
        except ValueError as exc:
            raise ValueError("Введите корректную дату в формате ГГГГ-ММ-ДД.") from exc


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
    end_date_from = DateField("Окончание с", validators=[Optional()], format="%Y-%m-%d")
    end_date_to = DateField("Окончание по", validators=[Optional()], format="%Y-%m-%d")
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
            ("end_date", "По дате окончания"),
            ("contractor_name", "По подрядчику"),
            ("amount", "По сумме"),
        ],
        default="created_at",
        validate_choice=False,
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
    contractor_name = StringField(
        "Подрядчик",
        validators=[
            DataRequired(message="Укажите подрядчика."),
            Length(max=500, message="Название подрядчика не должно превышать 500 символов."),
        ],
    )
    amount = RussianDecimalField(
        "Сумма",
        validators=[
            InputRequired(message="Укажите сумму контракта."),
            NumberRange(
                min=Decimal("0.01"),
                message="Сумма контракта должна быть больше нуля.",
            ),
        ],
        places=2,
        default=None,
        rounding=None,
    )
    status = SelectField("Статус", choices=CONTRACT_STATUS_CHOICES, validators=[DataRequired()])
    contract_date = DateField("Дата", validators=[Optional()], format="%Y-%m-%d")
    end_date = RussianDateField(
        "Дата окончания",
        validators=[InputRequired(message="Укажите дату окончания контракта.")],
        format="%Y-%m-%d",
    )
    responsible_id = SelectField("Ответственный", choices=[], validators=[Optional()])
    submit = SubmitField("Сохранить")


class ContractCommentForm(FlaskForm):
    body = TextAreaField("Комментарий", validators=[DataRequired(), Length(max=5000)])
    submit = SubmitField("Добавить комментарий")


class ContractDocumentForm(FlaskForm):
    title = StringField("Название", validators=[DataRequired(), Length(max=500)])
    document_type = SelectField(
        "Тип документа",
        choices=CONTRACT_DOC_TYPE_CHOICES,
        validators=[DataRequired()],
    )
    document_number = StringField("Номер документа", validators=[Optional(), Length(max=100)])
    document_date = DateField("Дата документа", validators=[Optional()], format="%Y-%m-%d")
    description = TextAreaField("Описание", validators=[Optional(), Length(max=5000)])
    files = MultipleFileField("Файлы", validators=[Optional()])
    submit = SubmitField("Добавить документ")


class ContractWorkflowForm(FlaskForm):
    comment = TextAreaField("Комментарий", validators=[Optional(), Length(max=5000)])
    submit = SubmitField("Выполнить")

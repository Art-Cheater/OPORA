"""Формы модуля заявок."""

from __future__ import annotations

from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateTimeLocalField,
    DecimalField,
    HiddenField,
    IntegerField,
    MultipleFileField,
    SelectField,
    StringField,
    SubmitField,
    TelField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models.enums import Priority
from app.modules.requests.districts import district_choices


class RequestFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional(), Length(max=255)])
    number = StringField("Номер", validators=[Optional(), Length(max=50)])
    date_from = StringField("С", validators=[Optional(), Length(max=10)])
    date_to = StringField("По", validators=[Optional(), Length(max=10)])
    district = SelectField(
        "Район",
        choices=district_choices(empty_label="Любой"),
        validators=[Optional()],
        validate_choice=False,
    )
    pp = StringField("ПП", validators=[Optional(), Length(max=255)])
    for_beresnev = BooleanField("Для Береснева", default=False)
    hide_completed = BooleanField("Убрать выполненные", default=False)
    status_id = SelectField("Статус", choices=[], validators=[Optional()])
    priority = SelectField(
        "Приоритет",
        choices=[
            ("", "Любой"),
            (Priority.LOW.value, "Низкий"),
            (Priority.MEDIUM.value, "Средний"),
            (Priority.HIGH.value, "Высокий"),
            (Priority.CRITICAL.value, "Критический"),
        ],
        validators=[Optional()],
    )
    dispatcher_name = SelectField("Диспетчер", choices=[], validators=[Optional()])
    journal_id = SelectField("Журнал", choices=[], validators=[Optional()], validate_choice=False)
    preset = SelectField(
        "Быстрый фильтр",
        choices=[
            ("", "Все заявки"),
            ("for_emergency", "Новые"),
            ("completed", "Выполненные"),
        ],
        validators=[Optional()],
        default="",
    )
    sort_by = SelectField(
        "Сортировка",
        choices=[
            ("received_at", "По дате получения"),
            ("created_at", "По дате создания"),
            ("updated_at", "По дате обновления"),
            ("number", "По номеру"),
            ("priority", "По приоритету"),
            ("address", "По адресу"),
            ("pp", "По ПП"),
            ("dispatcher_name", "По диспетчеру"),
            ("status_id", "По статусу"),
        ],
        default="received_at",
        validate_choice=False,
    )
    sort_dir = SelectField(
        "Направление",
        choices=[("desc", "Сначала новые"), ("asc", "Сначала старые")],
        default="desc",
    )


class RequestForm(FlaskForm):
    number = StringField("Номер заявки", validators=[DataRequired(), Length(max=50)])
    journal_id = SelectField(
        "Журнал",
        choices=[],
        validators=[Optional()],
        validate_choice=False,
    )
    address = StringField("Адрес", validators=[DataRequired(), Length(max=500)])
    address_selection_token = HiddenField(validators=[Optional()])
    original_address = HiddenField(validators=[Optional(), Length(max=500)])
    normalized_address = HiddenField(validators=[Optional(), Length(max=1000)])
    region = HiddenField(validators=[Optional(), Length(max=255)])
    district = SelectField(
        "Район",
        choices=district_choices(empty_label="Не указан"),
        validators=[Optional()],
        validate_choice=False,
    )
    settlement = HiddenField(validators=[Optional(), Length(max=255)])
    street = HiddenField(validators=[Optional(), Length(max=500)])
    house = HiddenField(validators=[Optional(), Length(max=100)])
    address_source = HiddenField(validators=[Optional(), Length(max=50)])
    address_external_id = HiddenField(validators=[Optional(), Length(max=255)])
    pp = StringField("ПП (пункт питания)", validators=[Optional(), Length(max=255)])
    received_at = DateTimeLocalField(
        "Дата и время получения",
        format="%Y-%m-%dT%H:%M",
        validators=[DataRequired(message="Укажите дату и время получения")],
    )
    dispatcher_name = SelectField(
        "Диспетчер",
        choices=[],
        validators=[DataRequired(message="Выберите диспетчера")],
        validate_choice=False,
    )
    responsible_id = SelectField(
        "Районный мастер",
        choices=[],
        validators=[Optional()],
        validate_choice=False,
    )
    description = TextAreaField("Описание", validators=[Optional(), Length(max=10000)])
    latitude = DecimalField("Широта", validators=[Optional()], places=7)
    longitude = DecimalField("Долгота", validators=[Optional()], places=7)
    phone = TelField("Телефон заявителя", validators=[Optional(), Length(max=30)])
    applicant_name = StringField("Заявитель", validators=[Optional(), Length(max=255)])
    has_barrier = BooleanField("Шлагбаум", default=False)
    barrier_phone = TelField("Телефон шлагбаума", validators=[Optional(), Length(max=30)])
    for_beresnev = BooleanField("Для Береснева", default=False)
    priority = SelectField(
        "Приоритет",
        choices=[
            (Priority.LOW.value, "Низкий"),
            (Priority.MEDIUM.value, "Средний"),
            (Priority.HIGH.value, "Высокий"),
            (Priority.CRITICAL.value, "Критический"),
        ],
        validators=[DataRequired()],
    )
    status_id = SelectField(
        "Статус",
        choices=[],
        validators=[Optional()],
        validate_choice=False,
    )
    executor_id = SelectField("Исполнитель", choices=[], validators=[Optional()])
    submit = SubmitField("Сохранить")


class AssignMasterForm(FlaskForm):
    master_id = SelectField(
        "Мастер",
        choices=[],
        validators=[DataRequired(message="Выберите мастера")],
        validate_choice=False,
    )
    submit = SubmitField("Передать мастеру")


class RequestCommentForm(FlaskForm):
    body = TextAreaField("Комментарий", validators=[DataRequired(), Length(max=5000)])
    submit = SubmitField("Добавить комментарий")


class RequestMaterialForm(FlaskForm):
    name = StringField("Материал", validators=[DataRequired(), Length(max=255)])
    unit = StringField("Ед. изм.", validators=[DataRequired(), Length(max=30)], default="шт")
    quantity = DecimalField(
        "Количество",
        validators=[DataRequired(), NumberRange(min=Decimal("0.001"))],
        places=3,
    )
    price = DecimalField(
        "Цена",
        validators=[DataRequired(), NumberRange(min=Decimal("0"))],
        places=2,
    )
    notes = StringField("Примечание", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Добавить")


class RequestAttachmentForm(FlaskForm):
    files = MultipleFileField("Файлы", validators=[DataRequired(message="Выберите хотя бы один файл")])
    submit = SubmitField("Загрузить")


class DispatcherForm(FlaskForm):
    name = StringField("ФИО диспетчера", validators=[DataRequired(), Length(max=255)])
    sort_order = IntegerField(
        "Порядок",
        validators=[Optional(), NumberRange(min=0, max=9999)],
        default=0,
    )
    is_active = BooleanField("Активен", default=True)
    submit = SubmitField("Сохранить")

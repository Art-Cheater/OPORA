"""Формы модуля заявок."""

from __future__ import annotations

from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import (
    DecimalField,
    MultipleFileField,
    SelectField,
    StringField,
    SubmitField,
    TelField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models.enums import Priority


class RequestFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional(), Length(max=255)])
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
    responsible_id = SelectField("Ответственный мастер", choices=[], validators=[Optional()])
    executor_id = SelectField("Исполнитель", choices=[], validators=[Optional()])
    preset = SelectField(
        "Быстрый фильтр",
        choices=[
            ("", "Все заявки"),
            ("for_emergency", "Новые"),
            ("awaiting_master", "Выехала бригада"),
            ("my", "Мои заявки"),
            ("in_progress", "У мастера"),
            ("completed", "Выполненные"),
        ],
        validators=[Optional()],
        default="",
    )
    sort_by = SelectField(
        "Сортировка",
        choices=[
            ("created_at", "По дате создания"),
            ("updated_at", "По дате обновления"),
            ("number", "По номеру"),
            ("priority", "По приоритету"),
            ("title", "По названию"),
        ],
        default="created_at",
    )
    sort_dir = SelectField(
        "Направление",
        choices=[("desc", "Сначала новые"), ("asc", "Сначала старые")],
        default="desc",
    )


class RequestForm(FlaskForm):
    number = StringField("Номер", validators=[DataRequired(), Length(max=50)])
    title = StringField("Название", validators=[DataRequired(), Length(max=500)])
    description = TextAreaField("Описание", validators=[Optional(), Length(max=10000)])
    address = StringField("Адрес", validators=[DataRequired(), Length(max=500)])
    latitude = DecimalField("Широта", validators=[Optional()], places=7)
    longitude = DecimalField("Долгота", validators=[Optional()], places=7)
    phone = TelField("Телефон", validators=[Optional(), Length(max=30)])
    applicant_name = StringField("ФИО заявителя", validators=[DataRequired(), Length(max=255)])
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
    responsible_id = SelectField(
        "Ответственный мастер",
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
        default=Decimal("1"),
    )
    price = DecimalField(
        "Цена",
        validators=[DataRequired(), NumberRange(min=Decimal("0"))],
        places=2,
        default=Decimal("0"),
    )
    notes = StringField("Примечание", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Добавить материал")


class RequestAttachmentForm(FlaskForm):
    files = MultipleFileField("Файлы", validators=[DataRequired(message="Выберите хотя бы один файл")])
    submit = SubmitField("Загрузить файлы")

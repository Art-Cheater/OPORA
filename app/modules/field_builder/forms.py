"""Формы конструктора полей."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, Regexp

from app.models.custom_fields.constants import (
    CUSTOM_FIELD_MODULES,
    CUSTOM_FIELD_MODULE_LABELS,
    FIELD_TYPES,
    FIELD_TYPE_LABELS,
)


class CustomFieldForm(FlaskForm):
    module_code = SelectField("Модуль", choices=[], validators=[DataRequired()])
    code = StringField(
        "Системный код",
        validators=[
            DataRequired(message="Укажите код."),
            Length(min=2, max=100),
            Regexp(
                r"^[a-z][a-z0-9_]*$",
                message="Латиница, цифры, _, начинается с буквы.",
            ),
        ],
    )
    name = StringField("Название", validators=[DataRequired(), Length(max=150)])
    field_type = SelectField(
        "Тип",
        choices=[(t, FIELD_TYPE_LABELS[t]) for t in FIELD_TYPES],
        validators=[DataRequired()],
    )
    description = TextAreaField("Описание", validators=[Optional(), Length(max=2000)])
    is_required = BooleanField("Обязательное")
    is_visible = BooleanField("Видимость", default=True)
    sort_order = IntegerField("Порядок", default=0, validators=[Optional()])
    options_text = TextAreaField(
        "Варианты списка",
        validators=[Optional()],
        description="По одному на строку: код|Название (например: new|Новый)",
    )
    submit = SubmitField("Сохранить")

    is_edit = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.module_code.choices = [
            (c, CUSTOM_FIELD_MODULE_LABELS.get(c, c)) for c in CUSTOM_FIELD_MODULES
        ]

"""Формы модуля ролей."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, Regexp, ValidationError


class RoleFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional(), Length(max=255)])
    sort_by = SelectField(
        "Сортировка",
        choices=[("name", "По названию"), ("code", "По коду"), ("created_at", "По дате")],
        default="name",
        validate_choice=False,
    )
    sort_dir = SelectField(
        "Направление",
        choices=[("asc", "По возрастанию"), ("desc", "По убыванию")],
        default="asc",
    )


class RoleForm(FlaskForm):
    code = StringField(
        "Код",
        validators=[
            DataRequired(message="Укажите код роли."),
            Length(max=50),
            Regexp(r"^[a-z][a-z0-9_]*$", message="Код: латиница, цифры и _, начинается с буквы."),
        ],
    )
    name = StringField(
        "Название",
        validators=[DataRequired(message="Укажите название роли."), Length(max=100)],
    )
    description = TextAreaField("Описание", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Сохранить")

    is_edit = False
    is_system = False

    def validate_code(self, field):
        if self.is_edit and self.is_system:
            return
        if not field.data:
            return
        value = field.data.strip().lower()
        field.data = value

"""Формы модуля сотрудников."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectField, SelectMultipleField, StringField, SubmitField, TelField
from wtforms.validators import DataRequired, Email, Length, Optional, ValidationError


class EmployeeFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional(), Length(max=255)])
    role_id = SelectField("Роль", choices=[], validators=[Optional()])
    status = SelectField(
        "Статус",
        choices=[
            ("", "Все"),
            ("active", "Активен"),
            ("blocked", "Заблокирован"),
            ("inactive", "Деактивирован"),
        ],
        validators=[Optional()],
    )
    department = StringField("Подразделение", validators=[Optional(), Length(max=255)])
    sort_by = SelectField(
        "Сортировка",
        choices=[
            ("full_name", "По ФИО"),
            ("created_at", "По дате создания"),
            ("email", "По email"),
            ("department", "По подразделению"),
            ("position", "По должности"),
        ],
        default="full_name",
        validate_choice=False,
    )
    sort_dir = SelectField(
        "Направление",
        choices=[("asc", "По возрастанию"), ("desc", "По убыванию")],
        default="asc",
    )


class EmployeeForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[
            DataRequired(message="Укажите email."),
            Email(message="Некорректный формат email."),
            Length(max=255),
        ],
    )
    full_name = StringField(
        "ФИО",
        validators=[DataRequired(message="Укажите ФИО."), Length(max=255)],
    )
    phone = TelField("Телефон", validators=[Optional(), Length(max=50)])
    position_id = SelectField("Должность", choices=[], validators=[Optional()])
    department = StringField("Подразделение", validators=[Optional(), Length(max=255)])
    role_ids = SelectMultipleField(
        "Роли",
        choices=[],
        validators=[DataRequired(message="Выберите хотя бы одну роль.")],
    )
    password = PasswordField(
        "Пароль",
        validators=[
            Optional(),
            Length(min=6, max=128, message="Пароль должен содержать от 6 до 128 символов."),
        ],
    )
    submit = SubmitField("Сохранить")

    def validate_password(self, field):
        if not self.is_edit and not (field.data and field.data.strip()):
            raise ValidationError("Пароль обязателен при создании сотрудника (минимум 6 символов).")

    is_edit = False

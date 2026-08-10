"""Формы модуля auth."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError


class LoginForm(FlaskForm):
    """Форма входа в систему."""

    email = StringField(
        "Email",
        validators=[
            DataRequired(message="Введите email."),
            Email(message="Некорректный формат email.", check_deliverability=False),
        ],
        render_kw={"placeholder": "admin@opora.ru", "autofocus": True},
    )
    password = PasswordField(
        "Пароль",
        validators=[
            DataRequired(message="Введите пароль."),
            Length(min=6, message="Пароль должен содержать минимум 6 символов."),
        ],
        render_kw={"placeholder": "••••••••"},
    )
    remember = BooleanField("Запомнить меня")
    submit = SubmitField("Войти")


class ChangePasswordForm(FlaskForm):
    """Форма смены пароля."""

    current_password = PasswordField(
        "Текущий пароль",
        validators=[DataRequired(message="Введите текущий пароль.")],
        render_kw={"placeholder": "••••••••", "autocomplete": "current-password"},
    )
    new_password = PasswordField(
        "Новый пароль",
        validators=[
            DataRequired(message="Введите новый пароль."),
            Length(min=8, message="Пароль должен содержать минимум 8 символов."),
        ],
        render_kw={"placeholder": "••••••••", "autocomplete": "new-password"},
    )
    confirm_password = PasswordField(
        "Подтверждение пароля",
        validators=[
            DataRequired(message="Подтвердите новый пароль."),
            EqualTo("new_password", message="Пароли не совпадают."),
        ],
        render_kw={"placeholder": "••••••••", "autocomplete": "new-password"},
    )
    submit = SubmitField("Сменить пароль")


class ProfileForm(FlaskForm):
    """Форма редактирования профиля."""

    full_name = StringField(
        "ФИО",
        validators=[
            DataRequired(message="Введите ФИО."),
            Length(max=255, message="Слишком длинное значение."),
        ],
    )
    phone = StringField(
        "Телефон",
        validators=[Length(max=50)],
        render_kw={"placeholder": "+7 (___) ___-__-__"},
    )
    position = StringField(
        "Должность",
        validators=[Length(max=255)],
    )
    department = StringField(
        "Подразделение",
        validators=[Length(max=255)],
    )
    submit = SubmitField("Сохранить")


class BlockUserForm(FlaskForm):
    """Форма блокировки пользователя."""

    reason = TextAreaField(
        "Причина блокировки",
        validators=[
            DataRequired(message="Укажите причину блокировки."),
            Length(max=1000),
        ],
        render_kw={"rows": 3},
    )
    submit = SubmitField("Заблокировать")

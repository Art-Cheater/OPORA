"""Формы журнала действий."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, StringField
from wtforms.validators import Optional

from app.core.audit_service import ACTION_LABELS, ENTITY_LABELS


class AuditFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional()])
    user_id = SelectField("Пользователь", choices=[], validators=[Optional()])
    action = SelectField(
        "Действие",
        choices=[("", "Все действия")]
        + [(k, v) for k, v in sorted(ACTION_LABELS.items(), key=lambda x: x[1])],
        validators=[Optional()],
    )
    entity_type = SelectField(
        "Объект",
        choices=[("", "Все объекты")]
        + [(k, v) for k, v in sorted(ENTITY_LABELS.items(), key=lambda x: x[1])],
        validators=[Optional()],
    )
    date_from = DateField("Дата с", validators=[Optional()], format="%Y-%m-%d")
    date_to = DateField("Дата по", validators=[Optional()], format="%Y-%m-%d")

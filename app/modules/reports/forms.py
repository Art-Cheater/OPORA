"""Формы модуля отчётов."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, SubmitField
from wtforms.validators import Optional


class RequestsReportForm(FlaskForm):
    period = SelectField(
        "Период",
        choices=[
            ("week", "Прошедшая неделя"),
            ("month", "Прошедший месяц"),
            ("custom", "Свой период"),
        ],
        default="week",
    )
    date_from = DateField("С", validators=[Optional()], format="%Y-%m-%d")
    date_to = DateField("По", validators=[Optional()], format="%Y-%m-%d")
    submit = SubmitField("Показать")

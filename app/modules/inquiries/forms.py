"""Формы обращений."""

from flask_wtf import FlaskForm
from wtforms import SelectField, StringField
from wtforms.validators import Length, Optional


class InquiryFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional(), Length(max=255)])
    status = SelectField(
        "Статус",
        choices=[
            ("", "Все"),
            ("new", "Новые"),
            ("seen", "Просмотренные"),
            ("done", "Обработанные"),
        ],
        validators=[Optional()],
    )

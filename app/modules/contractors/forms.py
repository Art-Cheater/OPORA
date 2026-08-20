"""Формы справочника подрядчиков."""

from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional, Regexp


class ContractorFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional(), Length(max=255)])


class ContractorForm(FlaskForm):
    name = StringField("Наименование", validators=[DataRequired(), Length(max=500)])
    inn = StringField(
        "ИНН",
        validators=[Optional(), Length(max=12), Regexp(r"^\d{0,12}$", message="ИНН — только цифры")],
    )
    kpp = StringField("КПП", validators=[Optional(), Length(max=9)])
    kpp_largest = StringField("КПП крупнейшего", validators=[Optional(), Length(max=9)])
    address = StringField("Адрес", validators=[Optional(), Length(max=1000)])
    phone = StringField("Телефон", validators=[Optional(), Length(max=50)])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=255)])
    notes = TextAreaField("Заметки", validators=[Optional(), Length(max=5000)])
    submit = SubmitField("Сохранить")

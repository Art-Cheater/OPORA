"""Формы модуля договоров на опорах."""

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import StringField, SubmitField
from wtforms.validators import Length, Optional


class AgreementFilterForm(FlaskForm):
    q = StringField("Адрес или договор", validators=[Optional(), Length(max=255)])


class AgreementUploadForm(FlaskForm):
    file = FileField(
        "Файл Word",
        validators=[
            FileRequired("Выберите файл .docx"),
            FileAllowed(["docx"], "Нужен файл Word (.docx)"),
        ],
    )
    submit = SubmitField("Загрузить")

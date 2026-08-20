"""Формы модуля договоров на опорах."""

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import StringField, SubmitField
from wtforms.validators import Length, Optional


class AgreementFilterForm(FlaskForm):
    q = StringField("Адрес или договор", validators=[Optional(), Length(max=255)])


class AgreementUploadForm(FlaskForm):
    file = FileField(
        "Файл договора",
        validators=[
            FileRequired("Выберите файл договора"),
            FileAllowed(
                ["docx", "doc", "docm", "odt", "rtf", "pdf"],
                "Нужен Word (.doc/.docx), OpenDocument, RTF или PDF",
            ),
        ],
    )
    submit = SubmitField("Загрузить")

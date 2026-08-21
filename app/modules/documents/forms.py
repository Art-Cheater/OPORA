"""Формы загрузки личных документов."""

from flask_wtf import FlaskForm
from wtforms import MultipleFileField, SubmitField
from wtforms.validators import DataRequired


class PersonalDocumentForm(FlaskForm):
    files = MultipleFileField(
        "Файлы",
        validators=[DataRequired(message="Выберите хотя бы один файл")],
    )
    submit = SubmitField("Загрузить")

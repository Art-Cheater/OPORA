"""Формы загрузки личных документов и договоров."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, DateField, MultipleFileField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class PersonalDocumentForm(FlaskForm):
    files = MultipleFileField(
        "Файлы",
        validators=[DataRequired(message="Выберите хотя бы один файл")],
    )
    submit = SubmitField("Загрузить")


class PersonalContractUploadForm(FlaskForm):
    files = MultipleFileField(
        "Файлы договоров",
        validators=[DataRequired(message="Выберите хотя бы один файл")],
    )
    submit = SubmitField("Загрузить договор")


class PersonalContractEditForm(FlaskForm):
    title = StringField("Название", validators=[DataRequired(), Length(max=500)])
    description = TextAreaField("Краткое описание", validators=[Optional(), Length(max=2000)])
    ends_on = DateField("Дата окончания", validators=[Optional()], format="%Y-%m-%d")
    reminders_enabled = BooleanField("Напоминать о сроке", default=True)
    submit = SubmitField("Сохранить")


class ContractsFeatureForm(FlaskForm):
    enabled = BooleanField("Включить раздел «Договоры»")
    submit = SubmitField("Сохранить")

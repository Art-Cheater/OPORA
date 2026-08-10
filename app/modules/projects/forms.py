"""Формы модуля проектов."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    IntegerField,
    MultipleFileField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models.enums import ProjectDocumentType, ProjectStatus


PROJECT_STATUS_CHOICES = [
    (ProjectStatus.DRAFT.value, "Черновик"),
    (ProjectStatus.ACTIVE.value, "В работе"),
    (ProjectStatus.ON_HOLD.value, "Приостановлен"),
    (ProjectStatus.COMPLETED.value, "Завершён"),
    (ProjectStatus.ARCHIVED.value, "Архив"),
]

DOCUMENT_TYPE_CHOICES = [
    (ProjectDocumentType.CONTRACT.value, "Договор"),
    (ProjectDocumentType.ACT.value, "Акт"),
    (ProjectDocumentType.ORDER.value, "Приказ"),
    (ProjectDocumentType.PLAN.value, "План"),
    (ProjectDocumentType.OTHER.value, "Прочее"),
]


class ProjectFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional(), Length(max=255)])
    status = SelectField(
        "Статус",
        choices=[("", "Все статусы")] + PROJECT_STATUS_CHOICES,
        validators=[Optional()],
    )
    responsible_id = SelectField("Ответственный", choices=[], validators=[Optional()])
    executor_id = SelectField("Исполнитель", choices=[], validators=[Optional()])
    date_from = DateField("Дата с", validators=[Optional()], format="%Y-%m-%d")
    date_to = DateField("Дата по", validators=[Optional()], format="%Y-%m-%d")
    sort_by = SelectField(
        "Сортировка",
        choices=[
            ("created_at", "По дате создания"),
            ("updated_at", "По дате обновления"),
            ("name", "По названию"),
            ("code", "По коду"),
            ("status", "По статусу"),
            ("progress_percent", "По готовности"),
            ("start_date", "По дате начала"),
            ("end_date", "По дате окончания"),
        ],
        default="created_at",
    )
    sort_dir = SelectField(
        "Направление",
        choices=[("desc", "Сначала новые"), ("asc", "Сначала старые")],
        default="desc",
    )


class ProjectForm(FlaskForm):
    code = StringField("Код", validators=[DataRequired(), Length(max=50)])
    name = StringField("Название", validators=[DataRequired(), Length(max=500)])
    description = TextAreaField("Описание", validators=[Optional(), Length(max=10000)])
    status = SelectField("Статус", choices=PROJECT_STATUS_CHOICES, validators=[DataRequired()])
    progress_percent = IntegerField(
        "Процент готовности",
        validators=[DataRequired(), NumberRange(min=0, max=100)],
        default=0,
    )
    start_date = DateField("Дата начала", validators=[Optional()], format="%Y-%m-%d")
    end_date = DateField("Дата окончания", validators=[Optional()], format="%Y-%m-%d")
    responsible_id = SelectField("Ответственный", choices=[], validators=[Optional()])
    executor_ids = SelectMultipleField("Исполнители", choices=[], validators=[Optional()])
    submit = SubmitField("Сохранить")


class ProjectCommentForm(FlaskForm):
    body = TextAreaField("Комментарий", validators=[DataRequired(), Length(max=5000)])
    submit = SubmitField("Добавить комментарий")


class ProjectDocumentForm(FlaskForm):
    title = StringField("Название", validators=[DataRequired(), Length(max=500)])
    document_type = SelectField(
        "Тип документа",
        choices=DOCUMENT_TYPE_CHOICES,
        validators=[DataRequired()],
    )
    document_number = StringField("Номер", validators=[Optional(), Length(max=100)])
    document_date = DateField("Дата документа", validators=[Optional()], format="%Y-%m-%d")
    description = TextAreaField("Описание", validators=[Optional(), Length(max=5000)])
    files = MultipleFileField("Файлы", validators=[Optional()])
    submit = SubmitField("Добавить документ")


class ProjectAttachmentForm(FlaskForm):
    files = MultipleFileField("Файлы", validators=[DataRequired(message="Выберите хотя бы один файл")])
    submit = SubmitField("Загрузить файлы")

"""Формы модуля дефектов."""

from flask_wtf import FlaskForm
from wtforms import (
    HiddenField,
    MultipleFileField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Optional

from app.modules.requests.districts import district_choices


class DefectFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional(), Length(max=255)])
    district = SelectField(
        "Район",
        choices=district_choices(empty_label="Любой"),
        validators=[Optional()],
        validate_choice=False,
    )
    status_id = SelectField("Статус", choices=[], validators=[Optional()])
    category_id = SelectField("Категория", choices=[], validators=[Optional()])
    sort_by = SelectField(
        "Сортировка",
        choices=[
            ("created_at", "По дате создания"),
            ("number", "По номеру"),
            ("address", "По адресу"),
            ("status_id", "По статусу"),
        ],
        default="created_at",
        validate_choice=False,
    )
    sort_dir = SelectField(
        "Направление",
        choices=[("desc", "Сначала новые"), ("asc", "Сначала старые")],
        default="desc",
    )


class DefectForm(FlaskForm):
    number = StringField("Номер", validators=[DataRequired(), Length(max=50)])
    description = TextAreaField("Описание", validators=[DataRequired(), Length(max=10000)])
    category_id = SelectField("Категория", choices=[], validators=[DataRequired()], validate_choice=False)
    address = StringField("Адрес", validators=[DataRequired(), Length(max=500)])
    address_selection_token = HiddenField(validators=[Optional()])
    original_address = HiddenField(validators=[Optional(), Length(max=500)])
    normalized_address = HiddenField(validators=[Optional(), Length(max=1000)])
    region = HiddenField(validators=[Optional(), Length(max=255)])
    district = SelectField(
        "Район",
        choices=district_choices(empty_label="Не указан"),
        validators=[Optional()],
        validate_choice=False,
    )
    settlement = HiddenField(validators=[Optional(), Length(max=255)])
    street = HiddenField(validators=[Optional(), Length(max=500)])
    house = HiddenField(validators=[Optional(), Length(max=100)])
    pp = StringField("ПП (пункт питания)", validators=[Optional(), Length(max=255)])
    address_source = HiddenField(validators=[Optional(), Length(max=50)])
    address_external_id = HiddenField(validators=[Optional(), Length(max=255)])
    latitude = HiddenField(validators=[Optional()])
    longitude = HiddenField(validators=[Optional()])
    responsible_id = SelectField("Ответственный", choices=[], validators=[Optional()], validate_choice=False)
    submit = SubmitField("Сохранить")


class DefectStatusForm(FlaskForm):
    status_code = SelectField("Статус", choices=[], validators=[DataRequired()], validate_choice=False)
    comment = TextAreaField("Комментарий", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Сменить статус")


class DefectCommentForm(FlaskForm):
    body = TextAreaField("Комментарий", validators=[DataRequired(), Length(max=5000)])
    submit = SubmitField("Добавить")


class DefectAttachmentForm(FlaskForm):
    files = MultipleFileField("Файлы", validators=[DataRequired(message="Выберите хотя бы один файл")])
    submit = SubmitField("Загрузить")

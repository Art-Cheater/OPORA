"""Формы путевых листов."""

from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, SelectMultipleField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class WaybillFilterForm(FlaskForm):
    q = StringField("Поиск", validators=[Optional(), Length(max=255)])
    status = SelectField(
        "Статус",
        choices=[("", "Все")] + [("draft", "Черновик"), ("in_progress", "В работе"), ("completed", "Выполнен"), ("cancelled", "Отменён")],
        validators=[Optional()],
    )
    sort_by = SelectField(
        "Сортировка",
        choices=[("work_date", "По дате"), ("created_at", "По созданию"), ("number", "По номеру")],
        default="work_date",
        validate_choice=False,
    )
    sort_dir = SelectField(
        "Направление",
        choices=[("desc", "Сначала новые"), ("asc", "Сначала старые")],
        default="desc",
    )


class WaybillForm(FlaskForm):
    number = StringField("Номер", validators=[DataRequired(), Length(max=50)])
    work_date = DateField("Дата", validators=[DataRequired()])
    master_id = SelectField("Мастер", choices=[], validators=[DataRequired()], validate_choice=False)
    member_ids = SelectMultipleField("Исполнители", choices=[], validators=[Optional()], validate_choice=False)
    comment = TextAreaField("Комментарий", validators=[Optional(), Length(max=5000)])
    submit = SubmitField("Сохранить")


class WaybillStatusForm(FlaskForm):
    status = SelectField("Статус", choices=[], validators=[DataRequired()], validate_choice=False)
    submit = SubmitField("Сменить статус")


class WaybillStopForm(FlaskForm):
    entity_type = SelectField(
        "Тип",
        choices=[("request", "Заявка"), ("defect", "Дефект")],
        validators=[DataRequired()],
    )
    entity_id = StringField("ID", validators=[DataRequired()])
    comment = TextAreaField("Комментарий к точке", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Добавить")

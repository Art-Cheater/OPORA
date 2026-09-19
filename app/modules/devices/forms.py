"""Forms for the administrative device inventory."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, Regexp, ValidationError


class DeviceForm(FlaskForm):
    name = StringField("Название", validators=[DataRequired(message="Укажите название."), Length(max=255)])
    device_id = StringField("Device ID", validators=[DataRequired(message="Укажите Device ID."), Length(max=100), Regexp(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", message="Используйте буквы, цифры, точку, дефис или подчёркивание.")])
    secret = PasswordField("Device Secret", validators=[Optional(), Length(max=512)])
    protocol_version = SelectField("Протокол", choices=[("1", "v1: JSON"), ("2", "v2: text")], default="1", validators=[DataRequired()])
    enabled = BooleanField("Активна", default=True)
    submit = SubmitField("Сохранить")
    is_edit = False

    def validate_secret(self, field):
        if not self.is_edit and not (field.data or "").strip():
            raise ValidationError("Device Secret обязателен при добавлении платы.")

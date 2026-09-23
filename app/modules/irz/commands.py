"""Allow-listed read-only Mercury 230 commands (mercury-base 1.6 + project parsers)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

PROTOCOL = "Инкотекс, «Описание системы команд приборов учета Меркурий», вер. 06.2024"


@dataclass(frozen=True)
class CommandSpec:
    id: str
    title: str
    mercury_command: str
    description: str
    category: str = "Основное"
    mode: str = "read"
    dangerous: bool = False
    timeout: float = 5.0
    parameters: tuple[dict[str, Any], ...] = ()
    models: tuple[str, ...] = ("230",)
    available: bool = True
    limitation: str | None = None
    poll: bool = False
    command_code: int = 0x08
    subcommand: int | None = None
    units: str | None = None
    safe_read_only: bool = True
    fixture_tested: bool = False
    physical_verified: bool = False
    request: str | None = None
    response_length: int | None = None
    needs_channel: bool = True
    source: str | None = None

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["parameters"] = list(self.parameters)
        value["models"] = list(self.models)
        return value


def _ext(command_id: str, title: str, description: str, category: str, request: str, section: str, **kwargs) -> CommandSpec:
    return CommandSpec(command_id, title, f"ext:{command_id}", description, category, request=request,
                       source=f"{PROTOCOL}, {section}", fixture_tested=True, **kwargs)


COMMANDS: dict[str, CommandSpec] = {
    "serial_and_manufacture": CommandSpec(
        id="serial_and_manufacture",
        title="Серийный номер и дата выпуска",
        mercury_command="get_serial_number_and_date_of_manufacture",
        description="Чтение серийного номера и даты изготовления.",
        poll=True,
        subcommand=0x00,
        request="08 00",
        response_length=7,
        needs_channel=False,
        source=f"{PROTOCOL}, §4.4.2; parser mercury-base 1.6",
        fixture_tested=True,
        physical_verified=True,
    ),
    "firmware_version": CommandSpec(
        id="firmware_version",
        title="Версия ПО",
        mercury_command="get_firmware_version",
        description="Версия встроенного программного обеспечения.",
        category="Диагностика",
        poll=True,
        subcommand=0x03,
        request="08 03",
        response_length=3,
        source=f"{PROTOCOL}, §4.4.5; parser mercury-base 1.6",
        fixture_tested=True,
        physical_verified=True,
    ),
    "transformation_ratios": _ext(
        "transformation_ratios", "Коэффициенты трансформации",
        "Кн и Кт — два двоичных байта каждый.", "Параметры", "08 02", "§4.4.4",
        poll=True, subcommand=0x02, response_length=4,
        limitation="Запрос физически подтверждён; полный 7-байтный ответ требует повторной записи",
    ),
    "additional_timeout_multiplier": CommandSpec(
        id="additional_timeout_multiplier",
        title="Множитель дополнительного тайм-аута",
        mercury_command="get_additional_timeout_multiplier",
        description="Служебный множитель дополнительного тайм-аута.",
        category="Диагностика",
        subcommand=0x04,
        request="08 04",
        response_length=2,
        source=f"{PROTOCOL}, §4.4.6.1; parser mercury-base 1.6",
    ),
    "main_timeout_multiplier": CommandSpec(
        id="main_timeout_multiplier",
        title="Множитель основного тайм-аута",
        mercury_command="get_main_timeout_multiplier",
        description="Служебный множитель основного тайм-аута.",
        category="Диагностика",
        subcommand=0x1D,
        request="08 1D",
        response_length=2,
        source=f"{PROTOCOL}, §4.4.6.2; parser mercury-base 1.6",
    ),
    "passport": CommandSpec(
        id="passport",
        title="Паспорт прибора",
        mercury_command="get_passport",
        description="Паспортные данные прибора.",
        available=False,
        limitation="mercury-base 1.6 передаёт 0x0100 в bytes() и команда завершается ValueError",
        subcommand=0x0100,
    ),
    "device_info": _ext(
        "device_info", "Информация о модели", "Определение модели и возможностей.", "Диагностика",
        "08 12", "§4.4.16.1", subcommand=0x12, response_length=6,
        limitation="Определяет capabilities, но не заменяет полную маркировку с корпуса",
    ),
    "voltage_phases": _ext(
        "voltage_phases", "Напряжение по фазам", "U A/B/C, текущие значения.", "Электрические параметры",
        "08 16 11 (резерв: 08 11 11/12/13)", "§4.4.15, рис. 4.28", poll=True, subcommand=0x16, units="V",
        response_length=9),
    "current_phases": _ext(
        "current_phases", "Ток по фазам", "I A/B/C, текущие значения.", "Электрические параметры",
        "08 16 21 (резерв: 08 11 21/22/23)", "§4.4.15, рис. 4.28", poll=True, subcommand=0x16, units="A",
        response_length=9),
    "active_power": _ext(
        "active_power", "Активная мощность", "P Σ/A/B/C со знаком направления.", "Электрические параметры",
        "08 16 00 (резерв: 08 11 00…03)", "§4.4.15.2.1, рис. 4.26", poll=True, subcommand=0x16, units="W",
        response_length=12),
    "reactive_power": _ext(
        "reactive_power", "Реактивная мощность", "Q Σ/A/B/C со знаком направления.", "Электрические параметры",
        "08 16 04 (резерв: 08 11 04…07)", "§4.4.15.2.1, рис. 4.26", poll=True, subcommand=0x16, units="var",
        response_length=12),
    "apparent_power": _ext(
        "apparent_power", "Полная мощность", "S Σ/A/B/C.", "Электрические параметры",
        "08 16 08 (резерв: 08 11 08…0B)", "§4.4.15.2.1, рис. 4.26", poll=True, subcommand=0x16, units="VA",
        response_length=12),
    "power_factor": _ext(
        "power_factor", "Коэффициент мощности", "cos φ Σ/A/B/C.", "Электрические параметры",
        "08 16 30 (резерв: 08 11 30…33)", "§4.4.15.2.3, рис. 4.29", poll=True, subcommand=0x16, units="1",
        response_length=12),
    "frequency": _ext(
        "frequency", "Частота", "Частота сети.", "Электрические параметры",
        "08 11 40", "§4.4.15.2.4, рис. 4.30", poll=True, subcommand=0x11, units="Hz", response_length=3),
    "phase_angles": _ext(
        "phase_angles", "Углы между фазными напряжениями", "Углы U1-U2, U1-U3, U2-U3.", "Электрические параметры",
        "08 16 51 (резерв: 08 11 51/52/53)", "§4.4.15.2.2, рис. 4.28", poll=True, subcommand=0x16, units="deg",
        response_length=9),
    "energy_current": _ext(
        "energy_current", "Энергия от сброса, сумма тарифов", "A+/A-/R+/R- нарастающим итогом.", "Энергия",
        "05 00 00", "§4.3.1, табл. 4.6, рис. 4.11", poll=True, command_code=0x05, subcommand=0x00,
        units="Wh/varh", response_length=16),
    "energy_tariffs": _ext(
        "energy_tariffs", "Энергия от сброса по тарифам", "A+/A-/R+/R- по тарифам T1…T4.", "Энергия",
        "05 00 01…04", "§4.3.1, табл. 4.6", poll=True, command_code=0x05, subcommand=0x00,
        units="Wh/varh", response_length=16, timeout=5.0),
    "meter_time": _ext(
        "meter_time", "Время счётчика", "Текущие дата и время внутренних часов.", "Диагностика",
        "04 00", "§4.2.2", poll=True, command_code=0x04, subcommand=0x00, response_length=8),
    "status_word": _ext(
        "status_word", "Слово состояния", "Самодиагностика E-01…E-48.", "Диагностика",
        "08 0A", "§4.4.12, приложение А", poll=True, subcommand=0x0A, response_length=6,
        limitation="Порядок байт E-01…E-08 подтверждён примерами протокола; остальные — выведены, требуют проверки"),
    "events": _ext(
        "events", "Журналы событий", "Последняя запись основных журналов.", "События",
        "04 NN FF", "§4.2.1–4.2.12", command_code=0x04, timeout=5.0),
    "energy_archive": _ext(
        "energy_archive", "Архив энергии", "A+/A-/R+/R- за год, месяц, сутки.", "Архивы",
        "05 {массив|месяц} {тариф}", "§4.3.1, табл. 4.6", command_code=0x05, units="Wh/varh", response_length=16,
        parameters=({"name": "period", "values": ["reset", "year", "prev_year", "month", "day", "prev_day"]},
                    {"name": "month", "min": 1, "max": 12}, {"name": "tariff", "min": 0, "max": 4})),
}

POLL_ORDER = (
    "serial_and_manufacture", "firmware_version", "transformation_ratios",
    "voltage_phases", "current_phases", "frequency", "active_power", "reactive_power",
    "apparent_power", "power_factor", "phase_angles", "energy_current", "energy_tariffs",
    "meter_time", "status_word",
)


def poll_commands() -> list[CommandSpec]:
    return [COMMANDS[command_id] for command_id in POLL_ORDER if COMMANDS[command_id].available and COMMANDS[command_id].poll]


def get_command(command_id: object, *, require_available: bool = True) -> CommandSpec:
    if not isinstance(command_id, str) or command_id not in COMMANDS:
        raise KeyError("INVALID_COMMAND")
    command = COMMANDS[command_id]
    if require_available and not command.available:
        raise ValueError("COMMAND_NOT_SUPPORTED")
    return command


def command_list(*, include_unavailable: bool = True) -> list[dict[str, Any]]:
    return [
        spec.public_dict()
        for spec in COMMANDS.values()
        if include_unavailable or spec.available
    ]


def normalize_result(value: Any) -> Any:
    """Convert mercury-base return values to JSON-safe data without rescaling."""
    from datetime import date, datetime, time
    from decimal import Decimal

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex(" ").upper()
    if isinstance(value, dict):
        return {str(key): normalize_result(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [normalize_result(item) for item in value]
    raise TypeError(f"Unsupported Mercury result type: {type(value).__name__}")

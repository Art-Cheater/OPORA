"""Allow-listed Mercury V2 commands exposed by mercury-base 1.6."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable


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
    models: tuple[str, ...] = ("203.2TD", "204", "208", "230", "231", "234", "236", "238")
    available: bool = True
    limitation: str | None = None
    poll: bool = False
    command_code: int = 0x08
    subcommand: int | None = None
    units: str | None = None
    safe_read_only: bool = True
    fixture_tested: bool = False
    physical_verified: bool = False

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["parameters"] = list(self.parameters)
        value["models"] = list(self.models)
        return value


COMMANDS: dict[str, CommandSpec] = {
    "serial_and_manufacture": CommandSpec(
        id="serial_and_manufacture",
        title="Серийный номер и дата выпуска",
        mercury_command="get_serial_number_and_date_of_manufacture",
        description="Чтение серийного номера и даты изготовления.",
        poll=True,
        subcommand=0x00,
        fixture_tested=True,
        physical_verified=True,
    ),
    "transformation_ratios": CommandSpec(
        id="transformation_ratios",
        title="Коэффициенты трансформации",
        mercury_command="get_transformation_ratios",
        description="Коэффициенты трансформации напряжения и тока.",
        category="Параметры",
        poll=True,
        subcommand=0x02,
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
        fixture_tested=True,
        physical_verified=True,
    ),
    "additional_timeout_multiplier": CommandSpec(
        id="additional_timeout_multiplier",
        title="Множитель дополнительного тайм-аута",
        mercury_command="get_additional_timeout_multiplier",
        description="Служебный множитель дополнительного тайм-аута.",
        category="Диагностика",
        poll=True,
        subcommand=0x04,
    ),
    "main_timeout_multiplier": CommandSpec(
        id="main_timeout_multiplier",
        title="Множитель основного тайм-аута",
        mercury_command="get_main_timeout_multiplier",
        description="Служебный множитель основного тайм-аута.",
        category="Диагностика",
        poll=True,
        subcommand=0x1D,
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
    "device_info": CommandSpec(
        id="device_info",
        title="Информация о модели",
        mercury_command="ext:device_info",
        description="Определение модели и возможностей.",
        available=True,
        limitation="Определяет capabilities, но не заменяет полную маркировку с корпуса",
        subcommand=0x12,
        fixture_tested=True,
    ),
    "voltage_phases": CommandSpec("voltage_phases", "Напряжение по фазам", "ext:voltage_phases",
        "U A/B/C по официальному протоколу.", "Электрические параметры", subcommand=0x14, units="V", fixture_tested=True),
    "current_phases": CommandSpec("current_phases", "Ток по фазам", "ext:current_phases",
        "I A/B/C по официальному протоколу.", "Электрические параметры", subcommand=0x14, units="A", fixture_tested=True),
    "active_power": CommandSpec("active_power", "Активная мощность", "ext:active_power",
        "P total/A/B/C.", "Электрические параметры", subcommand=0x14, units="W", fixture_tested=True),
    "reactive_power": CommandSpec("reactive_power", "Реактивная мощность", "ext:reactive_power",
        "Q total/A/B/C.", "Электрические параметры", subcommand=0x14, units="var", fixture_tested=True),
    "apparent_power": CommandSpec("apparent_power", "Полная мощность", "ext:apparent_power",
        "S total/A/B/C.", "Электрические параметры", subcommand=0x14, units="VA", fixture_tested=True),
    "power_factor": CommandSpec("power_factor", "Коэффициент мощности", "ext:power_factor",
        "cos φ total/A/B/C.", "Электрические параметры", subcommand=0x14, units="1", fixture_tested=True),
    "frequency": CommandSpec("frequency", "Частота", "ext:frequency",
        "Частота сети.", "Электрические параметры", subcommand=0x11, units="Hz", fixture_tested=True),
    "phase_angles": CommandSpec("phase_angles", "Углы между фазами", "ext:phase_angles",
        "Углы AB/AC/BC.", "Электрические параметры", subcommand=0x11, units="deg", fixture_tested=True),
}


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

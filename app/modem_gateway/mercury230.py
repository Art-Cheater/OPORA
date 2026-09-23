"""Read-only Mercury 230 commands from the official Incotex protocol.

Source: НПК «Инкотекс», «Описание системы команд приборов учета Меркурий»,
версия 06.2024. Section numbers in comments refer to that document.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

STATUS_CODES = {
    0x01: ("UNSUPPORTED", "Недопустимая команда или параметр"),
    0x02: ("METER_INTERNAL_ERROR", "Внутренняя ошибка счётчика"),
    0x03: ("ACCESS_DENIED", "Недостаточен уровень доступа"),
    0x04: ("TIME_ALREADY_CORRECTED", "Часы уже корректировались в текущие сутки"),
    0x05: ("CHANNEL_NOT_OPEN", "Не открыт канал связи"),
}

# Appendix A, table A.1. Bit 0 of the first row is E-01.
DIAGNOSTICS = {
    1: "Напряжение батареи менее 2,2 В", 2: "Нарушено функционирование памяти №2",
    3: "Нарушено функционирование UART1", 4: "Нарушено функционирование ADS",
    5: "Ошибка обмена с памятью №1", 6: "Нарушено функционирование RTC",
    7: "Нарушено функционирование памяти №3",
    9: "Ошибка КС программы", 10: "Ошибка КС массива калибровочных коэффициентов",
    11: "Ошибка КС массива регистров учтённой энергии", 12: "Ошибка КС адреса прибора",
    13: "Ошибка КС серийного номера", 14: "Ошибка КС пароля",
    15: "Ошибка КС массива варианта исполнения", 16: "Ошибка КС байта тарификатора",
    17: "Ошибка КС байта управления нагрузкой", 18: "Ошибка КС лимита мощности",
    19: "Ошибка КС лимита энергии", 20: "Ошибка КС байта параметров UART",
    21: "Ошибка КС параметров индикации (по тарифам)", 22: "Ошибка КС параметров индикации (по периодам)",
    23: "Ошибка КС множителя тайм-аута", 24: "Ошибка КС байта программируемых флагов",
    25: "Ошибка КС массива праздничных дней", 26: "Ошибка КС массива тарифного расписания",
    27: "Ошибка КС массива таймера", 28: "Ошибка КС массива сезонных переходов",
    29: "Ошибка КС массива местоположения прибора", 30: "Ошибка КС массива коэффициентов трансформации",
    31: "Ошибка КС массива регистров накопления по периодам", 32: "Ошибка КС параметров среза",
    33: "Ошибка КС регистров среза", 34: "Ошибка КС указателей журнала событий",
    35: "Ошибка КС записи журнала событий", 36: "Ошибка КС регистра учёта технических потерь",
    37: "Ошибка КС мощностей технических потерь", 38: "Ошибка КС регистров учтённой энергии потерь",
    39: "Ошибка КС регистров энергии пофазного учёта", 40: "Флаг поступления широковещательного сообщения",
    41: "Ошибка КС указателей журнала ПКЭ", 42: "Ошибка КС записи журнала ПКЭ",
    43: "Ошибка КС регистров R1-R4", 47: "Флаг выполнения процедуры коррекции времени",
    48: "Напряжение батареи менее 2,65 В",
}

# Six status bytes are three words, most significant word first (§4.2.12). The
# official examples place E-01..E-08 in the fifth byte, i.e. low byte first
# inside each word.
STATUS_BYTE_ROWS = (4, 5, 2, 3, 0, 1)

# §4.2.3–4.2.12: two 6-byte BCD timestamps (start/on, end/off) unless noted.
JOURNALS = (
    ("meter_power", 0x01, "Включение/выключение счётчика", "interval"),
    ("phase_a_voltage", 0x03, "Напряжение фазы A: включение/выключение", "interval"),
    ("phase_b_voltage", 0x04, "Напряжение фазы B: включение/выключение", "interval"),
    ("phase_c_voltage", 0x05, "Напряжение фазы C: включение/выключение", "interval"),
    ("phase_a_current", 0x17, "Ток фазы A: включение/выключение", "interval"),
    ("phase_b_current", 0x18, "Ток фазы B: включение/выключение", "interval"),
    ("phase_c_current", 0x19, "Ток фазы C: включение/выключение", "interval"),
    ("time_correction", 0x02, "Коррекция часов (до/после)", "interval"),
    ("case_open", 0x12, "Вскрытие/закрытие прибора", "interval"),
    ("magnetic", 0x1A, "Воздействие магнитного поля", "interval"),
    ("power_limit", 0x06, "Превышение лимита мощности", "interval"),
    ("reprogramming", 0x13, "Перепрограммирование", "reprogramming"),
    ("status_word", 0x14, "Слово состояния (самодиагностика)", "status_word"),
)
MAX_JOURNAL_TIMEOUTS = 2

# Table 4.6: energy array number in the high nibble, month in the low nibble.
ARCHIVE_PERIODS = {"reset": 0x0, "year": 0x1, "prev_year": 0x2, "month": 0x3, "day": 0x4, "prev_day": 0x5}
ENERGY_KEYS = ("a_plus", "a_minus", "r_plus", "r_minus")


class MercuryStatusError(ValueError):
    """The meter answered with a one-byte exchange status instead of data (table 1.3)."""

    def __init__(self, status: int):
        self.status = status
        self.code, message = STATUS_CODES.get(status & 0x0F, ("PROTOCOL_ERROR", "Ошибка протокола Mercury"))
        super().__init__(message)


def _u24(chunk: list[int]) -> int:
    """3-byte value: 1st (two direction bits masked), 3rd, 2nd byte order (fig. 4.27)."""
    if len(chunk) != 3:
        raise ValueError("UNKNOWN_RESPONSE_FORMAT")
    return ((chunk[0] & 0x3F) << 16) | (chunk[2] << 8) | chunk[1]


def _signed_power(chunk: list[int], reactive: bool) -> Decimal:
    direction_bit = 0x40 if reactive else 0x80
    value = Decimal(_u24(chunk)) / Decimal(100)
    return -value if chunk[0] & direction_bit else value


def _groups(data: list[int], size: int, count: int) -> list[list[int]]:
    if len(data) != size * count:
        raise ValueError("UNKNOWN_RESPONSE_FORMAT")
    return [data[index:index + size] for index in range(0, len(data), size)]


def _energy_value(chunk: list[int]) -> int | None:
    """4-byte energy register in 2nd, 1st, 4th, 3rd byte order (fig. 4.11); masked as FF."""
    if len(chunk) != 4:
        raise ValueError("UNKNOWN_RESPONSE_FORMAT")
    if all(byte == 0xFF for byte in chunk):
        return None
    return (chunk[1] << 24) | (chunk[0] << 16) | (chunk[3] << 8) | chunk[2]


def _energy_block(data: list[int]) -> dict[str, int | None]:
    return {key: _energy_value(raw) for key, raw in zip(ENERGY_KEYS, _groups(data, 4, 4))}


def _bcd(byte: int) -> int:
    high, low = byte >> 4, byte & 0x0F
    if high > 9 or low > 9:
        raise ValueError("UNKNOWN_RESPONSE_FORMAT")
    return high * 10 + low


def _bcd_timestamp(chunk: list[int]) -> str | None:
    """sec, min, hour, day, month, year — all zero means an empty journal record."""
    if len(chunk) != 6:
        raise ValueError("UNKNOWN_RESPONSE_FORMAT")
    if not any(chunk):
        return None
    second, minute, hour, day, month, year = map(_bcd, chunk)
    try:
        return datetime(2000 + year, month, day, hour, minute, second).isoformat()
    except ValueError as exc:
        raise ValueError("UNKNOWN_RESPONSE_FORMAT") from exc


def decode_status_word(data: list[int]) -> dict:
    if len(data) != 6:
        raise ValueError("UNKNOWN_RESPONSE_FORMAT")
    errors = []
    for row, byte_index in enumerate(STATUS_BYTE_ROWS):
        for bit in range(8):
            if data[byte_index] & (1 << bit):
                code = row * 8 + bit + 1
                errors.append({"code": f"E-{code:02d}", "text": DIAGNOSTICS.get(code, "Резерв")})
    return {"raw": bytes(data).hex(" ").upper(), "ok": not errors, "errors": errors}


def _read_phases(meter, bwri: int, count: int, divisor: int, keys: tuple[str, ...], converter=None):
    """Read all phases via 08 16; fall back to per-phase 08 11 if 16h is not supported."""
    try:
        groups = _groups(meter.send_command(0x08, 0x16, bwri, response_length=3 * count), 3, count)
    except MercuryStatusError as exc:
        if exc.code != "UNSUPPORTED":
            raise
        first_phase = 0 if count == 4 else 1
        groups = [meter.send_command(0x08, 0x11, (bwri & 0xFC) | (first_phase + index), response_length=3)
                  for index in range(count)]
        groups = [_groups(item, 3, 1)[0] for item in groups]
    if converter:
        return {key: converter(raw) for key, raw in zip(keys, groups)}
    return {key: Decimal(_u24(raw)) / Decimal(divisor) for key, raw in zip(keys, groups)}


def open_channel_request(level: int, password: bytes) -> tuple[int, ...]:
    if level not in (1, 2) or len(password) != 6:
        raise ValueError("INVALID_PASSWORD")
    return (0x01, level, *password)


def password_candidates(password: str, encoding: str = "auto") -> list[bytes]:
    """Appendix В: meters without index «D» use one byte per digit, «D» meters use ASCII."""
    value = str(password or "").strip()
    if len(value) != 6:
        raise ValueError("INVALID_PASSWORD")
    candidates = []
    if encoding in ("auto", "hex") and value.isdigit():
        candidates.append(bytes(int(char) for char in value))
    if encoding in ("auto", "ascii"):
        candidates.append(value.encode("ascii"))
    if not candidates:
        raise ValueError("INVALID_PASSWORD")
    return candidates


def execute(meter, command_id: str, params: dict | None = None):
    """Execute an allow-listed read-only command through the V2 adapter."""
    params = params or {}
    phases = ("a", "b", "c")
    with_total = ("total", "a", "b", "c")
    if command_id == "transformation_ratios":
        data = meter.send_command(0x08, 0x02, response_length=4)
        if len(data) != 4:
            raise ValueError("UNKNOWN_RESPONSE_FORMAT")
        return {"voltage": (data[0] << 8) | data[1], "current": (data[2] << 8) | data[3]}
    if command_id == "voltage_phases":
        return _read_phases(meter, 0x11, 3, 100, phases)
    if command_id == "current_phases":
        return _read_phases(meter, 0x21, 3, 1000, phases)
    if command_id == "power_factor":
        return _read_phases(meter, 0x30, 4, 1000, with_total)
    if command_id in {"active_power", "reactive_power", "apparent_power"}:
        bwri = {"active_power": 0x00, "reactive_power": 0x04, "apparent_power": 0x08}[command_id]
        if command_id == "apparent_power":
            return _read_phases(meter, bwri, 4, 100, with_total)
        reactive = command_id == "reactive_power"
        return _read_phases(meter, bwri, 4, 100, with_total, lambda raw: _signed_power(raw, reactive))
    if command_id == "frequency":
        data = meter.send_command(0x08, 0x11, 0x40, response_length=3)
        return {"value": Decimal(_u24(data)) / Decimal(100)}
    if command_id == "phase_angles":
        return _read_phases(meter, 0x51, 3, 100, ("ab", "ac", "bc"))
    if command_id == "energy_current":
        return _energy_block(meter.send_command(0x05, 0x00, 0x00, response_length=16))
    if command_id == "energy_tariffs":
        result = {}
        for tariff in range(1, 5):
            try:
                result[f"t{tariff}"] = _energy_block(meter.send_command(0x05, 0x00, tariff, response_length=16))
            except MercuryStatusError as exc:
                if exc.code != "UNSUPPORTED":
                    raise
                result[f"t{tariff}"] = None
        return result
    if command_id == "energy_archive":
        period = params.get("period")
        try:
            month = int(params.get("month") or 0)
            tariff = int(params.get("tariff") or 0)
        except (TypeError, ValueError) as exc:
            raise KeyError("INVALID_PARAMETERS") from exc
        if period not in ARCHIVE_PERIODS or not 0 <= tariff <= 4 or (period == "month" and not 1 <= month <= 12):
            raise KeyError("INVALID_PARAMETERS")
        month = month if period == "month" else 0
        selector = (ARCHIVE_PERIODS[period] << 4) | month
        block = _energy_block(meter.send_command(0x05, selector, tariff, response_length=16))
        return {"period": period, "month": month or None, "tariff": tariff, **block}
    if command_id == "meter_time":
        data = meter.send_command(0x04, 0x00, response_length=8)
        if len(data) != 8:
            raise ValueError("UNKNOWN_RESPONSE_FORMAT")
        second, minute, hour, weekday, day, month, year, season = map(_bcd, data)
        try:
            value = datetime(2000 + year, month, day, hour, minute, second)
        except ValueError as exc:
            raise ValueError("UNKNOWN_RESPONSE_FORMAT") from exc
        return {"value": value.isoformat(), "weekday": weekday, "season": "winter" if season == 1 else "summer"}
    if command_id == "status_word":
        return decode_status_word(meter.send_command(0x08, 0x0A, response_length=6))
    if command_id == "events":
        return {"journals": _read_journals(meter)}
    if command_id == "device_info":
        data = meter.send_command(0x08, 0x12)
        if len(data) not in (6, 8):
            raise ValueError("UNKNOWN_RESPONSE_FORMAT")
        return {
            "raw": bytes(data).hex(" ").upper(),
            "three_phase": not bool(data[1] & 0x10),
            "profile_supported": bool(data[1] & 0x20),
            "tariff_supported": bool(data[2] & 0x40),
            "reactive_energy_supported": not bool(data[2] & 0x20),
            "rs485": ((data[3] >> 2) & 0x03) == 1,
            "power_quality_supported": bool(data[4] & 0x02),
            "per_phase_energy_supported": bool(data[4] & 0x01),
        }
    raise KeyError("INVALID_COMMAND")


def _read_journals(meter) -> list[dict]:
    """Last record of each journal; one unsupported or broken journal does not hide the others."""
    from app.modem_gateway.mercury import MercuryGatewayError

    entries, timeouts = [], 0
    for key, journal, title, kind in JOURNALS:
        entry = {"journal": key, "number": f"{journal:02X}", "title": title}
        try:
            data = meter.send_command(0x04, journal, 0xFF, response_length=13)
            entry.update(status="GOOD", **_parse_journal(kind, data))
            timeouts = 0
        except MercuryStatusError as exc:
            if exc.code != "UNSUPPORTED":
                raise
            entry.update(status="UNSUPPORTED")
        except MercuryGatewayError as exc:
            if exc.code == "DEVICE_OFFLINE":
                raise
            entry.update(status="ERROR", error_code=exc.code)
            timeouts = timeouts + 1 if exc.code == "MERCURY_TIMEOUT" else 0
        except ValueError:
            entry.update(status="ERROR", error_code="UNKNOWN_RESPONSE_FORMAT")
        entries.append(entry)
        if timeouts >= MAX_JOURNAL_TIMEOUTS:
            break
    return entries


def _parse_journal(kind: str, data: list[int]) -> dict:
    """§4.2.1: reading record FFh appends the record number after the 12 data bytes."""
    if len(data) != 13:
        raise ValueError("UNKNOWN_RESPONSE_FORMAT")
    record, body = data[12], data[:12]
    if kind == "reprogramming":
        if not any(body[:3]):
            return {"record": record, "start": None}
        day, month, year = map(_bcd, body[:3])
        return {"record": record, "start": f"{2000 + year:04d}-{month:02d}-{day:02d}",
                "requests": body[3], "codes": bytes(body[4:]).hex(" ").upper()}
    start = _bcd_timestamp(body[:6])
    if kind == "status_word":
        return {"record": record, "start": start, "status_word": decode_status_word(body[6:]) if start else None}
    return {"record": record, "start": start, "end": _bcd_timestamp(body[6:])}

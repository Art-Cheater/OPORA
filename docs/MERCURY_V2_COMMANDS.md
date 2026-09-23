# Mercury V2 read-only command registry

Источник протокольных данных — официальный портал документации НПК «Инкотекс»:

- «Протокол Меркурий. Описание команд от 03.11.2023» —
  https://doc.incotexcom.ru/protocol/mercury/
- «Меркурий 230. Руководство по эксплуатации АВЛГ.411152.021 РЭ» —
  https://doc.incotexcom.ru/hardware/230/

Важно: опубликованное описание команд от 03.11.2023 прямо относит протокол к
счётчикам Mercury 234/236. Оно не является достаточным доказательством формата
ответов неизвестной модели реального счётчика за ATM21. Поэтому электрические
параметры, энергию, архивы и журналы нельзя включать до определения модели и
проверки соответствующего официального документа.

| Command | Code | Purpose | Response/scaling | Units | Model | Implemented | Fixture tested | Physical verified | Source |
|---|---:|---|---|---|---|---|---|---|---|
| `serial_and_manufacture` | `08 00` | Серийный номер и дата выпуска | parser `mercury-base 1.6` | — | неизвестна | yes | yes | yes | production fixture |
| `transformation_ratios` | `08 02` | Коэффициенты трансформации | parser `mercury-base 1.6`; `current=0` требует проверки | — | неизвестна | yes | yes | communication path | production fixture |
| `firmware_version` | `08 03` | Версия ПО | три байта версии | — | неизвестна | yes | yes | yes | production fixture |
| `additional_timeout_multiplier` | `08 04` | Дополнительный timeout | parser `mercury-base 1.6` | — | supported list библиотеки | yes | no | no | mercury-base 1.6 |
| `main_timeout_multiplier` | `08 1D` | Основной timeout | parser `mercury-base 1.6` | — | supported list библиотеки | yes | no | no | mercury-base 1.6 |
| `passport` | `08 0100` | Паспорт | реализация библиотеки формирует недопустимый байт | — | — | no | no | no | mercury-base 1.6 limitation |
| `device_info` | `08 12` | Возможности исполнения | 6/8 байт feature flags; полная маркировка не угадывается | — | Mercury family | yes | yes | no | official protocol §6.21 |
| `voltage_phases` | `08 14 11` | U A/B/C | reordered unsigned 24-bit / 100 | V | Mercury 230 | yes | yes | no | official protocol §6.9–6.16 |
| `current_phases` | `08 14 21` | I A/B/C | reordered unsigned 24-bit / 1000 | A | Mercury 230 | yes | yes | no | official protocol §6.9–6.16 |
| `active_power` | `08 14 00` | P total/A/B/C | direction flag, reordered 24-bit / 100 | W | Mercury 230 | yes | yes | no | official protocol §6.11–6.14 |
| `reactive_power` | `08 14 04` | Q total/A/B/C | direction flag, reordered 24-bit / 100 | var | Mercury 230 | yes | yes | no | official protocol §6.11–6.14 |
| `apparent_power` | `08 14 08` | S total/A/B/C | reordered 24-bit / 100 | VA | Mercury 230 | yes | yes | no | official protocol §6.11–6.14 |
| `power_factor` | `08 14 30` | cosφ total/A/B/C | direction flags, reordered 24-bit / 1000 | 1 | Mercury 230 | yes | yes | no | official protocol §6.17 |
| `frequency` | `08 11 40` | Частота сети | reordered unsigned 24-bit / 100 | Hz | Mercury 230 | yes | yes | no | official protocol §6.18 |
| `phase_angles` | `08 11 51/52/53` | Углы AB/AC/BC | reordered unsigned 24-bit / 100 | deg | Mercury 230 | yes | yes | no | official protocol §6.9–6.16 |

Статусы в API command registry представлены флагами `fixture_tested` и
`physical_verified`. Все команды whitelist имеют `safe_read_only=true`.

## Добавление команды

До включения команды необходимо зафиксировать официальный документ и модель,
точные request bytes, layout ответа, endian, signedness, scaling и units. Затем
добавляются CRC/short/malformed/boundary fixtures. До физического теста флаг
`physical_verified` обязан оставаться `false`. Write-команды в IRZ Console не
добавляются.

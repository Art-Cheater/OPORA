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
| `device_info` | `08 12` | Вариант исполнения | parser библиотеки содержит TODO | — | 234/236 documented | no | no | no | official protocol §6 |

Статусы в API command registry представлены флагами `fixture_tested` и
`physical_verified`. Все команды whitelist имеют `safe_read_only=true`.

## Добавление команды

До включения команды необходимо зафиксировать официальный документ и модель,
точные request bytes, layout ответа, endian, signedness, scaling и units. Затем
добавляются CRC/short/malformed/boundary fixtures. До физического теста флаг
`physical_verified` обязан оставаться `false`. Write-команды в IRZ Console не
добавляются.

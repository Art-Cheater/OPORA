# IRZ / ATM21 / Mercury

Реестр команд, источники протокола и статусы проверки находятся в
[`MERCURY_V2_COMMANDS.md`](MERCURY_V2_COMMANDS.md).

IMEI является постоянной identity IRZ. Пользовательское имя хранится в уже
существующем `IRZDevice.name`; online определяется только live socket. Mercury
создаётся в `IRZMeter` только после физически успешного чтения серийного номера.
Неизвестную модель разрешено указать администратору вручную; такое значение
помечается `model_source=MANUAL` и не считается автоматическим определением.

## Architecture and ports

The production path is physically verified:

```text
Mercury <-- RS-485 --> ATM21 -- inbound TCP session --> modem-sniffer :5009
web -------------------------------- internal HTTP --> modem-sniffer :5010
boards ---------------------------------------------> tcp-gateway :5000
```

ATM21 is the TCP client. `modem-sniffer` owns its accepted socket. Flask web
workers never own or copy sockets, and OPORA never opens a production outbound
TCP or serial connection to Mercury. Board port 5000 and IRZ port 5009 are
separate paths.

## ATM21 identification and online state

The gateway buffers the TCP stream and parses `AT$IMEI` identification,
including fragmented packets. It stores IMEI, DEV, VER, REV, BLD, HDW, SIM,
CSQ, ATP, INT, remote endpoint, connection and last-RX timestamps. Passwords
are neither persisted nor included in fixtures.

`ONLINE` means the IMEI has a live socket in the process-local registry. It is
not a database boolean. Disconnect or sidecar restart makes the ATM21 offline.

## Heartbeat

`B5 BC BD BE BF` is classified as `ATM21_HEARTBEAT` and never passed to the
Mercury parser, including heartbeats that arrive between fragments of one
Mercury answer. It is hidden from the operator journal. Its exact protocol
meaning is unknown. Legacy
echo is configurable with `ATM21_HEARTBEAT_ACK=1` and disabled by default.

## Mercury universal address 0

The installed meter physically answers read-only Mercury V2 commands at
network address `0`. Address zero is therefore the operator default. It is not
approved for write/control commands: `0` is the universal/read address and
`1..N` is a specific meter address.

## Physically verified commands

### Serial number and manufacture date

```text
TX 00 08 00 76 00
RX 00 24 4F 01 3C 0A 02 13 7B 09
serial_number = 36790160
date_of_manufacture = 2019-02-10
```

### Transformation ratios

```text
TX 00 08 02 F7 C1
RX 00 00 01 00 01 B4        (observed, 6 bytes)
RX 00 00 01 00 01 B4 00     (full frame, reconstructed)
voltage = 1
current = 1 (expected)
```

The request is physically verified. The observed `current=0` was an artefact:
the old transport accepted the shortest CRC-valid prefix, and `00 00 01 00`
happens to have CRC `01 B4`. By §4.4.4 the answer carries four binary bytes
(Кн, Кт, most significant byte first), so the full frame is 7 bytes. The
transport now waits for the expected length; the ratios need a fresh physical
capture.

### Firmware

```text
TX 00 08 03 36 01
RX 00 02 03 05 61 17
firmware_version = 2.3.5
```

The additional (`08 04`) and main (`08 1D`) timeout multipliers are available
as manual commands and are not part of the regular poll.

## Transport, timeout, and correlation

`ATM21SessionTransport` supplies `mercury-base` with the already accepted
ATM21 socket. A per-session lock permits one Mercury command at a time. The
default command timeout is five seconds. Timeout, disconnect, CRC failure,
wrong address, and incomplete response clear pending state so a later command
can proceed.

Every command declares its response length. A response is complete when it has
the expected address and exactly `address + data + CRC` bytes with a valid CRC,
or when it is a 4-byte status frame. Mercury V2 responses do not echo the
request opcode, so command correlation is provided by the one-pending-command
rule rather than a fictitious echoed command field.

When the meter answers `05` (channel not open), the manager opens access
level 1 (`01 01 <password>`, read-only) and repeats the command once. The
password comes from `MERCURY_LEVEL1_PASSWORD` (factory default `111111`) and is
masked as `2A` bytes in every TX log.

## Monitoring and diagnostics

The operator page shows ATM21 connectivity separately from the last successful
Mercury response, persists the last serial/date, firmware, ratios and poll time,
and groups TX/RX/result as one logical operation. Heartbeats and duplicate raw
transport events are hidden by default.

The user page exposes monitoring only. Low-level RAW, manual HEX and protocol
diagnostics remain backend-only and are not mixed into the operator workflow.

## User pages and permissions

- `/irz` — «IRZ · Мониторинг»: MapLibre map and a searchable device list
  (name, IMEI, meter serial, address). Devices without coordinates stay in the
  list only.
- `/irz/<uuid>` — device detail (IMEI URLs redirect to the UUID URL):
  lighting status, readings, poll history, location card.
- `/irz/map-display` — read-only fullscreen map, see
  [`IRZ_MAP_DISPLAY.md`](IRZ_MAP_DISPLAY.md).
- `/irz/poles`, `/irz/poles/<id>` — street-lighting poles, see below.

### Статус освещения

Эксплуатационный статус вычисляется только в `app/modules/irz/status.py`
(`get_irz_operational_status`) и не зависит от транспортного online ATM21,
который показывается отдельно.

| Статус | Условие |
|---|---|
| `ON` «Горит» | ATM21 на связи, есть актуальные I/P/Q/S, хотя бы одно значение любой фазы по модулю > `IRZ_LIGHT_ON_THRESHOLD` (1.0). Порог в единицах карточки: I в амперах, P/Q/S в кВт / квар / кВА (в снимке P/Q/S хранятся в Вт / вар / ВА) |
| `OFF` «Не горит» | актуальные данные есть, хотя бы одна из величин I/P/Q/S пришла по всем трём фазам, ничего не превышает порог |
| `PROBLEM` «Проблема» | актуальных данных нет или их недостаточно для решения, прошло меньше часа |
| `CRITICAL` «Критическая проблема» | то же, но с последнего успешного ответа прошло ≥ `IRZ_CRITICAL_AFTER_SECONDS` (3600) |

Актуальны только команды I/P/Q/S, которые в последнем опросе вернулись
успешно и не старше `IRZ_DATA_FRESH_SECONDS` (900 с). Если команда упала,
её прошлые значения остаются в карточке с пометкой STALE, но решение по ним
не принимается. `null`, `NaN`, строки и `bool` не считаются нулём. «Последний
успешный ответ Mercury» — самое позднее `captured_at` из успешно считанных I/P/Q/S
(`irz_meters.latest_snapshot.commands`), а не heartbeat ATM21. Если ответов
не было ни разу, время отсчитывается от первого обнаружения ATM21 (`created_at`).

Тип шкафа по названию (trim, верхний регистр): начинается с «ИП» — `IP`,
розовая плашка; «ПП» — `PP`, серо-белая; иначе `OTHER`, светло-зелёная.
Маркер строится только из слоёв MapLibre над одним GeoJSON source: symbol-слой
с плашкой (`icon-text-fit`) и названием, над ним circle-слой лампы статуса.
DOM-маркеров нет.

| Permission | Grants |
|---|---|
| `irz.view` | list, map, detail page, poles list/detail, `GET /irz/api/map`, `GET /irz/api/directory`, `GET /irz/poles/map.json` |
| `irz.edit` | name, address and coordinates (`PATCH /irz/api/devices/<imei>`) |
| `irz.poll` | manual poll, event journals, energy archive |
| `irz.map_display` | fullscreen map, `GET /irz/api/map` and `GET /irz/poles/map.json` only |
| `irz.admin` | manual meter model (`PATCH /irz/api/mercury/devices/<id>/meter`) |
| `irz.send`, `irz.control` | legacy engineering endpoints; write commands stay disabled |

Newly introduced permissions are granted once on creation to roles that already
had the matching older one (`irz.edit` ← `irz.admin`, `irz.poll` and
`irz.map_display` ← `irz.view`); later changes in the roles UI are kept.

## Справочник ШУНО (серийный № Mercury → шкаф)

Таблица `meter_cabinet_directory` (миграция `066_irz_meter_directory`) хранит
соответствие серийного номера Mercury шкафу управления: ШУНО, ID ШУНО, модель,
дата установки, КТТ и координаты. Серийный номер хранится строкой и уникален.
С IRZ справочник связан только по `irz_devices.directory_entry_id`, без FK.

Источник — `meters_with_cabinets.xlsx`, лист «Счётчики», столбцы «Серийный
номер», «ШУНО», «ID ШУНО», «Модель», «Установлен», «КТТ», «Широта», «Долгота».
Excel читается только CLI-командой, а не при опросе.

- Номер со звёздочкой (`36794365*`) — прошлая установка с датой снятия. У
  такого счётчика всегда есть действующая строка, поэтому исторические строки
  пропускаются и не перезаписывают текущий ШУНО.
- Пустой номер — пропуск; невалидные координаты или КТТ — `NULL` и
  предупреждение; числовые и текстовые ячейки нормализуются одинаково.
- Повторный импорт обновляет записи по серийному номеру и не создаёт дублей.

### Автоматическое сопоставление

1. ATM21 подключается и регистрируется по IMEI, как раньше.
2. Опрос читает серийный номер Mercury (`serial_and_manufacture`).
3. Если IRZ ещё не сопоставлен, запись ищется по номеру:
   - найдена — у IRZ заполняются название = ШУНО (если стоит стандартное
     `ATM21 <IMEI>`) и координаты (если не заданы), у счётчика —
     `catalog_model` («Меркурий 230 ART-03 PQRSIDN»), статус `MATCHED`;
   - не найдена — `NOT_FOUND`, ничего не меняется, в карточке предупреждение;
   - запись уже привязана к другому IRZ — `METER_SERIAL_CONFLICT`, warning в
     логе, данные не применяются.
4. После сопоставления опросы ничего не перетирают.

`IRZMeter.model` остаётся ручным полем администратора; модель по справочнику
хранится отдельно в `catalog_model`. На статус связи и цвет маркера
сопоставление не влияет.

«Повторно применить данные справочника» (право `irz.edit`) в карточке
устройства показывает, что изменится, и после подтверждения перезаписывает
название, координаты и модель. Если запись была привязана к другому IRZ,
связь переносится на текущий, событие попадает в журнал действий.

### Runbook

На сервере достаточно:

```bash
cd /opt/opora && sudo bash scripts/deploy.sh
```

Скрипт после `git reset --hard origin/main` копирует `meters_with_cabinets.xlsx`
и `опоры.xlsx` из корня репозитория в `data/imports/` (в контейнере
`/data/imports/`, volume, не Docker image). Затем, уже после Alembic head,
в том же контейнере `web` и той же PostgreSQL:

1. `flask irz-import-meter-directory --file /data/imports/meters_with_cabinets.xlsx`
2. `flask irz-import-poles --file /data/imports/опоры.xlsx`
3. `flask irz-meter-directory-find 40191143`
4. `flask irz-match-existing-meter-directory`
5. `flask irz-poles-find 2880041`
6. `flask irz-deploy-check`

Повторный импорт — upsert: новые строки добавляются, изменённые обновляются,
отсутствующие в Excel записи из БД не удаляются. Сопоставление IRZ не
перезаписывает уже связанные карточки и не разрешает конфликты серийников.

`NOT_FOUND` не блокирует повторный lookup после обновления справочника.

Локально без `--file` используются xlsx в корне проекта. `--show-warnings`
выводит все предупреждения по строкам.

## Опоры освещения

Таблица `light_poles` (миграция `067_irz_light_poles`): `pole_number`
(строка, уникален), `luminaire_name`, `latitude`, `longitude`, `quantity`.
Источник — `опоры.xlsx`, первый лист, столбцы «Номер опоры», «Название
светильника», «Широта», «Долгота», «Кол-во, шт».

В файле одна строка — один светильник. Опора с несколькими светильниками
повторяет номер с теми же координатами, поэтому такие строки объединяются:
`quantity` — сумма строк, `luminaire_name` — «MAG41-200 … × 2; MAG31-130 …».
Реальный файл: 4701 строка → 4068 опор, 633 строки объединены, пропусков и
ошибок нет.

- Пустой номер — строка пропускается.
- Невалидные или неполные координаты — опора сохраняется без координат с
  предупреждением: она находится поиском, но не показывается на карте.
  Строку не выбрасываем, чтобы не потерять опору из справочника.
- Нецелое количество — ошибка строки и предупреждение, количество не учитывается.
- Повторный импорт — upsert по номеру: «Добавлено / Обновлено / Без изменений».
  Опоры, которых нет в новом файле, не удаляются.

Страницы: `/irz/poles` (поиск по номеру и светильнику, 50 на страницу),
`/irz/poles/<id>` (карточка с небольшой картой). На `/irz` и
`/irz/map-display` опоры — отдельный слой треугольников. Он появляется с zoom 14
на `/irz` и с zoom 15 на большом экране, загружается через `GET /irz/poles/map.json?bbox=minLon,minLat,maxLon,maxLat`
после остановки карты (debounce 300 мс). Отдаётся не больше 2500 опор;
при обрезке в ответе `truncated: true`. Переключатели слоёв «IRZ» и «Опоры»
запоминаются в `localStorage` браузера. На экране IRZ показываются всегда,
опоры включаются отдельно.

### Runbook

`опоры.xlsx` хранится в корне репозитория. `deploy.sh` копирует его в
`data/imports/опоры.xlsx` (`/data/imports/опоры.xlsx` в контейнере) и
импортирует после миграций. Отдельный `cp` / `flask irz-import-poles` на
сервере не нужен. Файл не кладётся в Docker-образ (`*.xlsx` в
`.dockerignore`).

Локально без `--file` используется `опоры.xlsx` в корне проекта.

## Ten-minute production poll

The `irz-poller` sidecar gives every enabled IMEI a fixed offset inside the
600-second window (600 devices means one start per second). A device is due
once its current slot has started and it has not been polled since. Due devices
are polled by a thread pool (`IRZ_POLL_WORKERS`); modem-sniffer still
serializes transactions inside one ATM21. The database session is released
while waiting for the gateway. Browsers never trigger periodic polling.

Manual refresh calls the same `MercurySessionManager.poll()` path. One poll
creates one normalized `IRZMeterSnapshot` with quality `GOOD`, `PARTIAL`,
`STALE`, `INVALID`, `CRC_ERROR` or `UNSUPPORTED`. The meter keeps a merged
current state: successful commands update their fields; failed commands keep
the previous values marked `STALE` with their capture time. After two
consecutive timeouts the remaining commands are skipped.

The default poll includes identity, Кн/Кт, U/I/P/Q/S/cos phi, frequency,
phase angles, energy A+/A-/R+/R- (total and T1–T4), meter time with drift
against server time (`IRZ_METER_TIMEZONE`, no correction), and the status word
with E-01…E-48 decoding. Event journals and energy archives are read only on
request (`POST /irz/api/devices/<imei>/events`, `/energy-archive`).

## Known mercury-base 1.6 limitations

- `get_passport` calls `send_command(0x08, 0x0100)`; `bytes(params)` rejects
  `0x0100`, so it is disabled.
- `get_info` sends `08 12 00`, but its parser is a TODO returning
  `model=unknown` and an empty feature list; it is disabled.
- `get_transformation_ratios` parses Кн/Кт as decimal strings, which is wrong
  for binary values; the project parser is used instead.
- Voltage, current, power, frequency, cos phi, angles, energy, meter time,
  status word, journals and archives are implemented in the project-local
  `app/modem_gateway/mercury230.py`; site-packages are unchanged. Load
  profiles are not implemented yet.

## Official sources

- Incotex, «Описание системы команд приборов учета Меркурий», version 06.2024,
  pages 43-74 and appendix A:
  https://www.incotexcom.ru/files/em/docs/merkuriy-sistema-komand-ver-1-ot-2024-08-30.pdf
- Mercury 230 operating manual АВЛГ.411152.021 РЭ:
  https://doc.incotexcom.ru/hardware/230/

## How to add a read command

1. Identify the exact physical meter model or obtain an authoritative protocol.
2. Record command bytes, response length/shape, CRC, and address behavior.
3. Implement missing behavior in a project-local extension module, never in
   site-packages.
4. Add real TX/RX fixtures and parser/CRC/timeout tests.
5. Expose it as read-only in the allow-list, then verify physically before
   enabling it for polling.

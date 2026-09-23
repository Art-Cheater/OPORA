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

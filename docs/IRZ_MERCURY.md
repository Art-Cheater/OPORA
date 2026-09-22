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
Mercury parser. The operator journal hides it by default; engineering RAW and
the Heartbeat filter retain it. Its exact protocol meaning is unknown. Legacy
echo is configurable with `ATM21_HEARTBEAT_ACK=1` and disabled by default.

## Mercury universal address 0

The installed meter physically answers read-only Mercury V2 commands at
network address `0`. Address zero is therefore the operator default. It is not
approved for write/control commands. Engineering mode explains that `0` is the
universal/read address and `1..N` is a specific meter address.

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
RX 00 00 01 00 01 B4
voltage = 1
current = 0
```

These are the unmodified `mercury-base 1.6` parser values. The suspicious
`current=0` is deliberately not rescaled or hidden without protocol evidence.

### Firmware

```text
TX 00 08 03 36 01
RX 00 02 03 05 61 17
firmware_version = 2.3.5
```

The additional (`08 04`) and main (`08 1D`) timeout multipliers are implemented
by the library and included in polling, but still require physical verification
on this meter.

## Transport, timeout, and correlation

`ATM21SessionTransport` supplies `mercury-base` with the already accepted
ATM21 socket. A per-session lock permits one Mercury command at a time. The
default command timeout is five seconds; a complete poll is bounded by the web
request timeout. Timeout, disconnect, CRC failure, wrong address, and incomplete
response clear pending state so a later command can proceed.

Responses must have the expected address, a minimum CRC frame length, and valid
CRC. Mercury V2 responses do not echo the request opcode, so command correlation
is provided by the one-pending-command rule rather than a fictitious echoed
command field.

## Operator and RAW modes

The operator page shows ATM21 connectivity separately from the last successful
Mercury response, persists the last serial/date, firmware, ratios and poll time,
and groups TX/RX/result as one logical operation. Heartbeats and duplicate raw
transport events are hidden by default.

Engineering mode retains manual HEX, Protocol Lab, full heartbeat traffic,
internal command IDs, CSV export, and network address diagnostics.

## Known mercury-base 1.6 limitations

- `get_passport` calls `send_command(0x08, 0x0100)`; `bytes(params)` rejects
  `0x0100`, so it is disabled.
- `get_info` sends `08 12 00`, but its parser is a TODO returning
  `model=unknown` and an empty feature list; it is disabled.
- Voltage, current, power, frequency, cos phi, energy, tariffs, event journal,
  and meter time are not implemented for V2 by this dependency. No speculative
  production commands are exposed.

## How to add a read command

1. Identify the exact physical meter model or obtain an authoritative protocol.
2. Record command bytes, response length/shape, CRC, and address behavior.
3. Implement missing behavior in a project-local extension module, never in
   site-packages.
4. Add real TX/RX fixtures and parser/CRC/timeout tests.
5. Expose it as read-only in the allow-list, then verify physically before
   enabling it for polling.

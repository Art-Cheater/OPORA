# IRZ: Mercury V2

## Архитектура

Страница `/irz` вызывает только Flask API. Flask хранит настройки приборов,
аудит и журнал операций, но не владеет физическими соединениями. Все Serial и
TCP соединения, а также блокировки физических линий находятся в однопроцессном
sidecar `modem-sniffer` на внутреннем HTTP-порту 5010. Это важно, потому что web
работает в трёх Gunicorn worker-процессах: локальный lock в route не обеспечил бы
сериализацию команд.

Путь вызова: `UI -> IRZ routes -> service -> modem-sniffer ->
MercuryConnectionManager -> mercury-base 1.6 -> прибор`. Старые ATM21 endpoints
`/devices`, `/send` и `/test-command` сохранены.

## Реальные возможности mercury-base 1.6

Исходник `mercury_base/mercury_v2/commands.py` содержит семь публичных функций:

- `get_serial_number_and_date_of_manufacture`;
- `get_passport`;
- `get_transformation_ratios`;
- `get_firmware_version`;
- `get_additional_timeout_multiplier`;
- `get_main_timeout_multiplier`;
- `get_info`.

Пять исправных read-only функций доступны оператору. `get_passport` отключена:
библиотека передаёт значение `0x0100` в `bytes()`. `get_info` отключена, потому
что её parser оставлен автором с `TODO` и всегда возвращает `unknown`. README
при этом перечисляет `get_serial_number`, которого в V2 module нет. Из-за этого
штатный `Meter` не может завершить V2 discovery. Адаптер использует настоящие
V2 command functions, framing/parsing библиотеки и `modbus-crc`, обходя только
сломанный discovery. В версии 1.6 нет V2-команд напряжения, тока, мощности,
частоты, энергии или write/control, поэтому OPORA их не имитирует.

Реестр находится в `app/modules/irz/commands.py`. Для добавления команды сначала
нужно подтвердить её наличие и сигнатуру в используемой версии mercury-base,
затем добавить `CommandSpec`, formatter/validator и тест. UI строится из реестра
и не принимает Python method name от браузера.

## Транспорты и очередь

Serial использует фактический `SerialDataTransport(port, baudrate=...)`.
Для TCP применяется совместимый синхронный adapter: зависимость
`simple-socket-client 1.5`, которую использует `TcpDataTransport`, бесконечно
busy-spin'ит в idle и может навсегда зависнуть при connection-refused. Adapter
сохраняет контракт `ask(bytes)` и конечный socket timeout, а протокол, команды,
CRC и parsing остаются в mercury-base. Допустимы `/dev/tty*`,
`/dev/serial/by-id/*` и `COMn`; произвольные filesystem paths отвергаются.
Для Docker serial device должен быть явно проброшен оператором Compose, например
`/dev/ttyUSB0:/dev/ttyUSB0`; проект не hardcode-ит конкретный порт.

Lock имеет ключ `serial:<port>` либо `tcp:<host>:<port>`, поэтому приборы на одной
линии не выполняют команды одновременно. Lock освобождается в `finally` после
успеха, timeout и parser/transport error. TCP timeout ограничивается настройкой
0.2–30 секунд; Serial transport mercury-base делает пять чтений по 0.1 секунды.

Библиотека не предоставляет публичный `close()`. Connection manager использует
проверенные private backing connections только для закрытия; это изолировано в
одном adapter и должно быть перепроверено при обновлении зависимости.

## Журнал, RAW и права

`irz_operation_logs` хранит пользователя, команду, status, JSON-safe результат,
duration и TX/RX (не более 4096 байт каждого направления). Polling UI загружает
не более 100 записей, API ограничивает максимум 200. RAW снимается decorator-ом
транспорта без изменения site-packages.

- `irz.view`: страница, read-команды, опрос и журнал;
- `irz.control`: connect/disconnect и будущие write/control команды;
- `irz.admin`: создание, изменение и удаление конфигураций;
- `irz.send`: сохранено только для совместимости старого ATM21 HEX API.

Write-команд в реальном V2 API 1.6 нет. Когда зависимость их предоставит, они
должны получить `mode=write`, `dangerous=true`, отдельное подтверждение UI,
`irz.control` и audit.

## Диагностика и тесты

Запуск: `pytest -q tests/test_irz.py tests/test_irz_mercury.py
tests/test_modem_sniffer.py`. Fake transport покрывает успешный ответ, timeout,
RAW, неизвестную команду, сериализацию двух устройств на одной линии и
восстановление очереди после timeout. Fake используется только в tests.

При отсутствии связи проверить доступность sidecar 5010 внутри Compose, mapping
Serial device, права процесса на `/dev/tty*`, host/port, сетевой адрес и RAW CRC.
После перезапуска sidecar UI синхронизирует состояние соединений обратно в
`DISCONNECTED`; оператор должен подключить прибор повторно.

# TCP Gateway: контракт протокола устройств

Это новый versioned-протокол OPORA, а не описание или подтверждение
совместимости с существующей платой. Для BGS2T/IPP/другой firmware **ТРЕБУЕТСЯ
ПРОТОКОЛ ПЛАТЫ** и отдельная проверка до подключения к production.

Транспорт — raw TCP `tcp.zheleznogame.ru:5000`; кадр — один JSON-объект UTF-8,
заканчивающийся `\n`, не больше `DEVICE_MAX_FRAME_BYTES`.

1. Gateway отправляет `{"type":"challenge","version":"1","nonce":"..."}`.
2. Устройство отвечает `{"type":"auth","version":"1","device_id":"...","hmac":"..."}`.
3. `hmac` — lowercase HMAC-SHA256 от байтов `device_id:nonce`, ключ —
   индивидуальный provisioning secret устройства.
4. После `authenticated` устройство отправляет `pong` и фактическое состояние:
   `{"type":"state","actual":{"C6":...,"C7":...,"C8":...}}`.
   Имена C6/C7/C8 не получают в OPORA придуманной семантики.
5. Команда приходит как `{"type":"command","command_id":"UUID","command":"...","payload":{...}}`.
   Устройство обязано вернуть `ack` с тем же `command_id`; успешная socket-write
   не считается завершением команды.

Нельзя логировать provisioning secret, nonce+HMAC целиком или payload с
секретами. При невалидном кадре, таймауте авторизации или HMAC соединение
закрывается без создания сессии устройства.

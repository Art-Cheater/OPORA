IPP TCP v2.2.6 STATE SPLIT TX
=========================

Цель этой сборки — стабильная тестовая прошивка под уже реализованный в OPORA
протокол v2.

ЧТО ОСТАВЛЕНО НА ПЛАТЕ
----------------------
- BGS2T / SIM / CREG / GPRS.
- Постоянный TCP tcp.zheleznogame.ru:5000.
- Production challenge/HMAC/authenticated handshake.
- После auth только короткий ASCII protocol v2.
- C6/C7/C8.
- SETALL.
- RAW U2/U3.
- CSQ / CREG / CGATT.
- STATE при изменении входов и раз в 2 секунды.
- LCD диагностика.

ЧЕГО НА ПЛАТЕ НЕТ
-----------------
- phase A/B/C logic;
- desired/actual business logic;
- истории;
- UUID команд;
- JSON после authentication;
- интерпретации G1/G2/G3;
- принятия решений по состоянию объекта.

НАСТРОЙКИ ТЕСТОВОЙ ПЛАТЫ
-------------------------
DEVICE_ID: ipp-001
DEVICE_SECRET: Artwer
Host: tcp.zheleznogame.ru
Port: 5000

На сайте для этой прошивки выбирать:
Protocol = v2

LCD
---
Нормальный запуск:

V2.1 / CLEAN V2
NET
TCP / OPENING
TCP / WAIT UP
TCP UP / WAIT AUTH
AUTH / NONCE OK
AUTH / SENT
ONLINE / AUTH OK
ONLINE / V2 READY

Основные ошибки:

E01 NET / INIT FAIL
  Не прошла инициализация modem/SIM/CREG/GPRS.

E06 TCP / OPEN FAIL
  Не удалось открыть TCP socket.

E08 AUTH / NO NONCE
  TCP работает, но challenge/nonce не получен.

E08 AUTH / NONCE LONG
  nonce длиннее NONCE_MAX.

E09 AUTH / TX FAIL
  Не удалось передать auth frame через SISW.

E10 AUTH / REJECT
  auth отправлен, но Gateway не прислал authenticated.
  Проверить protocol=v2, DEVICE_ID и DEVICE_SECRET.

E11 RX / PATH FAIL
  Ошибка чтения TCP/SISR.

E11 RX / SISR SHORT
  BGS2T объявил N байт payload, но UART не получил их полностью.

E12 TX / BUSY
  BGS2T временно не дал write grant после повторов.

E12 TX / PART GRANT
  BGS2T дал grant меньше длины frame.

E12 TX / STATE FAIL
  Не удалось отправить STATE.

E12 TX / CMD FAIL
  Не удалось отправить OK/PONG/STATE после команды.

СБОРКА
------
1. Распаковать каталог.
2. Запустить build.bat.
3. Прислать Program/Data из avr-size.
4. Если сборка помещается — запустить flash.bat.

ВАЖНО
-----
В этой среде AVR toolchain отсутствует, поэтому firmware.hex здесь не
пересобирался и размер Program/Data не проверен. build.bat сделает реальную
проверку на вашем Windows-компьютере.

ПОСЛЕ ПРОШИВКИ
---------------
Сначала НЕ тестировать всё сразу.

1. Дождаться ONLINE / V2 READY.
2. На сайте ipp-001 должен быть protocol=v2.
3. Проверить GET/state.
4. Проверить C6.
5. Проверить C7.
6. Проверить C8.
7. Проверить "Включить всё".
8. Проверить "Выключить всё".
9. Смотреть U2/U3 при изменении входов.

Если не дошла до ONLINE, пришлите две строки LCD.
Если ONLINE есть, но команда не работает — пришлите LCD и tcp_gateway logs
за момент одной команды.


v2.2.3 — AUTH SAFE FLASH FIT
----------------------------

Почему сделана эта версия:

tcpdump production показал:
- TCP соединение устанавливается;
- Gateway отправляет challenge;
- плата подтверждает TCP packet;
- но AUTH payload от платы вообще не появляется в tcpdump;
- спустя ~30 секунд Gateway закрывает соединение.

v2.2/v2.2.2 пытались сделать универсальный chunked-SISW transport, но он
раздул Flash ATmega8515 за предел 8192 bytes.

В v2.2.3 выбран более простой и проверяемый подход:

1. Возвращена компактная транспортная реализация v2.1, которая помещалась
   во Flash.
2. Только AUTH отправляется несколькими небольшими SISW writes:
   - JSON prefix;
   - DEVICE_ID;
   - `"hmac":"`;
   - HMAC четырьмя блоками по 16 hex chars;
   - suffix + LF.
3. Для TCP это по-прежнему одна непрерывная JSON строка. TCP не сохраняет
   границы SISW writes и Gateway получает один auth frame до LF.
4. После authentication остаётся обычный v2 ASCII protocol.
5. Нет function pointers, generic frame contexts и другого тяжёлого transport-кода.

LCD:
AUTH / TX
  началась физическая передача AUTH через BGS2T.

AUTH / WAIT GW
  весь AUTH передан, ждём authenticated.

E09 AUTH / TX
  AUTH не удалось физически передать через SISW.

E10 AUTH / TIMEOUT
  AUTH был передан, но authenticated не распознан до timeout.

Это диагностически важное различие.

ВАЖНО:
На сайте ipp-001 должен быть Protocol = v2.
DEVICE_SECRET в этой pilot-сборке = Artwer.


v2.2.5 — ТОЧНОЕ ИСПРАВЛЕНИЕ AUTH SCANNER
-----------------------------------------

Предыдущая v2.2.4 была исправлена не в том месте: в main.c реальный scanner
всё ещё содержал:

    static const char pat[] PROGMEM="\"authenticated\"";

Поэтому ответ production Gateway:

    AUTHENTICATED 2\n

никогда не мог совпасть и прошивка закономерно доходила до E10 AUTH TIMEOUT.

В этой версии исправлен именно auth_scan_authenticated():

    static const char pat[] PROGMEM="AUTHENTICATED";

Совпадение делается по слову AUTHENTICATED. После него цифра протокола и LF
не важны.

tcpdump уже подтвердил, что:
- AUTH полностью отправляется;
- HMAC принимается;
- Gateway отвечает AUTHENTICATED 2;
- затем Gateway сразу отправляет GET.

Поэтому после этой правки ожидаем:
    AUTH / TX
    AUTH / WAIT GW
    ONLINE / AUTH OK
а затем обработку GET и передачу STATE.


v2.2.6 — STATE SPLIT TX
-----------------------

После v2.2.5 плата дошла до ONLINE/AUTH OK, затем получила GET от Gateway,
но показала E12 TX CMD.

Это означает:
- TCP/Auth уже работают;
- GET разобран;
- ошибка возникает при ответе на команду;
- первый ответ на GET — STATE.

В старом коде весь STATE (~40–50 bytes) требовал одного точного SISW grant.
BGS2T уже показал, что для больших writes может дать partial grant.

В v2.2.6 STATE остаётся одной TCP-строкой, но передаётся модему двумя
короткими SISW writes:

  part 1: STATE O=... U2=... U3=...
  part 2:  CSQ=... CREG=... CGATT=...\n

TCP склеивает их в исходную строку автоматически.

AUTH scanner fix из v2.2.5 сохранён.

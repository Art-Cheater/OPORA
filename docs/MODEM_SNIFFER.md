# ATM21.A raw TCP sniffer

Добавьте `MODEM_SNIFFER_PORT=5009` в `.env` и запустите сервис обычным
`docker compose up -d modem-sniffer`. Настройте ATM21.A на TCP server IP OPORA
и порт `5009`. Поток не парсится: логи доступны через
`docker compose logs -f modem-sniffer`.

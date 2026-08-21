# Как мерить скорость (шаг 0)

Не гадать. Цифры до и после nginx — иначе непонятно, что помогло.

## Включить профайлер в `.env` на сервере

```
PERFORMANCE_PROFILER_ENABLED=True
PERFORMANCE_PROFILER_RESPONSE_HEADERS=True
```

Перезапустить `web` (`docker compose up -d web`).

## Что смотреть в DevTools → Network

1. HTML-страница (документ): **Waiting for server / TTFB**. Это бэкенд. Уже отдаётся `Server-Timing: app;dur=…`.
2. `bootstrap.min.css`, шрифты, JS: время и размер. После nginx CSS должен быть ~30 КБ (gzip), не 228 КБ, и **не** идти через gunicorn.
3. Если TTFB 50–300 мс, а «долго» — секунды на статике: причина была в доставке файлов. Если TTFB секунды — тогда копать SQL (ILIKE, seq scan).

Записать 4–5 URL до выкладки и те же после.

## Что уже сделано в инфре

- nginx перед gunicorn, gzip, `/static/` с диска
- Postgres и gunicorn не торчат наружу, наружу только `:5000` → nginx
- `.dockerignore`, образ web без LibreOffice по умолчанию
- иконки только woff2

## Что сознательно не трогали

Списки с `ILIKE '%…%'`, Redis для ролей, нарезка 1000-строчных `routes.py` — это шаг 4, только с `EXPLAIN ANALYZE` с прода.

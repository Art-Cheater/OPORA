"""Конфиг Gunicorn для контейнера.

preload_app: приложение грузится один раз в мастере, воркеры форкаются.
Без этого каждый из 3 воркеров заново импортирует Flask — на Docker Desktop
это легко даёт минуты до первой страницы.
"""

import os

bind = "0.0.0.0:5000"
workers = int(os.getenv("WEB_CONCURRENCY", "3"))
threads = int(os.getenv("GUNICORN_THREADS", "4"))
timeout = 60
graceful_timeout = 30
keepalive = 5
preload_app = True
accesslog = None
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")


def post_fork(server, worker):
    """Сбросить унаследованные соединения SQLAlchemy после fork."""
    from app.extensions import db

    db.engine.dispose()

"""WSGI-точка входа для production (gunicorn)."""

from app import create_app

app = create_app("production")

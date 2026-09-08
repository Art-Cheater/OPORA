from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from flask import Flask

from app import _reject_insecure_production_secrets


ROOT = Path(__file__).resolve().parents[1]


def _check_env_module():
    spec = importlib.util.spec_from_file_location("opora_check_env", ROOT / "scripts" / "check_env.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_env() -> str:
    return "\n".join(
        [
            "FLASK_ENV=production",
            "FLASK_DEBUG=0",
            "SECRET_KEY=correct-production-secret-key-with-32-chars",
            "USE_SQLITE=0",
            "POSTGRES_HOST=db",
            "POSTGRES_PORT=5432",
            "POSTGRES_DB=opora",
            "POSTGRES_USER=opora_user",
            "POSTGRES_PASSWORD=not-a-real-password",
            "ADMIN_EMAIL=admin@example.test",
            "ADMIN_PASSWORD=not-a-real-admin-password",
            "",
        ]
    )


def test_check_env_accepts_valid_production_env(tmp_path):
    path = tmp_path / ".env"
    path.write_text(_valid_env(), encoding="utf-8")
    assert _check_env_module().validate_env(path) == []


def test_check_env_rejects_example_or_too_short_secret(tmp_path):
    path = tmp_path / ".env"
    path.write_text(_valid_env().replace("correct-production-secret-key-with-32-chars", "change-me-to-a-long-random-secret-value"), encoding="utf-8")
    assert any("SECRET_KEY" in error for error in _check_env_module().validate_env(path))


def test_check_env_rejects_nonempty_gunicorn_cmd_args(tmp_path):
    path = tmp_path / ".env"
    path.write_text(_valid_env() + "GUNICORN_CMD_ARGS=--workers 99\n", encoding="utf-8")
    assert any("GUNICORN_CMD_ARGS" in error for error in _check_env_module().validate_env(path))


@pytest.mark.parametrize(
    ("broken_line", "expected"),
    [
        ("FLASK_ENV=production FLASK_DEBUG=0 SECRET_KEY=abc", "несколько переменных"),
        ("POSTGRES_PASSWORD=abc POSTGRES_SCHEMA=opora", "несколько переменных"),
        ('INQUIRY_IMAP_PASSWORD="abc"WEB_CONCURRENCY=1', "несколько переменных"),
    ],
)
def test_check_env_rejects_joined_assignments_without_leaking_secret(tmp_path, broken_line, expected):
    path = tmp_path / ".env"
    path.write_text(_valid_env() + broken_line + "\n", encoding="utf-8")
    errors = _check_env_module().validate_env(path)
    rendered = "\n".join(errors)
    assert expected in rendered
    assert "not-a-real-password" not in rendered
    assert "SECRET_KEY=abc" not in rendered
    assert "INQUIRY_IMAP_PASSWORD=********" in rendered or "POSTGRES_PASSWORD=********" in rendered or "FLASK_ENV=" in rendered


def test_check_env_masks_secret_in_cli_output(tmp_path, capsys):
    path = tmp_path / ".env"
    path.write_text(_valid_env() + "SECRET_KEY=very-secret-value DB_POOL_SIZE=2\n", encoding="utf-8")
    assert _check_env_module().main(["check_env.py", str(path)]) == 1
    output = capsys.readouterr().err
    assert "very-secret-value" not in output
    assert "SECRET_KEY=********" in output


def test_deploy_checks_env_before_docker_build_and_reports_unhealthy_web():
    deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    assert deploy.index("python3 scripts/check_env.py") < deploy.index("docker compose build")
    assert "show_web_failure" in deploy
    assert "docker compose logs --tail=120 web" in deploy
    assert "docker inspect opora_web" in deploy


def test_production_secret_protection_rejects_default_and_accepts_strong_secret():
    insecure = Flask(__name__)
    insecure.config.update(SECRET_KEY="change-me-to-a-long-random-secret-value", ADMIN_PASSWORD="safe-admin-password")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _reject_insecure_production_secrets(insecure)

    safe = Flask(__name__)
    safe.config.update(SECRET_KEY="correct-production-secret-key-with-32-chars", ADMIN_PASSWORD="safe-admin-password")
    _reject_insecure_production_secrets(safe)

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
            "OPORA_ENV=production",
            "SECRET_KEY=correct-production-secret-key-with-32-chars",
            "USE_SQLITE=0",
            "POSTGRES_HOST=db",
            "POSTGRES_PORT=5432",
            "POSTGRES_DB=opora",
            "POSTGRES_USER=opora_user",
            "POSTGRES_PASSWORD=not-a-real-password",
            "ADMIN_EMAIL=admin@example.test",
            "ADMIN_PASSWORD=not-a-real-admin-password",
            "TLS_CERTS_DIR=/etc/letsencrypt",
            "SESSION_COOKIE_SECURE=True",
            "REMEMBER_COOKIE_SECURE=True",
            "PROXY_FIX_ENABLED=True",
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
    assert "compose logs --tail=120" in deploy
    assert "docker inspect opora_web" in deploy
    assert "docker-compose.timeweb.example.yml" in deploy
    assert "docker-compose.staging.yml" in deploy
    assert "COMPOSE_BAKE=false" in deploy
    code = "\n".join(line for line in deploy.splitlines() if not line.lstrip().startswith("#"))
    assert "--allow" not in code
    assert " down" not in code and "down -v" not in code
    for service in ("web", "nginx", "inquiry-sync", "eis-sync", "documents-notify", "tcp-gateway", "modem-sniffer", "irz-poller"):
        assert service in deploy
    assert "flask db" in deploy and "current" in deploy and "heads" in deploy
    assert "opora_tcp_gateway 5000/tcp" in deploy
    assert "opora_modem_sniffer 5009/tcp" in deploy


def test_tcp_gateway_reuses_web_image_and_does_not_overwrite_it():
    overlay = (ROOT / "docker-compose.timeweb.example.yml").read_text(encoding="utf-8")
    gateway = overlay.split("  tcp-gateway:", 1)[1].split("\n\n", 1)[0]
    assert "image: opora-web:latest" in gateway
    assert "build:" not in gateway
    assert "app.tcp_gateway.main\", \"--healthcheck" not in gateway


def test_tcp_gateway_healthcheck_command_talks_to_the_real_health_server(monkeypatch):
    import asyncio
    import re
    import subprocess
    import sys

    from app.tcp_gateway.main import Gateway

    overlay = (ROOT / "docker-compose.timeweb.example.yml").read_text(encoding="utf-8")
    gateway = overlay.split("  tcp-gateway:", 1)[1]
    code = re.search(r'test: \["CMD", "python", "-c", "(.+)"\]', gateway).group(1)

    async def scenario():
        server = await asyncio.start_server(lambda r, w: Gateway.health(None, r, w), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        env = {"DEVICE_HEALTH_PORT": str(port), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
        async with server:
            process = await asyncio.create_subprocess_exec(sys.executable, "-c", code, env=env)
            ok = await asyncio.wait_for(process.wait(), 10)
        closed = subprocess.run([sys.executable, "-c", code], env=env, timeout=10).returncode
        return ok, closed

    ok, closed = asyncio.run(scenario())
    assert ok == 0 and closed != 0


FAKE_DOCKER = r'''#!/usr/bin/env bash
echo "docker $*" >> "$PWD/calls.log"
if [[ "$1" == "compose" ]]; then
  shift; args=()
  while [[ $# -gt 0 ]]; do case "$1" in -f) shift 2;; *) args+=("$1"); shift;; esac; done
  set -- "${args[@]}"
  case "$1" in
    ps) echo "id_${@: -1}";;
    config) printf '%s\n' db web nginx eis-sync inquiry-sync documents-notify modem-sniffer irz-poller tcp-gateway;;
    exec)
      if [[ "$*" == *"db current"* ]]; then echo "${FAKE_DB_CURRENT:-061_irz_monitoring_dashboard} (head)"
      elif [[ "$*" == *"db heads"* ]]; then echo "061_irz_monitoring_dashboard (head)"; fi;;
  esac
  exit 0
fi
case "$1" in
  inspect)
    shift; fmt=""; id=""
    while [[ $# -gt 0 ]]; do case "$1" in -f|--format) fmt="$2"; shift 2;; *) id="$1"; shift;; esac; done
    service="${id#id_}"
    case "$fmt" in
      "{{.State.Status}}/"*) [[ "$service" == "${FAKE_UNHEALTHY:-}" ]] && echo "running/unhealthy" || echo "running/healthy";;
      "{{.Created}}") date -u +%Y-%m-%dT%H:%M:%S.000000000Z;;
      *printf*) echo "$service row";;
    esac;;
  port)
    case "$2 ${3:-}" in
      "opora_tcp_gateway 5000/tcp") echo "0.0.0.0:5000";;
      "opora_modem_sniffer 5009/tcp") echo "0.0.0.0:5009";;
      "opora_tcp_gateway ") echo "5000/tcp -> 0.0.0.0:5000";;
      "opora_modem_sniffer ") echo "5009/tcp -> 0.0.0.0:5009";;
    esac;;
esac
exit 0
'''


def _bash() -> str | None:
    import os
    import shutil
    if os.name == "nt":
        for candidate in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if Path(candidate).exists():
                return candidate
        return None
    return shutil.which("bash")


def _run_deploy(tmp_path, **env):
    import os
    import subprocess
    bash = _bash()
    if bash is None:
        pytest.skip("bash is not available")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "deploy.sh").write_bytes((ROOT / "scripts" / "deploy.sh").read_bytes().replace(b"\r\n", b"\n"))
    (tmp_path / ".env").write_text("OPORA_ENV=production\n", encoding="utf-8", newline="\n")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    stubs = {"docker": FAKE_DOCKER, "sleep": "#!/usr/bin/env bash\nexit 0\n",
             "git": '#!/usr/bin/env bash\necho "git $*" >> "$PWD/calls.log"\n[[ "$1" == rev-parse ]] && echo abc123\nexit 0\n',
             "python3": '#!/usr/bin/env bash\necho "python3 $*" >> "$PWD/calls.log"\nexit 0\n'}
    for name, content in stubs.items():
        path = fakebin / name
        path.write_text(content, encoding="utf-8", newline="\n")
        path.chmod(0o755)
    process = subprocess.run([bash, "-c", 'export PATH="$PWD/fakebin:$PATH"; bash scripts/deploy.sh'],
                             cwd=tmp_path, env={**os.environ, **env}, capture_output=True, timeout=120)
    output = process.stdout.decode("utf-8", "replace") + process.stderr.decode("utf-8", "replace")
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines() if (tmp_path / "calls.log").exists() else []
    return process.returncode, output, calls


def test_deploy_builds_once_and_recreates_every_service_without_build(tmp_path):
    code, output, calls = _run_deploy(tmp_path)
    assert code == 0, output
    builds = [line for line in calls if line.startswith("docker compose") and " build " in line]
    assert len(builds) == 1
    for service in ("web", "nginx", "inquiry-sync", "eis-sync", "documents-notify", "modem-sniffer", "irz-poller"):
        assert f" {service}" in builds[0]
    assert "tcp-gateway" not in builds[0]
    ups = [line for line in calls if line.startswith("docker compose") and " up " in line]
    assert ups and all("--no-build" in line for line in ups)
    assert not any(" down" in line or " -v" in line for line in calls)
    recreated = " ".join(line for line in ups if "--force-recreate" in line)
    for service in ("web", "nginx", "inquiry-sync", "eis-sync", "documents-notify", "tcp-gateway", "modem-sniffer", "irz-poller"):
        assert f" {service}" in recreated
    web_up = next(index for index, line in enumerate(calls) if " up " in line and line.endswith(" web"))
    current = next(index for index, line in enumerate(calls) if "flask db current" in line)
    others_up = next(index for index, line in enumerate(calls) if " up " in line and "tcp-gateway" in line)
    assert calls.index(builds[0]) < web_up < current < others_up
    assert "COMMIT: abc123" in output
    assert "MIGRATION HEAD: 061_irz_monitoring_dashboard" in output
    assert "tcp-gateway row" in output and "modem-sniffer row" in output


def test_deploy_stops_when_migrations_are_not_at_head(tmp_path):
    code, output, calls = _run_deploy(tmp_path, FAKE_DB_CURRENT="060_irz_meter_snapshots")
    assert code != 0
    assert "FAIL: миграции не применены до head" in output
    assert not any(" up " in line and "tcp-gateway" in line for line in calls)


def test_deploy_names_the_actually_failing_service(tmp_path):
    code, output, _calls = _run_deploy(tmp_path, FAKE_UNHEALTHY="tcp-gateway")
    assert code != 0
    assert "FAIL: сервис tcp-gateway" in output
    assert "FAIL: сервис web" not in output


def test_check_env_accepts_staging_without_timeweb_tls(tmp_path):
    path = tmp_path / ".env"
    content = _valid_env().replace("OPORA_ENV=production", "OPORA_ENV=staging")
    content = content.replace("TLS_CERTS_DIR=/etc/letsencrypt\n", "")
    content = content.replace("SESSION_COOKIE_SECURE=True\n", "")
    content = content.replace("REMEMBER_COOKIE_SECURE=True\n", "")
    content = content.replace("PROXY_FIX_ENABLED=True\n", "")
    path.write_text(content, encoding="utf-8")
    assert _check_env_module().validate_env(path) == []


def test_production_secret_protection_rejects_default_and_accepts_strong_secret():
    insecure = Flask(__name__)
    insecure.config.update(SECRET_KEY="change-me-to-a-long-random-secret-value", ADMIN_PASSWORD="safe-admin-password")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _reject_insecure_production_secrets(insecure)

    safe = Flask(__name__)
    safe.config.update(SECRET_KEY="correct-production-secret-key-with-32-chars", ADMIN_PASSWORD="safe-admin-password")
    _reject_insecure_production_secrets(safe)

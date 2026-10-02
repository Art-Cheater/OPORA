"""Публичный домен, отдельный сертификат и raw TCP без смены портов."""

from pathlib import Path

ROOT = Path(__file__).parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_nginx_accepts_new_host_and_keeps_old_certificate_path():
    conf = _text("docker/nginx.timeweb.conf")
    assert "server_name opora.truthqwark.ru opora.zheleznogame.ru;" in conf
    assert "location /.well-known/acme-challenge/ { root /var/www/certbot; }" in conf
    assert "return 301 https://$public_https_host$request_uri;" in conf
    assert "include /etc/nginx/site-enabled/legacy-site.conf;" in conf
    assert "include /etc/nginx/site-enabled/public-https.conf;" in conf
    assert "include /etc/nginx/site-enabled/public-site.conf;" in conf
    assert "client_max_body_size 64m;" in conf

    legacy = _text("docker/nginx.legacy-serve.conf")
    public = _text("docker/nginx.public-https.conf")
    assert "server_name opora.zheleznogame.ru;" in legacy
    assert "/etc/letsencrypt/live/opora.zheleznogame.ru/fullchain.pem" in legacy
    assert "return 301 https://opora.truthqwark.ru" not in legacy
    assert "listen 443 ssl default_server;" in public
    assert "server_name opora.truthqwark.ru;" in public
    assert "/etc/letsencrypt/live/opora.truthqwark.ru/fullchain.pem" in public
    assert "opora.zheleznogame.ru" not in public


def test_legacy_redirect_preserves_path_and_old_certificate():
    redirect = _text("docker/nginx.legacy-redirect.conf")
    mapping = _text("docker/nginx.legacy-redirect-map.conf")
    assert "return 301 https://opora.truthqwark.ru$request_uri;" in redirect
    assert "/etc/letsencrypt/live/opora.zheleznogame.ru/fullchain.pem" in redirect
    assert "5000" not in redirect and "5009" not in redirect
    assert mapping.strip() == "opora.zheleznogame.ru opora.truthqwark.ru;"


def test_proxy_keeps_host_and_does_not_open_cors():
    proxy = _text("docker/nginx.proxy-locations.conf")
    assert "proxy_set_header Host $host;" in proxy
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in proxy
    assert "proxy_send_timeout 120s;" in proxy
    assert "Access-Control-Allow-Origin" not in proxy


def test_tcp_listeners_stay_on_their_ports_and_modem_api_is_private():
    base = _text("docker-compose.yml")
    production = _text("docker-compose.timeweb.example.yml")
    deploy = _text("scripts/deploy.sh")
    assert '"5009:5009"' in base
    assert "5010:5010" not in base and "5010:5010" not in production
    assert '"5000:5000"' in production
    assert "/var/www/certbot" in production
    assert "./data/nginx:/etc/nginx/site-enabled:ro" in production
    assert "listen 443" not in base
    assert "opora-public-site:latest" in base
    assert "127.0.0.1:8090:80" in base
    assert "public-site" in deploy
    assert "kirovsvet.truthqwark.ru" in deploy
    site_nginx = _text("docker/nginx.public-site.conf")
    assert "proxy_pass http://$public_site_upstream;" in site_nginx
    assert "web:5000" not in site_nginx
    assert "DB_HOST: db" in base
    assert "container_name: opora_public_site" in base
    assert "--webroot" in deploy and '--cert-name "$PUBLIC_DOMAIN"' in deploy
    assert "certbot delete" not in deploy
    assert "nginx.legacy-serve.conf" in deploy
    assert "OPORA_LEGACY_REDIRECT" in deploy


def test_session_cookie_stays_host_only():
    config = _text("app/config.py")
    assert "SESSION_COOKIE_DOMAIN" not in config
    assert "COOKIE_DOMAIN deliberately remains unset" in config
    assert 'SESSION_COOKIE_SAMESITE = "Lax"' in config

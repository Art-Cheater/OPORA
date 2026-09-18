from app.modules.auth.login_throttle import LoginThrottle


def test_login_form_has_remember_me(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b"remember" in response.data


def test_login_throttle_keys_ip_login_and_pair(app):
    with app.app_context():
        original = app.config["LOGIN_RATE_LIMIT_MAX_ATTEMPTS"]
        app.config["LOGIN_RATE_LIMIT_MAX_ATTEMPTS"] = 2
        LoginThrottle.clear_success("10.0.0.1", "person@example.test")
        LoginThrottle.record_failure("10.0.0.1", "person@example.test")
        assert LoginThrottle.retry_after("10.0.0.1", "person@example.test") == 0
        LoginThrottle.record_failure("10.0.0.1", "person@example.test")
        assert LoginThrottle.retry_after("10.0.0.1", "person@example.test") > 0
        LoginThrottle.clear_success("10.0.0.1", "person@example.test")
        app.config["LOGIN_RATE_LIMIT_MAX_ATTEMPTS"] = original

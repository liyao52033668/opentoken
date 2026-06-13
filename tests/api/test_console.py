from fastapi.testclient import TestClient

from opentoken.api.app import create_app
from opentoken.api.auth import reset_auth_cache
from opentoken.config.paths import resolve_app_config_path, resolve_providers_dir


def _client() -> TestClient:
    return TestClient(create_app())


def test_status_when_disabled_reports_disabled(monkeypatch) -> None:
    monkeypatch.delenv("OPENTOKEN_ADMIN_PASSWORD", raising=False)
    client = _client()
    response = client.get("/console/api/status")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "authenticated": False}


def test_console_endpoints_reject_when_disabled(monkeypatch) -> None:
    """No admin password → every protected endpoint fails closed with 401,
    not a 500 stack trace. The console must never expose an adminless surface."""
    monkeypatch.delenv("OPENTOKEN_ADMIN_PASSWORD", raising=False)
    client = _client()
    assert client.get("/console/api/apikey").status_code == 401
    assert client.post("/console/api/apikey/rotate").status_code == 401
    assert client.get("/console/api/providers").status_code == 401


def test_login_with_wrong_password_is_401(monkeypatch) -> None:
    monkeypatch.setenv("OPENTOKEN_ADMIN_PASSWORD", "secret")
    client = _client()
    response = client.post("/console/api/login", json={"password": "wrong"})
    assert response.status_code == 401
    # No session cookie set on failure.
    assert "opentoken_console" not in response.cookies


def test_login_then_session_grants_access(monkeypatch) -> None:
    monkeypatch.setenv("OPENTOKEN_ADMIN_PASSWORD", "secret")
    client = _client()
    login = client.post("/console/api/login", json={"password": "secret"})
    assert login.status_code == 200
    assert "opentoken_console" in client.cookies

    # Authenticated status reflects the session cookie.
    status = client.get("/console/api/status")
    assert status.json()["enabled"] is True
    assert status.json()["authenticated"] is True

    # A protected endpoint now works.
    apikey = client.get("/console/api/apikey")
    assert apikey.status_code == 200
    assert "api_key" in apikey.json()


def test_logout_clears_session(monkeypatch) -> None:
    monkeypatch.setenv("OPENTOKEN_ADMIN_PASSWORD", "secret")
    client = _client()
    client.post("/console/api/login", json={"password": "secret"})
    assert client.get("/console/api/apikey").status_code == 200

    client.post("/console/api/logout")
    # After logout the protected endpoint rejects again.
    reset_request = client.get("/console/api/apikey")
    assert reset_request.status_code == 401


def test_apikey_rotate_changes_key_and_invalidates_old(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENTOKEN_ADMIN_PASSWORD", "secret")
    reset_auth_cache()
    client = _client()

    # Seed a known key.
    config_path = resolve_app_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        '{"api_key":"seed-key","host":"127.0.0.1","port":32117}', encoding="utf-8"
    )

    client.post("/console/api/login", json={"password": "secret"})
    rotated = client.post("/console/api/apikey/rotate")
    assert rotated.status_code == 200
    new_key = rotated.json()["api_key"]
    assert new_key != "seed-key"
    assert rotated.json()["keyless_local"] is False

    # The old seed key no longer authenticates /v1/*.
    reset_auth_cache()
    old = client.get("/v1/models", headers={"Authorization": "Bearer seed-key"})
    assert old.status_code == 401
    # The new key does.
    ok = client.get("/v1/models", headers={"Authorization": f"Bearer {new_key}"})
    assert ok.status_code == 200
    reset_auth_cache()


def test_apikey_clear_enters_keyless_local(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENTOKEN_ADMIN_PASSWORD", "secret")
    reset_auth_cache()
    client = _client()
    config_path = resolve_app_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        '{"api_key":"seed-key","host":"127.0.0.1","port":32117}', encoding="utf-8"
    )

    client.post("/console/api/login", json={"password": "secret"})
    cleared = client.post("/console/api/apikey/clear")
    assert cleared.status_code == 200
    assert cleared.json() == {"api_key": "", "keyless_local": True, "has_key": False}

    # keyless_local lets /v1/* through without a bearer.
    reset_auth_cache()
    response = client.get("/v1/models")
    assert response.status_code == 200
    reset_auth_cache()


def test_provider_login_and_delete(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENTOKEN_ADMIN_PASSWORD", "secret")
    client = _client()
    client.post("/console/api/login", json={"password": "secret"})

    # nim requires api_key; supply it.
    saved = client.post(
        "/console/api/providers/nim/login", json={"api_key": "nvapi-xxx"}
    )
    assert saved.status_code == 200
    assert saved.json() == {"provider": "nim", "status": "valid"}

    providers = client.get("/console/api/providers").json()["providers"]
    nim = next(p for p in providers if p["key"] == "nim")
    assert nim["status"] == "valid"
    assert "api_key" in nim["manual_auth"]

    deleted = client.delete("/console/api/providers/nim")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    providers = client.get("/console/api/providers").json()["providers"]
    nim = next(p for p in providers if p["key"] == "nim")
    assert nim["status"] == "not_logged_in"


def test_provider_login_rejects_wrong_material(monkeypatch) -> None:
    monkeypatch.setenv("OPENTOKEN_ADMIN_PASSWORD", "secret")
    client = _client()
    client.post("/console/api/login", json={"password": "secret"})

    # nim requires api_key — supplying only a cookie must 400.
    bad = client.post(
        "/console/api/providers/nim/login", json={"cookie": "a=b"}
    )
    assert bad.status_code == 400


def test_provider_cookie_requires_user_agent(monkeypatch) -> None:
    """A cookie-based session is bound to its issuing UA; without one the saved
    session is likely dead on arrival, so the backend rejects cookie-without-UA
    regardless of what the frontend allowed."""
    monkeypatch.setenv("OPENTOKEN_ADMIN_PASSWORD", "secret")
    client = _client()
    client.post("/console/api/login", json={"password": "secret"})

    # deepseek accepts cookie/header — but a cookie without UA must be rejected.
    rejected = client.post(
        "/console/api/providers/deepseek/login", json={"cookie": "a=b"}
    )
    assert rejected.status_code == 400
    assert "User-Agent" in rejected.json()["detail"]

    # Same cookie with a UA succeeds.
    ok = client.post(
        "/console/api/providers/deepseek/login",
        json={"cookie": "a=b", "user_agent": "Mozilla/5.0 test"},
    )
    assert ok.status_code == 200


def test_provider_token_is_wrapped_as_bearer_header(monkeypatch) -> None:
    """The frontend sends a bare token in `headers.authorization`; the backend
    stores it as-is. This pins the contract: a token round-trips into the
    saved record's headers under `authorization`."""
    monkeypatch.setenv("OPENTOKEN_ADMIN_PASSWORD", "secret")
    from opentoken.config.paths import resolve_providers_dir
    from opentoken.storage.provider_store import load_provider_credentials

    client = _client()
    client.post("/console/api/login", json={"password": "secret"})

    saved = client.post(
        "/console/api/providers/deepseek/login",
        json={
            "headers": {"authorization": "Bearer my-token"},
            "user_agent": None,
        },
    )
    assert saved.status_code == 200, saved.text

    record = load_provider_credentials(resolve_providers_dir(), "deepseek")
    assert record is not None
    assert record.headers.get("authorization") == "Bearer my-token"


def test_provider_login_rejects_unknown_provider(monkeypatch) -> None:
    monkeypatch.setenv("OPENTOKEN_ADMIN_PASSWORD", "secret")
    client = _client()
    client.post("/console/api/login", json={"password": "secret"})

    response = client.post(
        "/console/api/providers/nope/login", json={"api_key": "x"}
    )
    assert response.status_code == 404


def test_models_returns_grouped(monkeypatch) -> None:
    monkeypatch.setenv("OPENTOKEN_ADMIN_PASSWORD", "secret")
    client = _client()
    client.post("/console/api/login", json={"password": "secret"})

    response = client.get("/console/api/models")
    assert response.status_code == 200
    models = response.json()["models"]
    assert isinstance(models, dict)
    # Each model object looks like the OpenAI-compat shape.
    for items in models.values():
        for item in items:
            assert {"id", "object", "owned_by"} <= set(item.keys())


def test_console_page_served_at_root(monkeypatch) -> None:
    monkeypatch.setenv("OPENTOKEN_ADMIN_PASSWORD", "secret")
    client = _client()
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "OpenToken Console" in response.text


def test_console_bypasses_gateway_api_key(monkeypatch, tmp_path) -> None:
    """The console page and its API must be reachable even when the gateway
    api_key is set (they don't share the gateway bearer auth)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENTOKEN_ADMIN_PASSWORD", "secret")
    reset_auth_cache()
    config_path = resolve_app_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        '{"api_key":"gateway-key","host":"127.0.0.1","port":32117}', encoding="utf-8"
    )
    client = _client()

    # No Authorization header, yet the console status endpoint responds.
    status = client.get("/console/api/status")
    assert status.status_code == 200
    reset_auth_cache()

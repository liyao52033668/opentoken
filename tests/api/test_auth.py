from fastapi.testclient import TestClient

from opentoken.api.app import create_app
from opentoken.api.auth import reset_auth_cache
from opentoken.config.app_config import default_app_config


def test_health_does_not_require_api_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200


def test_models_requires_bearer_api_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    config = default_app_config()
    config["api_key"] = "test-key"
    (tmp_path / ".opentoken").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".opentoken" / "config.json").write_text(
        '{"api_key":"test-key","host":"127.0.0.1","port":32117}',
        encoding="utf-8",
    )
    client = TestClient(create_app())

    missing = client.get("/v1/models")
    wrong = client.get("/v1/models", headers={"Authorization": "Bearer wrong"})
    ok = client.get("/v1/models", headers={"Authorization": "Bearer test-key"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200


def test_corrupt_config_fails_closed_not_open(monkeypatch, tmp_path) -> None:
    """A corrupt config.json must NOT crash the middleware (500 storm) and must
    NOT fall through to the keyless-open path — it fails closed with 503."""
    reset_auth_cache()
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".opentoken").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".opentoken" / "config.json").write_text("{ truncated", encoding="utf-8")
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.get("/v1/models", headers={"Authorization": "Bearer anything"})

    assert response.status_code == 503, response.text
    reset_auth_cache()

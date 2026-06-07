import pytest


@pytest.fixture(autouse=True)
def isolate_user_home(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("OPENTOKEN_STATE_DIR", raising=False)
    monkeypatch.delenv("OPENTOKEN_CONFIG_PATH", raising=False)
    monkeypatch.delenv("OPENTOKEN_API_KEY", raising=False)
    # 强制使用本地存储后端
    monkeypatch.setenv("OPENTOKEN_STORAGE_BACKEND", "local")
    # 清除 S3 相关环境变量
    monkeypatch.delenv("OPENTOKEN_S3_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENTOKEN_S3_BUCKET", raising=False)
    monkeypatch.delenv("OPENTOKEN_S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("OPENTOKEN_S3_SECRET_KEY", raising=False)
    monkeypatch.delenv("OPENTOKEN_S3_REGION", raising=False)
    monkeypatch.delenv("OPENTOKEN_S3_PREFIX", raising=False)
    # 重置存储后端实例
    from opentoken.storage.factory import reset_storage_backend
    reset_storage_backend()

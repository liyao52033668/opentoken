import pytest


@pytest.fixture(autouse=True)
def isolate_user_home(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    # 设置 OPENTOKEN_STATE_DIR 以便 StorageBackend 使用 tmp_path
    monkeypatch.setenv("OPENTOKEN_STATE_DIR", str(tmp_path / ".opentoken"))
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


@pytest.fixture(autouse=True)
def reset_storage_state() -> None:
    """在每个测试后重置存储状态。"""
    yield
    # 测试后重置存储后端
    from opentoken.storage.factory import reset_storage_backend
    reset_storage_backend()

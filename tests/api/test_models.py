from fastapi.testclient import TestClient

from opentoken.api.app import create_app


def test_models_endpoint_returns_openai_style_list() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/models")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"object", "data"}
    assert payload["object"] == "list"
    assert isinstance(payload["data"], list)
    for item in payload["data"]:
        assert set(item.keys()) == {"id", "object", "owned_by"}
        assert item["object"] == "model"
        assert item["owned_by"] == "opentoken"
        # ONE format only: bare `<provider>/<model>` — never the `algae/` prefix.
        assert not item["id"].startswith("algae/"), item["id"]


def test_models_endpoint_lists_only_bare_provider_model_ids() -> None:
    """/v1/models must advertise a single, bare `<provider>/<model>` form — no
    `algae/…` namespaced ids, and no namespace-less raw model names (which would
    be ambiguous across providers, e.g. glm-5)."""
    client = TestClient(create_app())
    payload = client.get("/v1/models").json()
    for item in payload["data"]:
        mid = item["id"]
        assert not mid.startswith("algae/"), mid
        # at least one slash → it carries a provider segment
        assert "/" in mid, mid


def test_models_endpoint_omits_retired_or_duplicate_ids() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/models")

    assert response.status_code == 200
    model_ids = {item["id"] for item in response.json()["data"]}

    # These ids used to leak from the hardcoded catalog. Now that the catalog is
    # live-discovered, they should not reappear unless a provider's upstream
    # explicitly lists them.
    retired = {
        "qwen-intl/qwen3.5-turbo",
        "qwen-cn/qwen3.5-plus",
        "qwen-cn/qwen3.5-turbo",
        "qwen-cn/Qwen3.5-Plus",
        "qwen-cn/Qwen3.5-Turbo",
        "doubao/doubao-lite",
        "glm-cn/glm-4",
        "glm-cn/glm-4-zero",
        "mimo/mimo-v2-pro",
        "mimo/xiaomimo-chat",
    }

    assert retired.isdisjoint(model_ids)


def test_models_endpoint_does_not_advertise_unimplemented_embedding_models() -> None:
    """/v1/embeddings 永久 501,所以 /v1/models 也不该再把 text-embedding-* 列
    出来 —— 之前的"故意 decouple"会让 SDK auto-discover 拿了再调 → 51X 错误。
    既然端点不可用,model 名也不暴露。"""
    client = TestClient(create_app())

    response = client.get("/v1/models")

    assert response.status_code == 200
    model_ids = {item["id"] for item in response.json()["data"]}

    assert "text-embedding-3-small" not in model_ids
    assert "text-embedding-3-large" not in model_ids
    assert "text-embedding-ada-002" not in model_ids

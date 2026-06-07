"""Provider 凭证管理 HTTP 接口。

提供 RESTful 接口用于服务器环境下管理手工凭证：
- GET    /v1/providers                      列出所有 provider 状态
- GET    /v1/providers/{provider}           获取单个 provider 详情
- POST   /v1/providers/{provider}/credentials  添加/更新凭证
- DELETE /v1/providers/{provider}/credentials  删除凭证
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from opentoken.config.paths import resolve_state_dir
from opentoken.models.provider_credentials import ProviderCredentialRecord
from opentoken.providers.registry import (
    get_provider_definition,
    list_supported_providers,
    supported_provider_keys,
)
from opentoken.storage.provider_store import (
    delete_provider_credentials,
    list_provider_credentials,
    load_provider_credentials,
    save_provider_credentials,
)


router = APIRouter()


class CredentialsRequest(BaseModel):
    """凭证请求体。"""
    cookie: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    api_key: str | None = None
    user_agent: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class ProviderInfo(BaseModel):
    """Provider 信息响应。"""
    key: str
    display_name: str
    login_modes: list[str]
    manual_auth: list[str]
    status: str
    kind: str | None = None


class ProviderListResponse(BaseModel):
    """Provider 列表响应。"""
    providers: list[ProviderInfo]


class CredentialsResponse(BaseModel):
    """凭证操作响应。"""
    provider: str
    status: str
    message: str


@router.get("/v1/providers")
def list_providers() -> ProviderListResponse:
    """列出所有 provider 状态。"""
    state_dir = resolve_state_dir()
    records = {record.provider: record for record in list_provider_credentials(state_dir)}
    result: list[ProviderInfo] = []
    for provider in list_supported_providers():
        record = records.get(provider.key)
        result.append(ProviderInfo(
            key=provider.key,
            display_name=provider.display_name,
            login_modes=list(provider.login_modes),
            manual_auth=list(provider.manual_auth),
            status=record.status if record else "not_logged_in",
            kind=record.kind if record else None,
        ))
    return ProviderListResponse(providers=result)


@router.get("/v1/providers/{provider}")
def get_provider(provider: str) -> ProviderInfo:
    """获取单个 provider 详情。"""
    provider_def = get_provider_definition(provider)
    if provider_def is None:
        supported = ", ".join(supported_provider_keys())
        raise HTTPException(
            status_code=404,
            detail=f"Unsupported provider: {provider}. Supported: {supported}",
        )

    state_dir = resolve_state_dir()
    record = load_provider_credentials(state_dir, provider_def.key)
    return ProviderInfo(
        key=provider_def.key,
        display_name=provider_def.display_name,
        login_modes=list(provider_def.login_modes),
        manual_auth=list(provider_def.manual_auth),
        status=record.status if record else "not_logged_in",
        kind=record.kind if record else None,
    )


@router.post("/v1/providers/{provider}/credentials")
def set_credentials(provider: str, body: CredentialsRequest) -> CredentialsResponse:
    """添加或更新 provider 凭证。

    支持的凭证类型：
    - cookie + user_agent: 网页登录态（如 qwen-intl, deepseek）
    - headers: 自定义请求头（如 authorization=Bearer xxx）
    - api_key: API 密钥（如 manus, nim）

    请求体示例：
    ```json
    {"cookie": "your_cookie", "user_agent": "Mozilla/5.0..."}
    {"headers": {"authorization": "Bearer xxx"}}
    {"api_key": "nvapi-xxx"}
    ```
    """
    provider_def = get_provider_definition(provider)
    if provider_def is None:
        supported = ", ".join(supported_provider_keys())
        raise HTTPException(
            status_code=404,
            detail=f"Unsupported provider: {provider}. Supported: {supported}",
        )

    provider_key = provider_def.key

    # 校验凭证类型是否被支持
    if body.api_key and "api_key" not in provider_def.manual_auth:
        raise HTTPException(
            status_code=400,
            detail=f"{provider_key} does not support api_key authentication.",
        )

    if body.api_key:
        # API key 模式
        if "api_key" not in provider_def.manual_auth:
            raise HTTPException(
                status_code=400,
                detail=f"{provider_key} does not support --api-key.",
            )
        headers = dict(body.headers)
        headers["api_key"] = body.api_key.strip()
        record = ProviderCredentialRecord(
            provider=provider_key,
            kind="api_key",
            cookie=None,
            headers=headers,
            user_agent=body.user_agent,
            metadata={"api_key": body.api_key.strip()},
            status="valid",
        )
    else:
        # 网页登录态模式
        if not body.cookie and not body.headers:
            raise HTTPException(
                status_code=400,
                detail=f"{provider_key} requires cookie or headers for manual login.",
            )
        record = ProviderCredentialRecord(
            provider=provider_key,
            kind="web_session",
            cookie=body.cookie,
            headers=body.headers,
            user_agent=body.user_agent,
            metadata=body.metadata,
            status="valid",
        )

    save_provider_credentials(resolve_state_dir(), record)
    return CredentialsResponse(
        provider=provider_key,
        status="valid",
        message=f"Credentials saved for {provider_key}.",
    )


@router.delete("/v1/providers/{provider}/credentials")
def delete_credentials(provider: str) -> CredentialsResponse:
    """删除 provider 凭证。"""
    provider_def = get_provider_definition(provider)
    provider_key = provider_def.key if provider_def else provider

    deleted = delete_provider_credentials(resolve_state_dir(), provider_key)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"No credentials found for {provider_key}.",
        )

    return CredentialsResponse(
        provider=provider_key,
        status="deleted",
        message=f"Credentials removed for {provider_key}.",
    )

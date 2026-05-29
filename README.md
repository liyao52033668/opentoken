<div align="center">

# OpenToken

**[🇨🇳 中文](#中文) · [🇬🇧 English](#english)**

把多家 LLM 网页登录态 / API key 凭证统一成一个本地 OpenAI 兼容网关。<br>
A single local OpenAI-compatible gateway fronting many LLM providers via web sessions and API keys.

</div>

---

<a id="中文"></a>

# 中文

> 切换到英文：[🇬🇧 English](#english)

把 DeepSeek / Qwen / Kimi / Doubao / GLM / Claude / Gemini / ChatGPT / Grok / Mimo / NVIDIA NIM / Manus / Unified (LiteLLM) 等多家 provider 的网页登录态、cookies、API key 统一封装成一个**本地 OpenAI 兼容网关**。你的下游客户端只对一个 OpenAI 风格端点说话；上游怎么登录、走什么协议、流式怎么剥 `<tool_calls>` 标签都被网关吃掉。

## 它解决什么

- 每家 provider 登录方式 / 模型名 / 流式协议 / 错误码都不一样
- OpenAI 风格的客户端（你的脚本 / IDE 插件 / 第三方 app）只想说一种话
- 凭证文件零散且容易意外提交进 Git

OpenToken 做的：(1) 凭证统一管理；(2) 本地 OpenAI 兼容 HTTP 接口；(3) 模型名映射；(4) 流式 / tool_calls / 错误响应对齐到 OpenAI spec。

## 支持的 Provider

**网页登录态 / 浏览器采集（11 个）**：DeepSeek · Qwen International · Qwen China · Kimi · Claude · Doubao · ChatGPT · Gemini · Grok · GLM International · GLM China · Xiaomi Mimo

**API key 直连（4 个）**：
- **Manus**（官方 API）
- **NVIDIA NIM** — `integrate.api.nvidia.com/v1`，免费 40 RPM。覆盖 DeepSeek R1 / Llama 3.3 70B / Qwen 2.5 72B / Mixtral 8x22B 等。注册 NVIDIA 账号拿 `nvapi-...` key 就能用，0 信用卡。
- **Unified Proxy (LiteLLM)** — 一个 adapter 接 100+ 后端（OpenRouter / Groq / Together / Bedrock / Anthropic / OpenAI / Perplexity / Cohere / Mistral / xAI / Fireworks / DeepInfra / Azure / Ollama / LM Studio …）。软依赖，`uv sync --extra unified` 装。

## /v1/models 全部实时发现

每家 provider 各自的发现路径见下表；任何一家失败软降级为空，结果缓存在 `~/.opentoken/model-catalog-cache.json`（TTL 6h）。冷启动并发跑所有发现器并尊重 45s 全局 deadline。

| Provider | 发现方式 |
|----------|---------|
| qwen-intl / qwen-cn / doubao / glm-cn | web 页面 / dialog 抓取（部分走 Camoufox 浏览器） |
| glm-intl | `GET chat.z.ai/api/models`，失败回退抓首页 |
| deepseek | `GET /api/v0/users/current` 校验后返协议支持的两个 wire 模型 |
| kimi | 抓 kimi.com 首页嵌入的 model metadata |
| nim | `GET integrate.api.nvidia.com/v1/models` Bearer auth |
| manus | `GET api.manus.im/api/v1/agents` |
| chatgpt | `GET /backend-api/models`，失败回退首页 |
| claude | `GET /api/organizations` + statsig chat-models 配置 |
| gemini | 抓 gemini.google.com app HTML |
| grok | 抓 grok.com 首页 HTML |
| mimo | 抓 xiaomimo.com 首页 HTML |
| unified | 按凭证里配置的 backend 过滤 `litellm.model_cost` |

**Fallback 楼板**：qwen-intl 的目录现在是纯 JS 渲染，kimi 的目录在 gRPC-Connect 后面，httpx 抓不到。已登录但实时发现返回空时，opentoken 用最小已知 wire 模型清单填底（qwen-intl → `qwen3.6-plus` / `qwen-max-latest`；kimi → `k2` / `k1`），让 chat 仍然可用、provider 不会从 `/v1/models` 静默消失。实时发现一旦恢复就直接覆盖楼板。

## 环境要求

Python **>= 3.13**，推荐用 [`uv`](https://docs.astral.sh/uv/)。

## 目录与本地状态

凭证不进仓库，全部写到 `~/.opentoken/`：

```
~/.opentoken/
├── config.json              # 本地网关配置（含本地 API key / host / port）
├── providers/<name>.json    # 各 provider 凭证
├── auth-profiles.json       # 跨 provider 的认证 profile
├── provider-sessions.json   # 会话上下文（conversation_id 等，capped 256 entries LRU）
├── responses.json           # /v1/responses 历史（TTL 7d, 1024 entries LRU）
├── files/, uploads/         # /v1/files & /v1/uploads 二进制内容
└── model-catalog-cache.json # 模型发现缓存
```

所有凭证 / cookie / token / 上传内容文件 0600（owner-only），目录树 0700（不可列）。所有 JSON 持久化走原子写（tmp + os.replace + flock）+ sensitive=True 强制 chmod。多用户主机上别人既看不到你的 cookie 也看不到对话历史和上传文件。

## 快速开始

```bash
uv sync
uv run opentoken onboard      # 初始化 ~/.opentoken/
uv run opentoken start        # 默认监听 http://127.0.0.1:32117
```

默认 base URL：`http://127.0.0.1:32117/v1`。

**非 loopback 绑定的警告**：`opentoken start --host 0.0.0.0` 会在 stderr 打印警告，因为这会把你已登录的 provider 会话暴露到本机之外；同时没配 API key 时警告升级为 **UNAUTHENTICATED**。

## 本地 API key

OpenToken 用的是**本地网关自己的 API key**（不是上游 provider 的 key）。

```bash
cat ~/.opentoken/config.json
# {"api_key":"...","host":"127.0.0.1","port":32117}
```

- 配置文件**不存在**（首次启动前）：视为开发场景 keyless 放行
- 配置文件存在但 `api_key` 是空字符串 / 纯空白：**fail closed 503**（rotation 中清空 key 忘了换是常见误操作，不能默默放行）
- 真要 keyless 本地模式：显式 `"keyless_local": true` opt-in
- `config.json` 截断 / 不是合法 JSON / 不可读：同样 **fail closed 503**

## Provider 登录

统一命令：`uv run opentoken login <provider>`。

### 方式 A：浏览器登录

打开真实 Firefox（Camoufox）让你登录，凭证保存到 `~/.opentoken/providers/<provider>.json`：

```bash
uv run opentoken login qwen international --browser
uv run opentoken login qwen china         --browser
uv run opentoken login deepseek           --browser
uv run opentoken login kimi               --browser
uv run opentoken login doubao             --browser
uv run opentoken login glm international  --browser
uv run opentoken login glm china          --browser
uv run opentoken login claude             --browser
uv run opentoken login chatgpt            --browser
uv run opentoken login gemini             --browser
uv run opentoken login grok               --browser
uv run opentoken login mimo               --browser
```

登录有 dry-run 校验：旧凭证仍有效时，新捕获到的必须通过认证 probe 才能覆盖，避免半成 harvest 把可用 cookie 替换成坏的。首次登录跳过 probe。浏览器登录后还会做 basic sanity check：至少要有 cookie / bearer / access_token / Authorization header 中一项非空，否则直接拒收。

### 方式 B：手工凭证

```bash
uv run opentoken login qwen international \
  --cookie 'your_cookie_here' \
  --user-agent 'your user agent'

uv run opentoken login deepseek --header 'authorization=Bearer xxx'
```

### 方式 C：API key

```bash
uv run opentoken login manus --api-key YOUR_KEY
uv run opentoken login nim   --api-key nvapi-XXXXXXXXXXXXXXXXXXXX
```

NIM 凭证可选 `model_chain` 跨模型 fallback —— 被 429 的模型自动切到链表里下一个，调用方无感：

```json
{
  "kind": "api_key",
  "metadata": {
    "api_key": "nvapi-XXXXXXXXXXXXXXXXXXXX",
    "model_chain": "[\"deepseek-ai/deepseek-r1\", \"meta/llama-3.3-70b-instruct\", \"qwen/qwen2.5-72b-instruct\"]"
  },
  "status": "valid"
}
```

### 方式 D：Unified Proxy (LiteLLM)

```bash
uv sync --extra unified

uv run opentoken login unified \
  --header api_key_openrouter=sk-or-XXXXXXXXX \
  --header api_key_anthropic=sk-ant-XXXXXXXX \
  --header api_key_groq=gsk_XXXXXXXX
```

调用模型形如：`unified/openrouter/anthropic/claude-3.5-sonnet`、`unified/groq/llama-3.3-70b-versatile`、`unified/together/qwen/qwen2.5-coder-32b-instruct`。

**unified 流式 + tool_calls 暂不支持**：流式接口用 `Iterator[str]` 无法承载结构化 tool_call delta；backend 在流里发出 tool_calls 时 opentoken 显式抛错让你 `stream=false` 重试，而不是静默吞掉。

### 查看状态 / 登出

```bash
uv run opentoken providers
uv run opentoken logout qwen international
```

## 启动后验证

```bash
curl http://127.0.0.1:32117/health     # → {"status":"ok"}
uv run opentoken status                # 服务状态
uv run opentoken doctor                # 系统诊断
uv run opentoken verify                # 接口契约验证（每 provider 独立线程，单个慢的不阻塞整轮）
```

跨 provider E2E 烟雾测试（另起终端）：

```bash
uv run python scripts/live_provider_smoke.py
```

每个已登录 provider 跑一次非流 + 一次流 + 一次 `/v1/responses`，写入 `live_provider_smoke_report.json`。

## OpenAI 兼容调用

```bash
curl http://127.0.0.1:32117/v1/models -H 'Authorization: Bearer YOUR_LOCAL_GATEWAY_KEY'
```

模型 id 形如：`algae/qwen-intl/qwen3.6-plus`、`algae/deepseek/deepseek-chat`、`algae/nim/deepseek-ai/deepseek-r1`、`algae/unified/openrouter/anthropic/claude-3.5-sonnet`。`algae/` 是外部 OpenClaw 客户端的 namespace 标识（保留作为 wire-format 契约）。模型别名**大小写不敏感**。

**Chat Completions（流式）**：

```bash
curl http://127.0.0.1:32117/v1/chat/completions \
  -H 'Authorization: Bearer YOUR_LOCAL_GATEWAY_KEY' \
  -H 'Content-Type: application/json' -N \
  -d '{
    "model": "algae/qwen-intl/qwen3.6-plus",
    "stream": true,
    "messages": [{"role": "user", "content": "来一段3000字自我介绍"}]
  }'
```

支持的可选参数：`temperature` · `max_tokens` · `top_p` · `tools` · `tool_choice`。

SSE 协议约定：第一条和最后一条 chunk 带 `system_fingerprint`；末尾 `usage` chunk 后接 `[DONE]`；provider 输出的 `<tool_calls>` 协议块在流末尾被重组为标准 OpenAI `tool_calls` delta，`finish_reason` 设为 `tool_calls`。

`<think>` 标签：推理模型（含 `reasoner` / `thinking` / `-think` 关键字）流式里**保留** `<think>...</think>` 让客户端实时看到推理过程；非流式响应**剥离**只留最终答案。这是有意的、测试钉住的行为。

**Responses API**：

```bash
curl http://127.0.0.1:32117/v1/responses \
  -H 'Authorization: Bearer YOUR_LOCAL_GATEWAY_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"model":"algae/qwen-intl/qwen3.6-plus","input":"你好，写一个摘要"}'
```

带 `previous_response_id` 续聊时，新请求里的 `instructions` 会被**置于上下文最前**而不是拼到历史尾部。`max_output_tokens` 自动映射到 `max_tokens`。**保存历史时 `<think>` 内容会被剥掉**——续聊不会把模型自己的推理草稿喂回去（成本翻倍 + 模型被自己干扰）。

**文件上传**：

```bash
# 一次性上传
curl -X POST http://127.0.0.1:32117/v1/files \
  -H 'Authorization: Bearer YOUR_LOCAL_GATEWAY_KEY' \
  -F 'purpose=assistants' -F 'file=@./report.pdf'

# 分块上传
curl -X POST http://127.0.0.1:32117/v1/uploads \
  -H 'Authorization: Bearer YOUR_LOCAL_GATEWAY_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"filename":"big.bin","bytes":52428800,"purpose":"assistants","mime_type":"application/octet-stream"}'
```

- 每 part 100 MiB cap，整个 upload 声明 `bytes` ≤ 100 MiB（complete 会把所有 part 拼到内存里）
- 每个 part 进来时校验"已有 parts 字节 + 本 part > 声明 bytes" → 413 拒
- **`GET /v1/files/{id}/content` 始终回 `application/octet-stream` + `nosniff` + `attachment`**，不回显上传时声明的 mime_type，防止 stored XSS

**`/v1/embeddings` 当前 501**：早期是 SHA-256 派生的伪向量，会污染 RAG 数据源 → 直接拒，把流量路由到真实 backend。`/v1/models` 也不再列 `text-embedding-*` 让 SDK auto-discover 别拿了再调。

## 错误分类

`/v1/chat/completions` 和 `/v1/responses` 共用同一个分类器：

| 上游错误 | 网关返回 |
|---------|---------|
| 缺失 / 失效凭证、session 过期、re-login 提示、`unauthenticated`（Kimi gRPC）、`no chat id`（Qwen） | **401** `authentication_error` |
| 上游 429 | **429** `rate_limit_error` |
| 上游 5xx / 解析失败 / 网关侧异常 | **502** `api_error`（不暴露上游 URL） |
| `Unsupported model` / `No route configured` | **400** `invalid_request_error` |

bare `expired` 字符串不再单独触发 401 —— 必须配合 `session/credentials/token expired` 等明确的 auth subject 才映射为 401，避免 "upstream certificate expired" 等被误判。

## 注入到外部 OpenClaw 配置

```bash
uv run opentoken config --dry-run
uv run opentoken config
uv run opentoken config --opentoken-config /path/to/openclaw-config.json
```

原子写（tmp + os.replace）+ chmod 0600（patch 含本地 apiKey）。

## 常见排障

- **`/v1/models` 空** → 检查 `/health` + `opentoken providers`。无凭证的 provider 不出现在列表里。
- **总是 401** → 检查 `Authorization: Bearer` 是不是本地网关 key（`cat ~/.opentoken/config.json`）。
- **流式不稳定** → 用 `curl -N` 区分本地问题（直接失败/超时）vs 上游限流（明确的 rate-limit/error 事件）。
- **浏览器 provider 报 `NS_ERROR_PROXY_CONNECTION_REFUSED`** → Camoufox 读**系统级**代理（不受 `HTTP_PROXY` env 影响）；关掉系统代理或确保代理可达。纯 HTTP provider 不受影响。
- **切换监听地址** → `opentoken start --host 0.0.0.0` 会打非 loopback 警告。

## 开发与测试

```bash
./.venv/bin/pytest                # 全套（当前 660+ 用例）
./.venv/bin/pytest -k stream      # 流式相关
./.venv/bin/pytest tests/providers/  # provider 单测
./.venv/bin/pytest tests/storage/    # 存储原子性/权限
```

## Git 提交前安全注意

`.gitignore` 已忽略 `.venv/`、`.opentoken/`、`tmp/`、`*.log`。**永远不要提交** `~/.opentoken/` 任何内容、导出的 cookie / token 文件、`.env*`、含 token 的调试日志。提交前先 `git status`，发现凭证文件就停。

## License

MIT —— 见 `LICENSE`。

<br>

---

<a id="english"></a>

# English

> Switch to Chinese: [🇨🇳 中文](#中文)

A single local **OpenAI-compatible gateway** that fronts many LLM providers — web sessions, browser-harvested cookies, and direct API keys — behind one unified surface. Your downstream client speaks one OpenAI-style dialect; how each provider logs in, what protocol it streams, and how its `<tool_calls>` markup gets normalized is the gateway's problem.

## What it solves

If you use DeepSeek, Qwen, Kimi, Doubao, GLM, Claude, Gemini, ChatGPT, Grok, and Mimo side by side, you've hit it: every provider has a different login, a different model namespace, a different streaming dialect. OpenToken (1) manages credentials in one place, (2) exposes one OpenAI-compatible gateway, (3) maps every provider's models to a uniform call shape, and (4) aligns streaming, tool-calls, and response envelopes to OpenAI's spec.

## Supported providers

**Web sessions / browser-harvested (11)**: DeepSeek · Qwen International · Qwen China · Kimi · Claude · Doubao · ChatGPT · Gemini · Grok · GLM International · GLM China · Xiaomi Mimo.

**Direct API keys (4)**:
- **Manus** (official API)
- **NVIDIA NIM** — free 40 RPM via `integrate.api.nvidia.com/v1`, covering DeepSeek R1 / Llama 3.3 70B / Qwen 2.5 72B & Coder 32B / Mixtral 8x22B and more. Just a NVIDIA account → `nvapi-...` key, no card needed.
- **Unified Proxy (LiteLLM)** — one adapter, 100+ backends through LiteLLM (OpenRouter / Groq / Together / Bedrock / Anthropic / OpenAI / Perplexity / Cohere / Mistral / xAI / Fireworks / DeepInfra / Azure / Ollama / LM Studio …). Soft dependency, install with `uv sync --extra unified`.

## `/v1/models` is fully live-discovered

Each provider discovers its catalog live; any failure soft-degrades to empty. Results cache in `~/.opentoken/model-catalog-cache.json` (6h TTL); cold-start runs every discoverer concurrently under a 45s deadline so one slow provider can't hold up the rest.

| Provider | Discovery |
|----------|-----------|
| qwen-intl / qwen-cn / doubao / glm-cn | web page / dialog scrape (some via Camoufox browser) |
| glm-intl | `GET chat.z.ai/api/models`, fallback to homepage scrape |
| deepseek | `GET /api/v0/users/current` validates, returns the two wire models the protocol supports |
| kimi | scrape model metadata embedded in kimi.com homepage |
| nim | `GET integrate.api.nvidia.com/v1/models` (Bearer auth) |
| manus | `GET api.manus.im/api/v1/agents` |
| chatgpt | `GET /backend-api/models`, fallback to homepage |
| claude | `GET /api/organizations` + statsig chat-models config |
| gemini | scrape gemini.google.com app HTML |
| grok | scrape grok.com homepage |
| mimo | scrape xiaomimo.com homepage |
| unified | filter `litellm.model_cost` by the credentials' configured backends |

**Fallback floor**: qwen-intl's catalog is now JS-rendered; kimi's lives behind a gRPC-Connect endpoint — neither is scrape-able with httpx. When a logged-in provider's live discovery yields nothing, opentoken falls back to a minimal known-wire list (qwen-intl → `qwen3.6-plus`, `qwen-max-latest`; kimi → `k2`, `k1`) so chat still works and the provider doesn't silently vanish from `/v1/models`. Live discovery wins whenever it returns something.

## Requirements

Python **>= 3.13**, [`uv`](https://docs.astral.sh/uv/) recommended.

## On-disk layout

Credentials never enter the repo — everything lives under `~/.opentoken/`:

```
~/.opentoken/
├── config.json              # local gateway config (API key / host / port)
├── providers/<name>.json    # per-provider credentials
├── auth-profiles.json       # cross-provider auth profiles
├── provider-sessions.json   # session state (conversation_id ...; capped 256 LRU)
├── responses.json           # /v1/responses history (7d TTL, 1024 LRU)
├── files/, uploads/         # /v1/files & /v1/uploads binary blobs
└── model-catalog-cache.json # discovery cache
```

All credential/cookie/token/uploaded blobs are 0600 (owner-only); the directory tree is 0700 (not listable). Every JSON store uses atomic write (tmp + os.replace + flock) with sensitive=True chmod. On a shared host nobody else can read your sessions, conversation history, or uploaded files.

## Quick start

```bash
uv sync
uv run opentoken onboard      # scaffolds ~/.opentoken/
uv run opentoken start        # binds http://127.0.0.1:32117
```

Default base URL: `http://127.0.0.1:32117/v1`.

**Non-loopback binding warning**: `opentoken start --host 0.0.0.0` prints a stderr warning — that exposes every logged-in provider session beyond this machine. With no API key configured, the warning escalates to **UNAUTHENTICATED**.

## Local API key

OpenToken expects the **local gateway key** on inbound requests, not any upstream provider key.

```bash
cat ~/.opentoken/config.json
# {"api_key":"...","host":"127.0.0.1","port":32117}
```

- `config.json` **absent** (pre-first-run): keyless dev path.
- `config.json` exists but `api_key` is empty/whitespace: **503 fail-closed** (usually a rotation in progress, not an intent to disable auth).
- To genuinely run keyless, opt in explicitly with `"keyless_local": true`.
- `config.json` corrupt/unreadable (parse failure or permission denied): also **503 fail-closed**.

## Provider login

Single command: `uv run opentoken login <provider>`.

### A) Browser-based

Launches a real (Camoufox) Firefox, you log in, the cookies/headers land in `~/.opentoken/providers/<provider>.json`:

```bash
uv run opentoken login qwen international --browser
uv run opentoken login qwen china         --browser
uv run opentoken login deepseek           --browser
uv run opentoken login kimi               --browser
uv run opentoken login doubao             --browser
uv run opentoken login glm international  --browser
uv run opentoken login glm china          --browser
uv run opentoken login claude             --browser
uv run opentoken login chatgpt            --browser
uv run opentoken login gemini             --browser
uv run opentoken login grok               --browser
uv run opentoken login mimo               --browser
```

Login is dry-run validated: if existing credentials still work, freshly captured ones must pass an authenticated probe before they replace the working pair. First-time login skips the probe. Browser captures also pass a basic sanity check — at least one of cookie / bearer / access_token / Authorization header must be non-empty, or the record is refused.

### B) Manual cookie / header

```bash
uv run opentoken login qwen international \
  --cookie 'your_cookie_here' \
  --user-agent 'your user agent'

uv run opentoken login deepseek --header 'authorization=Bearer xxx'
```

### C) Direct API key

```bash
uv run opentoken login manus --api-key YOUR_KEY
uv run opentoken login nim   --api-key nvapi-XXXXXXXXXXXXXXXXXXXX
```

NIM credentials accept an optional `model_chain` for cross-model 429 fallback — a rate-limited model transparently switches to the next id in the list:

```json
{
  "kind": "api_key",
  "metadata": {
    "api_key": "nvapi-XXXXXXXXXXXXXXXXXXXX",
    "model_chain": "[\"deepseek-ai/deepseek-r1\", \"meta/llama-3.3-70b-instruct\", \"qwen/qwen2.5-72b-instruct\"]"
  },
  "status": "valid"
}
```

### D) Unified Proxy (LiteLLM)

```bash
uv sync --extra unified

uv run opentoken login unified \
  --header api_key_openrouter=sk-or-XXXXXXXXX \
  --header api_key_anthropic=sk-ant-XXXXXXXX \
  --header api_key_groq=gsk_XXXXXXXX
```

Then call with `unified/<backend>/<model>`: `unified/openrouter/anthropic/claude-3.5-sonnet`, `unified/groq/llama-3.3-70b-versatile`, etc.

**unified streaming + tool_calls is unsupported**: the streaming interface yields plain strings and can't carry structured tool_call deltas; if a backend emits tool_calls mid-stream opentoken raises a clear "retry with stream=false" error rather than silently dropping them.

### Listing & logout

```bash
uv run opentoken providers
uv run opentoken logout qwen international
```

## Verifying the gateway

```bash
curl http://127.0.0.1:32117/health     # → {"status":"ok"}
uv run opentoken status                # quick service status
uv run opentoken doctor                # system diagnostics
uv run opentoken verify                # contract checks (per-provider thread; one slow one doesn't block the rest)
```

Cross-provider E2E smoke (in a second terminal):

```bash
uv run python scripts/live_provider_smoke.py
```

Runs non-stream + stream + `/v1/responses` against every logged-in provider; per-provider pass/fail + first-byte latency lands in `live_provider_smoke_report.json`.

## OpenAI-compatible API

```bash
curl http://127.0.0.1:32117/v1/models -H 'Authorization: Bearer YOUR_LOCAL_GATEWAY_KEY'
```

Model ids look like `algae/qwen-intl/qwen3.6-plus`, `algae/deepseek/deepseek-chat`, `algae/nim/deepseek-ai/deepseek-r1`, `algae/unified/openrouter/anthropic/claude-3.5-sonnet`. The `algae/` prefix is an external-client namespace tag (kept as a wire-format contract). Alias resolution is **case-insensitive**.

**Chat Completions (streaming)**:

```bash
curl http://127.0.0.1:32117/v1/chat/completions \
  -H 'Authorization: Bearer YOUR_LOCAL_GATEWAY_KEY' \
  -H 'Content-Type: application/json' -N \
  -d '{
    "model": "algae/qwen-intl/qwen3.6-plus",
    "stream": true,
    "messages": [{"role": "user", "content": "Tell me about yourself"}]
  }'
```

Honored optional params: `temperature` · `max_tokens` · `top_p` · `tools` · `tool_choice`.

SSE conventions: first/last chunks carry `system_fingerprint`; the final `usage` chunk is followed by `[DONE]`; a provider's `<tool_calls>` protocol block at end-of-stream is re-emitted as a standard OpenAI `tool_calls` delta with `finish_reason="tool_calls"`.

`<think>` tags: for reasoner models the streaming path **keeps** `<think>...</think>` markup (clients can show live reasoning), while the non-stream path **strips** it. This is an intentional, test-pinned divergence.

**Responses API**:

```bash
curl http://127.0.0.1:32117/v1/responses \
  -H 'Authorization: Bearer YOUR_LOCAL_GATEWAY_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"model":"algae/qwen-intl/qwen3.6-plus","input":"summarize this"}'
```

When continuing via `previous_response_id`, the new request's `instructions` are **hoisted to the front** of the model context — otherwise the active system prompt would land after the entire prior conversation and be largely ignored. `max_output_tokens` maps onto the unified `max_tokens` field. **`<think>` content is stripped before history is saved** — `previous_response_id` continuations don't feed the model its own scratch reasoning back (cost would double and the model gets biased by its own draft).

**File upload**:

```bash
# single-shot
curl -X POST http://127.0.0.1:32117/v1/files \
  -H 'Authorization: Bearer YOUR_LOCAL_GATEWAY_KEY' \
  -F 'purpose=assistants' -F 'file=@./report.pdf'

# multipart
curl -X POST http://127.0.0.1:32117/v1/uploads \
  -H 'Authorization: Bearer YOUR_LOCAL_GATEWAY_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"filename":"big.bin","bytes":52428800,"purpose":"assistants","mime_type":"application/octet-stream"}'
```

- Each part capped at 100 MiB; declared total `bytes` of an upload also capped at 100 MiB (complete concatenates all parts in memory).
- Each incoming part is rejected with 413 if `existing_parts_bytes + new_part > declared bytes`.
- **`GET /v1/files/{id}/content` always returns `application/octet-stream` + `nosniff` + `attachment`** — never the caller-supplied mime_type, so an uploaded text/html or SVG blob can't execute as stored XSS in a browser-reachable deployment.

**`/v1/embeddings` currently returns 501**: the previous implementation produced SHA-256-derived pseudo-vectors that would have polluted any real RAG/vector store. Route embedding traffic to a real backend instead. `/v1/models` also no longer advertises `text-embedding-*` so SDK auto-discovery doesn't pick them up.

## Error classification

Both routes share a single classifier:

| Upstream error | Gateway returns |
|----------------|-----------------|
| Missing/invalid credentials, session expired, re-login hint, `unauthenticated` (Kimi gRPC), `no chat id` (Qwen) | **401** `authentication_error` |
| Upstream 429 | **429** `rate_limit_error` |
| Upstream 5xx / parse failure / gateway-side exception | **502** `api_error` (no upstream URL leaked) |
| `Unsupported model` / `No route configured` | **400** `invalid_request_error` |

A bare `expired` substring no longer triggers 401 — only `session/credentials/token expired` and similar auth phrases do; "upstream certificate expired" and the like correctly stay 502.

## Bridge to OpenClaw config

```bash
uv run opentoken config --dry-run
uv run opentoken config
uv run opentoken config --opentoken-config /path/to/openclaw-config.json
```

Atomic write (tmp + os.replace) + chmod 0600 — the patch contains the gateway apiKey.

## Troubleshooting

- **Empty `/v1/models`** → check `/health` and `opentoken providers`. A provider without valid credentials simply doesn't appear.
- **Always 401** → make sure the `Authorization: Bearer` is the **local gateway key** (`cat ~/.opentoken/config.json`).
- **Flaky streams** → first isolate with `curl -N`. Local gateway issues fail fast/timeout, upstream throttles surface as explicit rate-limit/error events.
- **`NS_ERROR_PROXY_CONNECTION_REFUSED` on browser providers** → the Camoufox-backed providers read the **OS-level** proxy config (independent of `HTTP_PROXY`); an unreachable system proxy surfaces this error. Pure-HTTP providers aren't affected.
- **Change bind address** → `opentoken start --host 0.0.0.0 --port 32117` prints a LAN-exposure warning.

## Development & tests

```bash
./.venv/bin/pytest                      # full suite (currently 660+ tests)
./.venv/bin/pytest -k stream            # streaming tests
./.venv/bin/pytest tests/providers/     # provider unit tests
./.venv/bin/pytest tests/storage/       # atomicity + permission tests
```

## Git hygiene

`.gitignore` already excludes `.venv/`, `.opentoken/`, `tmp/`, `*.log`. **Never commit** anything from `~/.opentoken/`, exported cookies/headers/tokens, `.env*`, or debug logs containing tokens. Always `git status` first; bail if any credential file is staged.

## License

MIT — see `LICENSE`.

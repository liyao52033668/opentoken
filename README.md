<div align="center">

# OpenToken

**🇨🇳 中文 · [🇬🇧 English](README.en.md)**

把多家 LLM 网页登录态 / API key 凭证统一成一个本地 OpenAI 兼容网关。

</div>

---

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

> 提示：部分浏览器登录（如 Kimi）需要你在登录完成后**手动关闭浏览器窗口**来触发凭证捕获；命令行里会打印提示。

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

SSE 协议约定：流式 chunk 完全对齐 OpenAI（`object=chat.completion.chunk`、首帧 `delta.role=assistant`、内容帧 `delta.content`、跨帧 `id` 一致、末帧 `finish_reason`、`data: [DONE]` 终止符）；provider 输出的 `<tool_calls>` 协议块在流末尾被重组为标准 OpenAI `tool_calls` delta，`finish_reason` 设为 `tool_calls`。

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

`/v1/chat/completions` 和 `/v1/responses` 共用同一个分类器（流式中途出错也走同一脱敏逻辑，绝不把上游 URL / session 泄漏进 SSE error 事件）：

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
- **某 provider 持续 429 / 验证码（如 Doubao）** → 上游对无头自动化的反爬，换个时间或换出口 IP 再试；网关侧会快速返回 429 而不是挂起。
- **切换监听地址** → `opentoken start --host 0.0.0.0` 会打非 loopback 警告。

## 开发与测试

```bash
./.venv/bin/pytest                # 全套（当前 669+ 用例）
./.venv/bin/pytest -k stream      # 流式相关
./.venv/bin/pytest tests/providers/  # provider 单测
./.venv/bin/pytest tests/storage/    # 存储原子性/权限
```

## Git 提交前安全注意

`.gitignore` 已忽略 `.venv/`、`.opentoken/`、`tmp/`、`*.log`。**永远不要提交** `~/.opentoken/` 任何内容、导出的 cookie / token 文件、`.env*`、含 token 的调试日志。提交前先 `git status`，发现凭证文件就停。

## License

MIT —— 见 `LICENSE`。

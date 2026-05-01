export type HttpMethod = "GET" | "POST" | "PATCH" | "DELETE";

export interface ParamDef {
  name: string;
  type: string;
  required: boolean;
  description: string;
  children?: ParamDef[];
}

export interface EndpointDef {
  id: string;
  method: HttpMethod;
  path: string;
  title: string;
  description: string;
  auth: "bearer" | "cookie" | "none";
  adminOnly?: boolean;
  category: string;
  requestParams?: ParamDef[];
  queryParams?: ParamDef[];
  pathParams?: ParamDef[];
  requestExample?: string;
  responseExample?: string;
}

export interface CategoryDef {
  id: string;
  title: string;
  description?: string;
}

export const CATEGORIES: CategoryDef[] = [
  { id: "auth", title: "认证", description: "认证方式与 Token 说明" },
  { id: "inference", title: "推理接口", description: "核心推理端点" },
  { id: "models", title: "模型列表", description: "查询可用模型" },
  { id: "developer", title: "开发者工具", description: "API Key、CLI 引导与配置" },
  { id: "user", title: "用户资源", description: "个人 API Key、凭证与用量" },
  { id: "admin", title: "管理员", description: "凭证池、配额与审计（需 admin 角色）" },
];

// ─── Inference ────────────────────────────────────────────────────────────────

const CHAT_REQUEST_PARAMS: ParamDef[] = [
  { name: "model", type: "string", required: true, description: "模型 ID，格式 provider/model，例如 claude-max/claude-sonnet-4-6 或 openai/gpt-4.1" },
  {
    name: "messages",
    type: "object[]",
    required: true,
    description: "对话消息列表",
    children: [
      { name: "role", type: "string", required: true, description: '"system" | "user" | "assistant"' },
      { name: "content", type: "string | object[]", required: true, description: "消息内容，支持纯文本或多模态数组" },
    ],
  },
  { name: "stream", type: "boolean", required: false, description: "是否流式响应（SSE），默认 false" },
  { name: "max_tokens", type: "number", required: false, description: "最大输出 token 数" },
  { name: "temperature", type: "number", required: false, description: "采样温度，0–2，默认取决于模型" },
  { name: "top_p", type: "number", required: false, description: "nucleus 采样阈值" },
];

const CHAT_RESPONSE = `{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1743200000,
  "model": "claude-max/claude-sonnet-4-6",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "Hello! How can I help you today?"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 10,
    "total_tokens": 22
  }
}`;

const MESSAGES_REQUEST_PARAMS: ParamDef[] = [
  { name: "model", type: "string", required: true, description: "模型 ID，格式 provider/model，例如 claude-max/claude-sonnet-4-6" },
  {
    name: "messages",
    type: "object[]",
    required: true,
    description: "对话消息列表",
    children: [
      { name: "role", type: "string", required: true, description: '"user" | "assistant"' },
      { name: "content", type: "string | object[]", required: true, description: "消息内容" },
    ],
  },
  { name: "max_tokens", type: "number", required: true, description: "最大输出 token 数（Anthropic API 必填）" },
  { name: "system", type: "string", required: false, description: "系统提示" },
  { name: "stream", type: "boolean", required: false, description: "是否流式响应（SSE）" },
];

const MESSAGES_RESPONSE = `{
  "id": "msg_abc123",
  "type": "message",
  "role": "assistant",
  "content": [{
    "type": "text",
    "text": "Hello! How can I help you today?"
  }],
  "model": "claude-sonnet-4-6",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 12,
    "output_tokens": 10
  }
}`;

const RESPONSES_REQUEST_PARAMS: ParamDef[] = [
  { name: "model", type: "string", required: true, description: "模型 ID，格式 provider/model，例如 openai/gpt-4.1" },
  { name: "input", type: "string | object[]", required: true, description: "输入内容，字符串或多模态数组" },
  { name: "instructions", type: "string", required: false, description: "系统级指令" },
  { name: "max_output_tokens", type: "number", required: false, description: "最大输出 token 数" },
  { name: "stream", type: "boolean", required: false, description: "是否流式响应（SSE）" },
  { name: "previous_response_id", type: "string", required: false, description: "上一轮 response ID，实现多轮对话" },
];

const RESPONSES_RESPONSE = `{
  "id": "resp_abc123",
  "object": "response",
  "created_at": 1743200000,
  "model": "gpt-4.1",
  "output": [{
    "type": "message",
    "role": "assistant",
    "content": [{
      "type": "output_text",
      "text": "Hello! How can I help you today?"
    }]
  }],
  "usage": {
    "input_tokens": 12,
    "output_tokens": 10,
    "total_tokens": 22
  }
}`;

// ─── Models ───────────────────────────────────────────────────────────────────

const MODELS_RESPONSE = `{
  "data": [
    {
      "id": "openai-codex/gpt-5.4",
      "display_name": "GPT-5.4 (Codex)",
      "provider": "openai-codex",
      "description": "GPT-5.4 via Codex OAuth backend.",
      "model_profile": "openai-codex/gpt-5.4",
      "supported_protocols": ["openai_chat", "openai_responses", "anthropic_messages"],
      "supported_clients": ["claude_code", "codex"],
      "auth_modes": ["codex_chatgpt_oauth_managed", "codex_chatgpt_oauth_imported"],
      "experimental": true,
      "source": "catalog"
    },
    {
      "id": "claude-max/claude-sonnet-4-6",
      "display_name": "Claude Sonnet 4.6",
      "provider": "claude-max",
      "description": "Latest Claude Sonnet",
      "model_profile": "anthropic/claude-sonnet-4-6",
      "supported_protocols": ["anthropic_messages"],
      "supported_clients": ["claude_code"],
      "auth_modes": ["oauth_subscription", "api_key"],
      "experimental": false,
      "source": "catalog"
    }
  ]
}`;

// ─── Developer ────────────────────────────────────────────────────────────────

const API_KEY_RESPONSE = `{
  "id": "key_abc123",
  "name": "My dev key",
  "api_key": "elp_...",
  "key_prefix": "elp_abc",
  "created_at": "2026-03-29T00:00:00+00:00"
}`;

const ROUTERCTL_BOOTSTRAP_RESPONSE = `{
  "bootstrap_token": "eyJ...",
  "expires_at": "2026-03-29T00:15:00+00:00",
  "install_command": "curl -sSL https://router.example.com/install/routerctl.sh | BOOTSTRAP_TOKEN=eyJ... bash"
}`;

const CLAUDE_CODE_BOOTSTRAP_RESPONSE = `{
  "id": "key_abc123",
  "api_key": "elp_...",
  "script": "#!/bin/bash\\nclaude config set api_key elp_...\\n...",
  "hosts_fallback": {"api.anthropic.com": "router.example.com"}
}`;

const CODEX_BOOTSTRAP_RESPONSE = `{
  "id": "key_abc123",
  "api_key": "elp_...",
  "script": "#!/bin/bash\\ncodexa config set api_key elp_...\\n...",
  "hosts_fallback": {}
}`;

// ─── User ─────────────────────────────────────────────────────────────────────

const CREDENTIAL_RESPONSE = `{
  "id": "cred_abc123",
  "provider": "claude-max",
  "auth_kind": "oauth_subscription",
  "account_id": "user@example.com",
  "visibility": "private",
  "billing_model": "subscription",
  "quota_info": {
    "windows": [
      {"label": "5小时配额", "used_pct": 42, "reset_at": "2026-03-29T05:00:00+00:00"},
      {"label": "7天配额", "used_pct": 15, "reset_at": "2026-04-05T00:00:00+00:00"}
    ]
  },
  "created_at": "2026-03-01T00:00:00+00:00"
}`;

const ACTIVITY_RESPONSE = `{
  "data": [
    {"date": "2026-03-29", "requests": 42, "tokens_in": 18200, "tokens_out": 9100}
  ],
  "period": "7d"
}`;

const LOGS_RESPONSE = `{
  "data": [
    {
      "id": "evt_abc123",
      "model": "claude-max/claude-sonnet-4-6",
      "tokens_in": 420,
      "tokens_out": 210,
      "latency_ms": 1240,
      "status": "success",
      "created_at": "2026-03-29T00:00:00+00:00"
    }
  ],
  "page": 1,
  "page_size": 50
}`;

const PREFERENCES_RESPONSE = `{
  "user_id": "user_abc123",
  "default_model": "claude-max/claude-sonnet-4-6",
  "routing_config": {}
}`;

// ─── Admin ────────────────────────────────────────────────────────────────────

const ADMIN_CREDENTIAL_RESPONSE = `{
  "id": "cred_abc123",
  "provider": "claude-max",
  "auth_kind": "oauth_subscription",
  "account_id": "shared@example.com",
  "visibility": "enterprise_pool",
  "max_concurrency": 3,
  "billing_model": "subscription",
  "created_at": "2026-03-01T00:00:00+00:00"
}`;

const QUOTA_RESPONSE = `{
  "id": "quota_abc123",
  "scope_type": "user",
  "scope_id": "user_abc123",
  "limit": 100000,
  "used": 42000,
  "created_at": "2026-03-01T00:00:00+00:00"
}`;

const USAGE_SUMMARY_RESPONSE = `{
  "data": [
    {
      "model": "claude-max/claude-sonnet-4-6",
      "requests": 420,
      "tokens_in": 180000,
      "tokens_out": 90000
    }
  ]
}`;

const CUSTOM_MODEL_RESPONSE = `{
  "id": "my-provider/my-model",
  "display_name": "My Custom Model",
  "provider": "my-provider",
  "model_profile": "openai/gpt-4",
  "upstream_model": "gpt-4",
  "description": "Custom model via OpenAI-compatible endpoint",
  "auth_modes": ["api_key"],
  "supported_clients": [],
  "enabled": true,
  "created_at": "2026-03-29T00:00:00+00:00",
  "updated_at": "2026-03-29T00:00:00+00:00"
}`;

// ─── Endpoint Definitions ─────────────────────────────────────────────────────

export const ENDPOINTS: EndpointDef[] = [
  // ── Inference ──────────────────────────────────────────────────────────────
  {
    id: "post-v1-chat-completions",
    method: "POST",
    path: "/v1/chat/completions",
    title: "聊天补全",
    description: "OpenAI 兼容的聊天补全端点。支持所有 provider 的模型，包括 Claude Max OAuth 和 OpenAI API Key。流式响应通过 `stream: true` 开启（SSE）。",
    auth: "bearer",
    category: "inference",
    requestParams: CHAT_REQUEST_PARAMS,
    requestExample: `curl {BASE}/v1/chat/completions \\
  -H "Authorization: Bearer elp_..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "claude-max/claude-sonnet-4-6",
    "messages": [{"role": "user", "content": "Hello"}]
  }'`,
    responseExample: CHAT_RESPONSE,
  },
  {
    id: "post-v1-messages",
    method: "POST",
    path: "/v1/messages",
    title: "Anthropic Messages",
    description: "原生 Anthropic Messages API。兼容 Claude Code 等直接调用 Anthropic API 的工具。仅支持 anthropic_messages 协议的模型（claude-max/ 和 anthropic/）。",
    auth: "bearer",
    category: "inference",
    requestParams: MESSAGES_REQUEST_PARAMS,
    requestExample: `curl {BASE}/v1/messages \\
  -H "Authorization: Bearer elp_..." \\
  -H "Content-Type: application/json" \\
  -H "anthropic-version: 2023-06-01" \\
  -d '{
    "model": "claude-max/claude-sonnet-4-6",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello"}]
  }'`,
    responseExample: MESSAGES_RESPONSE,
  },
  {
    id: "post-v1-responses",
    method: "POST",
    path: "/v1/responses",
    title: "OpenAI Responses",
    description: "OpenAI Responses API（新一代 API，替代 Chat Completions）。仅支持 openai_responses 协议的模型（openai/ 和 openai-codex/）。",
    auth: "bearer",
    category: "inference",
    requestParams: RESPONSES_REQUEST_PARAMS,
    requestExample: `curl {BASE}/v1/responses \\
  -H "Authorization: Bearer elp_..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "openai/gpt-4.1",
    "input": "Hello"
  }'`,
    responseExample: RESPONSES_RESPONSE,
  },

  // ── Models ─────────────────────────────────────────────────────────────────
  {
    id: "get-v1-models",
    method: "GET",
    path: "/v1/models",
    title: "列出可用模型",
    description: "返回当前用户当前真正可路由的模型列表。未配置凭证的静态目录项不会出现在这个接口里。",
    auth: "bearer",
    category: "models",
    requestExample: `curl {BASE}/v1/models \\
  -H "Authorization: Bearer elp_..."`,
    responseExample: MODELS_RESPONSE,
  },

  // ── Developer ──────────────────────────────────────────────────────────────
  {
    id: "post-developer-api-keys",
    method: "POST",
    path: "/developer/api-keys",
    title: "创建 API Key",
    description: "为当前用户创建一个新的 Platform API Key（`elp_` 前缀）。Key 只在创建时返回一次，请妥善保存。",
    auth: "bearer",
    category: "developer",
    requestParams: [
      { name: "name", type: "string", required: false, description: 'Key 名称，默认 "Developer key"' },
    ],
    requestExample: `curl -X POST {BASE}/developer/api-keys \\
  -H "Authorization: Bearer elp_..." \\
  -H "Content-Type: application/json" \\
  -d '{"name": "My CI key"}'`,
    responseExample: API_KEY_RESPONSE,
  },
  {
    id: "post-developer-bootstrap-routerctl",
    method: "POST",
    path: "/developer/bootstrap/routerctl",
    title: "引导安装 routerctl",
    description: "生成一次性 bootstrap token 和 `curl | bash` 安装命令，用于在开发机上安装 routerctl CLI。Token 15 分钟内有效，只能使用一次。",
    auth: "bearer",
    category: "developer",
    requestExample: `curl -X POST {BASE}/developer/bootstrap/routerctl \\
  -H "Authorization: Bearer elp_..."`,
    responseExample: ROUTERCTL_BOOTSTRAP_RESPONSE,
  },
  {
    id: "post-developer-bootstrap-claude-code",
    method: "POST",
    path: "/developer/bootstrap/claude-code",
    title: "引导配置 Claude Code",
    description: "创建 API Key 并返回配置 Claude Code 的 shell 脚本，自动设置 API Key 和路由端点。",
    auth: "bearer",
    category: "developer",
    requestParams: [
      { name: "model", type: "string", required: false, description: "指定 Claude Code 使用的默认模型，默认取服务器配置" },
    ],
    requestExample: `curl -X POST {BASE}/developer/bootstrap/claude-code \\
  -H "Authorization: Bearer elp_..." \\
  -H "Content-Type: application/json" \\
  -d '{"model": "claude-max/claude-sonnet-4-6"}'`,
    responseExample: CLAUDE_CODE_BOOTSTRAP_RESPONSE,
  },
  {
    id: "post-developer-bootstrap-codex",
    method: "POST",
    path: "/developer/bootstrap/codex",
    title: "引导配置 Codex CLI",
    description: "创建 API Key 并返回配置 OpenAI Codex CLI 的 shell 脚本。",
    auth: "bearer",
    category: "developer",
    requestParams: [
      { name: "model", type: "string", required: false, description: "指定 Codex 使用的默认模型，默认取服务器配置" },
    ],
    requestExample: `curl -X POST {BASE}/developer/bootstrap/codex \\
  -H "Authorization: Bearer elp_..." \\
  -H "Content-Type: application/json" \\
  -d '{"model": "openai-codex/gpt-5-codex"}'`,
    responseExample: CODEX_BOOTSTRAP_RESPONSE,
  },

  // ── User ───────────────────────────────────────────────────────────────────
  {
    id: "get-me-api-keys",
    method: "GET",
    path: "/me/api-keys",
    title: "我的 API Keys",
    description: "列出当前用户所有 Platform API Keys（不含完整 key，仅前缀）。",
    auth: "bearer",
    category: "user",
    requestExample: `curl {BASE}/me/api-keys \\
  -H "Authorization: Bearer elp_..."`,
    responseExample: `{"data": [{"id": "key_abc123", "name": "My CI key", "key_prefix": "elp_abc", "created_at": "2026-03-29T00:00:00+00:00"}]}`,
  },
  {
    id: "delete-me-api-keys",
    method: "DELETE",
    path: "/me/api-keys/{key_id}",
    title: "删除 API Key",
    description: "删除指定 Platform API Key。只能删除自己的 Key。",
    auth: "bearer",
    category: "user",
    pathParams: [
      { name: "key_id", type: "string", required: true, description: "API Key ID" },
    ],
    requestExample: `curl -X DELETE {BASE}/me/api-keys/key_abc123 \\
  -H "Authorization: Bearer elp_..."`,
    responseExample: `HTTP 204 No Content`,
  },
  {
    id: "get-me-preferences",
    method: "GET",
    path: "/me/preferences",
    title: "获取用户偏好",
    description: "获取当前用户的偏好配置，包含默认模型和路由参数。",
    auth: "bearer",
    category: "user",
    requestExample: `curl {BASE}/me/preferences \\
  -H "Authorization: Bearer elp_..."`,
    responseExample: PREFERENCES_RESPONSE,
  },
  {
    id: "patch-me-preferences",
    method: "PATCH",
    path: "/me/preferences",
    title: "更新用户偏好",
    description: "局部更新当前用户的偏好配置。",
    auth: "bearer",
    category: "user",
    requestParams: [
      { name: "default_model", type: "string", required: false, description: "默认模型 ID，例如 claude-max/claude-sonnet-4-6" },
      { name: "routing_config", type: "object", required: false, description: "路由参数（预留，当前为空对象）" },
    ],
    requestExample: `curl -X PATCH {BASE}/me/preferences \\
  -H "Authorization: Bearer elp_..." \\
  -H "Content-Type: application/json" \\
  -d '{"default_model": "claude-max/claude-sonnet-4-6"}'`,
    responseExample: PREFERENCES_RESPONSE,
  },
  {
    id: "get-me-upstream-credentials",
    method: "GET",
    path: "/me/upstream-credentials",
    title: "我的上游凭证",
    description: "列出当前用户自己添加的所有上游凭证（BYOK API Key、OAuth 导入等）。",
    auth: "bearer",
    category: "user",
    requestExample: `curl {BASE}/me/upstream-credentials \\
  -H "Authorization: Bearer elp_..."`,
    responseExample: `{"data": [${CREDENTIAL_RESPONSE}]}`,
  },
  {
    id: "post-me-upstream-credentials-api-key",
    method: "POST",
    path: "/me/upstream-credentials/api-key",
    title: "添加 BYOK API Key",
    description: "为指定 provider 添加 Bring-Your-Own-Key API Key。支持：anthropic、openai、zhipu、deepseek、qwen、minimax、jina；兼容端点：anthropic_compat、openai_compat（需要 base_url 和 provider_alias）。",
    auth: "bearer",
    category: "user",
    requestParams: [
      { name: "provider", type: "string", required: true, description: "Provider 名称，例如 anthropic、openai、zhipu、minimax、jina、anthropic_compat、openai_compat" },
      { name: "provider_alias", type: "string", required: false, description: "兼容端点的命名空间别名。compat provider 必填，模型 ID 会变成 provider_alias/model_name" },
      { name: "api_key", type: "string", required: true, description: "上游 API Key" },
      { name: "label", type: "string", required: false, description: "自定义标签，默认使用 provider 名" },
      { name: "base_url", type: "string", required: false, description: "兼容端点的 base URL（compat provider 必填）" },
      { name: "billing_model", type: "string", required: false, description: '"subscription" 或 "pay_per_use"，用于余额/配额显示' },
    ],
    requestExample: `curl -X POST {BASE}/me/upstream-credentials/api-key \\
  -H "Authorization: Bearer elp_..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "provider": "openai",
    "api_key": "sk-...",
    "label": "My OpenAI Key"
  }'`,
    responseExample: CREDENTIAL_RESPONSE,
  },
  {
    id: "post-me-upstream-credentials-share",
    method: "POST",
    path: "/me/upstream-credentials/{credential_id}/share",
    title: "共享凭证到企业池",
    description: "将个人凭证提升为企业共享池，供所有团队成员使用。只能共享自己的凭证。",
    auth: "bearer",
    category: "user",
    pathParams: [
      { name: "credential_id", type: "string", required: true, description: "凭证 ID" },
    ],
    requestExample: `curl -X POST {BASE}/me/upstream-credentials/cred_abc123/share \\
  -H "Authorization: Bearer elp_..."`,
    responseExample: CREDENTIAL_RESPONSE,
  },
  {
    id: "post-me-upstream-credentials-refresh-quota",
    method: "POST",
    path: "/me/upstream-credentials/{credential_id}/refresh-quota",
    title: "刷新凭证配额",
    description: "调用上游 provider API 查询最新余额或配额使用情况，并更新到本地记录。支持 zhipu、minimax（余额）和 claude-max、openai-codex（订阅配额）。",
    auth: "bearer",
    category: "user",
    pathParams: [
      { name: "credential_id", type: "string", required: true, description: "凭证 ID" },
    ],
    requestExample: `curl -X POST {BASE}/me/upstream-credentials/cred_abc123/refresh-quota \\
  -H "Authorization: Bearer elp_..."`,
    responseExample: CREDENTIAL_RESPONSE,
  },
  {
    id: "delete-me-upstream-credentials",
    method: "DELETE",
    path: "/me/upstream-credentials/{credential_id}",
    title: "删除上游凭证",
    description: "删除当前用户的指定上游凭证。只能删除自己的凭证。",
    auth: "bearer",
    category: "user",
    pathParams: [
      { name: "credential_id", type: "string", required: true, description: "凭证 ID" },
    ],
    requestExample: `curl -X DELETE {BASE}/me/upstream-credentials/cred_abc123 \\
  -H "Authorization: Bearer elp_..."`,
    responseExample: `HTTP 204 No Content`,
  },
  {
    id: "get-me-usage-activity",
    method: "GET",
    path: "/me/usage/activity",
    title: "用量趋势",
    description: "按天汇总当前用户的 API 调用次数和 Token 用量。",
    auth: "bearer",
    category: "user",
    queryParams: [
      { name: "period", type: "string", required: false, description: '时间窗口，格式 "Nd"（例如 7d、30d），默认 7d' },
    ],
    requestExample: `curl "{BASE}/me/usage/activity?period=7d" \\
  -H "Authorization: Bearer elp_..."`,
    responseExample: ACTIVITY_RESPONSE,
  },
  {
    id: "get-me-usage-activity-by-model",
    method: "GET",
    path: "/me/usage/activity/by-model",
    title: "按模型用量",
    description: "按模型维度汇总当前用户的 Token 用量。",
    auth: "bearer",
    category: "user",
    queryParams: [
      { name: "days", type: "number", required: false, description: "时间窗口天数，默认 7" },
    ],
    requestExample: `curl "{BASE}/me/usage/activity/by-model?days=7" \\
  -H "Authorization: Bearer elp_..."`,
    responseExample: `{"data": [{"model": "claude-max/claude-sonnet-4-6", "requests": 42, "tokens_in": 18000, "tokens_out": 9000}]}`,
  },
  {
    id: "get-me-usage-logs",
    method: "GET",
    path: "/me/usage/logs",
    title: "请求日志",
    description: "分页获取当前用户的请求历史记录，包含每次调用的模型、token 数、延迟和状态。",
    auth: "bearer",
    category: "user",
    queryParams: [
      { name: "page", type: "number", required: false, description: "页码，从 1 开始，默认 1" },
      { name: "page_size", type: "number", required: false, description: "每页条数，默认 50" },
    ],
    requestExample: `curl "{BASE}/me/usage/logs?page=1&page_size=20" \\
  -H "Authorization: Bearer elp_..."`,
    responseExample: LOGS_RESPONSE,
  },

  // ── Admin ──────────────────────────────────────────────────────────────────
  {
    id: "get-admin-credentials",
    method: "GET",
    path: "/admin/credentials",
    title: "列出所有凭证",
    description: "列出系统中所有上游凭证（企业池 + 所有个人凭证）。需要 admin 角色。",
    auth: "bearer",
    adminOnly: true,
    category: "admin",
    requestExample: `curl {BASE}/admin/credentials \\
  -H "Authorization: Bearer elp_admin_..."`,
    responseExample: `{"data": [${ADMIN_CREDENTIAL_RESPONSE}]}`,
  },
  {
    id: "post-admin-credentials",
    method: "POST",
    path: "/admin/credentials",
    title: "创建企业凭证",
    description: "在企业凭证池中直接创建一条凭证记录。需要 admin 角色。",
    auth: "bearer",
    adminOnly: true,
    category: "admin",
    requestParams: [
      { name: "provider", type: "string", required: true, description: "Provider 名称，例如 claude-max、openai" },
      { name: "auth_kind", type: "string", required: true, description: "认证类型：api_key | oauth_subscription | codex_chatgpt_oauth_managed | codex_chatgpt_oauth_imported" },
      { name: "account_id", type: "string", required: true, description: "账号标识（邮箱或标签）" },
      { name: "access_token", type: "string", required: false, description: "Access token 或 API Key" },
      { name: "max_concurrency", type: "number", required: false, description: "最大并发数，默认 1" },
      { name: "visibility", type: "string", required: false, description: '"enterprise_pool" | "private"，默认 enterprise_pool' },
      { name: "billing_model", type: "string", required: false, description: '"subscription" | "pay_per_use"' },
    ],
    requestExample: `curl -X POST {BASE}/admin/credentials \\
  -H "Authorization: Bearer elp_admin_..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "provider": "claude-max",
    "auth_kind": "oauth_subscription",
    "account_id": "shared@example.com",
    "access_token": "oauth_token_here",
    "max_concurrency": 3,
    "visibility": "enterprise_pool",
    "billing_model": "subscription"
  }'`,
    responseExample: ADMIN_CREDENTIAL_RESPONSE,
  },
  {
    id: "patch-admin-credentials",
    method: "PATCH",
    path: "/admin/credentials/{credential_id}",
    title: "修改凭证并发数",
    description: "修改指定上游凭证的最大并发数。`/admin/upstream-credentials/{credential_id}` 也支持同样的 PATCH 请求。",
    auth: "bearer",
    adminOnly: true,
    category: "admin",
    pathParams: [
      { name: "credential_id", type: "string", required: true, description: "凭证 ID" },
    ],
    requestParams: [
      { name: "max_concurrency", type: "number", required: true, description: "新的最大并发数，必须大于等于 1" },
    ],
    requestExample: `curl -X PATCH {BASE}/admin/credentials/cred_abc123 \\
  -H "Authorization: Bearer elp_admin_..." \\
  -H "Content-Type: application/json" \\
  -d '{"max_concurrency": 8}'`,
    responseExample: ADMIN_CREDENTIAL_RESPONSE,
  },
  {
    id: "delete-admin-credentials",
    method: "DELETE",
    path: "/admin/credentials/{credential_id}",
    title: "删除上游凭证",
    description: "删除指定上游凭证。`/admin/upstream-credentials/{credential_id}` 也支持同样的 DELETE 请求。",
    auth: "bearer",
    adminOnly: true,
    category: "admin",
    pathParams: [
      { name: "credential_id", type: "string", required: true, description: "凭证 ID" },
    ],
    requestExample: `curl -X DELETE {BASE}/admin/credentials/cred_abc123 \\
  -H "Authorization: Bearer elp_admin_..."`,
    responseExample: `HTTP 204 No Content`,
  },
  {
    id: "get-admin-quotas",
    method: "GET",
    path: "/admin/quotas",
    title: "列出配额规则",
    description: "列出所有用量配额规则（按用户或团队限制）。需要 admin 角色。",
    auth: "bearer",
    adminOnly: true,
    category: "admin",
    requestExample: `curl {BASE}/admin/quotas \\
  -H "Authorization: Bearer elp_admin_..."`,
    responseExample: `{"data": [${QUOTA_RESPONSE}]}`,
  },
  {
    id: "post-admin-quotas",
    method: "POST",
    path: "/admin/quotas",
    title: "设置配额",
    description: "为指定用户或团队设置 Token 用量上限（每月）。需要 admin 角色。",
    auth: "bearer",
    adminOnly: true,
    category: "admin",
    requestParams: [
      { name: "scope_type", type: "string", required: true, description: '"user" | "team"' },
      { name: "scope_id", type: "string", required: true, description: "用户 ID 或团队 ID" },
      { name: "limit", type: "number", required: true, description: "Token 上限（输入 + 输出 token 总数）" },
    ],
    requestExample: `curl -X POST {BASE}/admin/quotas \\
  -H "Authorization: Bearer elp_admin_..." \\
  -H "Content-Type: application/json" \\
  -d '{"scope_type": "user", "scope_id": "user_abc123", "limit": 1000000}'`,
    responseExample: QUOTA_RESPONSE,
  },
  {
    id: "get-admin-usage-summary",
    method: "GET",
    path: "/admin/usage/summary",
    title: "用量汇总",
    description: "按模型汇总全局用量统计。需要 admin 角色。",
    auth: "bearer",
    adminOnly: true,
    category: "admin",
    queryParams: [
      { name: "period", type: "string", required: false, description: '"7d" | "30d" | "all"，默认 30d' },
    ],
    requestExample: `curl "{BASE}/admin/usage/summary?period=30d" \\
  -H "Authorization: Bearer elp_admin_..."`,
    responseExample: USAGE_SUMMARY_RESPONSE,
  },
  {
    id: "get-admin-models",
    method: "GET",
    path: "/admin/models",
    title: "列出自定义模型",
    description: "列出所有管理员自定义模型（Custom Model Catalog）。需要 admin 角色。",
    auth: "bearer",
    adminOnly: true,
    category: "admin",
    requestExample: `curl {BASE}/admin/models \\
  -H "Authorization: Bearer elp_admin_..."`,
    responseExample: `{"data": [${CUSTOM_MODEL_RESPONSE}]}`,
  },
  {
    id: "post-admin-models",
    method: "POST",
    path: "/admin/models",
    title: "创建自定义模型",
    description: "在企业模型目录中添加自定义模型定义。需要 admin 角色。",
    auth: "bearer",
    adminOnly: true,
    category: "admin",
    requestParams: [
      { name: "id", type: "string", required: true, description: "模型 ID，格式 provider/model" },
      { name: "display_name", type: "string", required: true, description: "显示名称" },
      { name: "provider", type: "string", required: true, description: "Provider 名称" },
      { name: "model_profile", type: "string", required: true, description: "LiteLLM 模型标识，例如 openai/gpt-4" },
      { name: "upstream_model", type: "string", required: true, description: "上游模型名称" },
      { name: "description", type: "string", required: false, description: "模型描述" },
      { name: "auth_modes", type: "string[]", required: false, description: '认证类型列表，例如 ["api_key"]' },
      { name: "supported_clients", type: "string[]", required: false, description: '支持的客户端，例如 ["claude_code", "codex"]' },
      { name: "enabled", type: "boolean", required: false, description: "是否启用，默认 true" },
    ],
    requestExample: `curl -X POST {BASE}/admin/models \\
  -H "Authorization: Bearer elp_admin_..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "id": "my-provider/my-model",
    "display_name": "My Custom Model",
    "provider": "my-provider",
    "model_profile": "openai/gpt-4",
    "upstream_model": "gpt-4",
    "auth_modes": ["api_key"]
  }'`,
    responseExample: CUSTOM_MODEL_RESPONSE,
  },
  {
    id: "patch-admin-models",
    method: "PATCH",
    path: "/admin/models/{model_id}",
    title: "更新自定义模型",
    description: "局部更新指定自定义模型的字段。需要 admin 角色。",
    auth: "bearer",
    adminOnly: true,
    category: "admin",
    pathParams: [
      { name: "model_id", type: "string", required: true, description: "模型 ID，例如 my-provider/my-model" },
    ],
    requestParams: [
      { name: "display_name", type: "string", required: false, description: "显示名称" },
      { name: "enabled", type: "boolean", required: false, description: "是否启用" },
      { name: "description", type: "string", required: false, description: "模型描述" },
    ],
    requestExample: `curl -X PATCH {BASE}/admin/models/my-provider%2Fmy-model \\
  -H "Authorization: Bearer elp_admin_..." \\
  -H "Content-Type: application/json" \\
  -d '{"enabled": false}'`,
    responseExample: CUSTOM_MODEL_RESPONSE,
  },
  {
    id: "delete-admin-models",
    method: "DELETE",
    path: "/admin/models/{model_id}",
    title: "删除自定义模型",
    description: "从企业模型目录中删除指定自定义模型。需要 admin 角色。",
    auth: "bearer",
    adminOnly: true,
    category: "admin",
    pathParams: [
      { name: "model_id", type: "string", required: true, description: "模型 ID" },
    ],
    requestExample: `curl -X DELETE {BASE}/admin/models/my-provider%2Fmy-model \\
  -H "Authorization: Bearer elp_admin_..."`,
    responseExample: `{"status": "deleted", "id": "my-provider/my-model"}`,
  },
  {
    id: "get-admin-cli-sessions",
    method: "GET",
    path: "/admin/cli/sessions",
    title: "CLI 会话列表",
    description: "列出所有活跃的 CLI 会话 token（routerctl 登录产生）。需要 admin 角色。",
    auth: "bearer",
    adminOnly: true,
    category: "admin",
    requestExample: `curl {BASE}/admin/cli/sessions \\
  -H "Authorization: Bearer elp_admin_..."`,
    responseExample: `{"data": [{"jti": "jti_abc123", "kind": "cli_session", "email": "dev@example.com", "issued_at": "2026-03-29T00:00:00+00:00", "expires_at": "2026-03-29T08:00:00+00:00", "is_revoked": false}]}`,
  },
  {
    id: "post-admin-cli-revoke",
    method: "POST",
    path: "/admin/cli/revoke/{jti}",
    title: "吊销 CLI Token",
    description: "立即吊销指定 CLI 或 client_access token，使其无法再用于 API 调用。需要 admin 角色。",
    auth: "bearer",
    adminOnly: true,
    category: "admin",
    pathParams: [
      { name: "jti", type: "string", required: true, description: "Token JTI（唯一标识）" },
    ],
    requestExample: `curl -X POST {BASE}/admin/cli/revoke/jti_abc123 \\
  -H "Authorization: Bearer elp_admin_..."`,
    responseExample: `{"status": "revoked", "jti": "jti_abc123"}`,
  },
];

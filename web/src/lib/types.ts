export type UserRole = "admin" | "member";

export interface UiConfig {
  app_name: string;
  router_public_base_url: string;
  router_control_plane_base_url: string;
  routerctl_install_url: string;
  routerctl_windows_install_url: string;
  default_claude_model: string;
  default_codex_model: string;
  platform_api_key_env: string;
  feishu_authorize_url: string | null;
  codex_oauth_browser_enabled: boolean;
}

export interface UiSession {
  user_id: string;
  email: string;
  name: string;
  team_ids: string[];
  role: UserRole;
}

export interface UiModelRecord {
  id: string;
  display_name: string;
  provider: string;
  provider_alias?: string | null;
  description: string;
  model_profile: string;
  upstream_model?: string;
  supported_protocols: string[];
  supported_clients: string[];
  auth_modes: string[];
  experimental: boolean;
  source?: "catalog" | "byok" | "compat";
  context_length?: number;
}

export type PlatformApiKeyRecord = {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
};

export interface DeveloperApiKeyResponse {
  id: string;
  name: string;
  api_key: string;
  key_prefix: string;
  created_at: string;
}

export interface RouterctlBootstrapResponse {
  bootstrap_token: string;
  expires_at: string;
  install_command: string;
  windows_install_command: string;
}

export interface BootstrapResponse {
  id: string;
  api_key: string;
  script: string;
  hosts_fallback?: {
    enabled: boolean;
    domain?: string | null;
    target?: string | null;
  } | null;
}

export interface CredentialRecord {
  id: string;
  provider: string;
  auth_kind: string;
  account_id: string;
  provider_alias?: string | null;
  scopes: string[];
  state: string;
  expires_at: string | null;
  cooldown_until: string | null;
  owner_principal_id?: string | null;
  visibility?: string;
  source?: string | null;
  max_concurrency: number;
  concurrent_leases: number;
  billing_model?: "subscription" | "pay_per_use" | null;
  quota_info?: {
    windows?: Array<{ label: string; used_pct: number; reset_at: string }>;
  } | null;
  billing_info?: {
    balance_cny?: number | null;
    input_cost_per_1m?: number | null;
    output_cost_per_1m?: number | null;
    currency?: string;
  } | null;
  catalog_info?: {
    available_models?: string[];
  } | null;
}

export type UpstreamCredentialRecord = CredentialRecord;

export interface OAuthFlowStartResponse {
  authorize_url: string;
  state: string;
}

export interface QuotaRule {
  scope_type: string;
  scope_id: string;
  limit: number;
}

export interface UsageSummaryRecord {
  principal_id: string;
  principal_email: string | null;
  model_profile: string;
  tokens_in: number;
  tokens_out: number;
  request_count: number;
}

export interface UsageEventRecord {
  request_id: string;
  principal_id: string;
  model_profile: string;
  provider: string;
  credential_id: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  status: string;
  created_at: number;
}

export interface IssuedTokenRecord {
  jti: string;
  kind: string;
  principal_id: string;
  email: string;
  client: string | null;
  model: string | null;
  issued_at: string;
  expires_at: string;
  is_revoked: boolean;
}

export interface ActivityPoint {
  date: string;          // "2026-03-21"
  tokens_in: number;
  tokens_out: number;
  request_count: number;
}

export interface UsageLogEntry {
  request_id: string;
  principal_id: string;
  model_profile: string;
  provider: string;
  credential_id: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  status: string;
  created_at: number;    // unix timestamp
}

export interface UserPreferences {
  user_id: string;
  default_model: string | null;
  routing_config: Record<string, unknown>;
}

export interface ModelActivityRecord {
  model_profile: string;
  tokens_in: number;
  tokens_out: number;
  request_count: number;
}

export interface CustomModelRecord {
  id: string;
  display_name: string;
  provider: string;
  model_profile: string;
  upstream_model: string;
  description: string;
  auth_modes: string[];
  supported_clients: string[];
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

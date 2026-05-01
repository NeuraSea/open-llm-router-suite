import {
  ApiError,
  type ActivityPoint,
  type BootstrapResponse,
  type CredentialRecord,
  type DeveloperApiKeyResponse,
  type IssuedTokenRecord,
  type OAuthFlowStartResponse,
  type PlatformApiKeyRecord,
  type QuotaRule,
  type RouterctlBootstrapResponse,
  type UiConfig,
  type UiModelRecord,
  type UiSession,
  type UpstreamCredentialRecord,
  type UsageEventRecord,
  type UsageSummaryRecord,
  type UsageLogEntry,
  type ModelActivityRecord,
  type CustomModelRecord,
  type UserPreferences,
} from "@/lib/types";

async function parseResponse(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return null;
  }
  const contentType = response.headers?.get?.("content-type") ?? "";
  if (contentType.includes("application/json") || (!contentType && typeof response.json === "function")) {
    return response.json();
  }
  if (typeof response.text === "function") {
    return response.text();
  }
  return null;
}

async function apiRequest<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    credentials: "same-origin",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const payload = await parseResponse(response);
  if (!response.ok) {
    const message =
      typeof payload === "object" && payload && "detail" in payload
        ? String((payload as { detail: string }).detail)
        : `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status, payload);
  }
  return payload as T;
}

export function getUiConfig() {
  return apiRequest<UiConfig>("/ui/config", { headers: {} });
}

export function getUiSession() {
  return apiRequest<UiSession>("/ui/session", { headers: {} });
}

export async function getUiModels(options?: unknown) {
  const routableOnly =
    typeof options === "object" &&
    options !== null &&
    "routableOnly" in options &&
    Boolean((options as { routableOnly?: boolean }).routableOnly);
  const query = routableOnly ? "?routable_only=true" : "";
  const payload = await apiRequest<{ data: UiModelRecord[] }>(`/ui/models${query}`, { headers: {} });
  return payload.data;
}

export function createDeveloperApiKey(name: string) {
  return apiRequest<DeveloperApiKeyResponse>("/developer/api-keys", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function bootstrapRouterctl() {
  return apiRequest<RouterctlBootstrapResponse>("/developer/bootstrap/routerctl", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function bootstrapClaudeCode(model: string) {
  return apiRequest<BootstrapResponse>("/developer/bootstrap/claude-code", {
    method: "POST",
    body: JSON.stringify({ model }),
  });
}

export function bootstrapCodex(model: string) {
  return apiRequest<BootstrapResponse>("/developer/bootstrap/codex", {
    method: "POST",
    body: JSON.stringify({ model }),
  });
}

export async function listCredentials() {
  const payload = await apiRequest<{ data: CredentialRecord[] }>("/admin/credentials", {
    headers: {},
  });
  return payload.data;
}

export function createCredential(input: {
  provider: string;
  auth_kind: string;
  account_id: string;
  scopes: string[];
  access_token?: string;
  refresh_token?: string;
  max_concurrency: number;
  owner_principal_id?: string;
  visibility?: string;
  source?: string;
}) {
  return apiRequest<CredentialRecord>("/admin/credentials", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function refreshCredential(credentialId: string) {
  return apiRequest<CredentialRecord>(`/admin/credentials/${credentialId}/refresh`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function updateCredential(
  credentialId: string,
  input: {
    max_concurrency: number;
  }
) {
  return apiRequest<CredentialRecord>(`/admin/credentials/${credentialId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function deleteCredential(credentialId: string): Promise<void> {
  await apiRequest<void>(`/admin/credentials/${credentialId}`, { method: "DELETE" });
}

export function promoteCredential(credentialId: string) {
  return apiRequest<CredentialRecord>(`/admin/upstream-credentials/${credentialId}/promote`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function demoteCredential(credentialId: string) {
  return apiRequest<CredentialRecord>(`/admin/upstream-credentials/${credentialId}/demote`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function listQuotas() {
  const payload = await apiRequest<{ data: QuotaRule[] }>("/admin/quotas", { headers: {} });
  return payload.data;
}

export function upsertQuota(input: QuotaRule) {
  return apiRequest<QuotaRule>("/admin/quotas", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function listUsage() {
  const payload = await apiRequest<{ data: UsageEventRecord[] }>("/admin/usage", {
    headers: {},
  });
  return payload.data;
}

export async function listUsageSummary(period: string = "30d") {
  const payload = await apiRequest<{ data: UsageSummaryRecord[] }>(
    `/admin/usage/summary?period=${encodeURIComponent(period)}`
  );
  return payload.data;
}

export async function listMyUpstreamCredentials() {
  const payload = await apiRequest<{ data: UpstreamCredentialRecord[] }>("/me/upstream-credentials", {
    headers: {},
  });
  return payload.data;
}

export function addByokApiKey(
  provider: string,
  apiKey: string,
  label?: string,
  baseUrl?: string,
  billingModel?: string,
  providerAlias?: string,
) {
  return apiRequest<import("./types").UpstreamCredentialRecord>("/me/upstream-credentials/api-key", {
    method: "POST",
    body: JSON.stringify({
      provider,
      provider_alias: providerAlias,
      api_key: apiKey,
      label,
      base_url: baseUrl,
      billing_model: billingModel,
    }),
  });
}

export function startCodexOAuthBinding() {
  return apiRequest<OAuthFlowStartResponse>("/me/upstream-credentials/codex-oauth/start", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function listMyApiKeys(): Promise<PlatformApiKeyRecord[]> {
  const payload = await apiRequest<{ data: PlatformApiKeyRecord[] }>("/me/api-keys");
  return payload.data;
}

export async function deleteMyApiKey(keyId: string): Promise<void> {
  await apiRequest<void>(`/me/api-keys/${keyId}`, { method: "DELETE" });
}

export async function listCliSessions(): Promise<IssuedTokenRecord[]> {
  const payload = await apiRequest<{ data: IssuedTokenRecord[] }>("/admin/cli/sessions");
  return payload.data;
}

export async function listCliActivations(): Promise<IssuedTokenRecord[]> {
  const payload = await apiRequest<{ data: IssuedTokenRecord[] }>("/admin/cli/activations");
  return payload.data;
}

export async function revokeToken(jti: string): Promise<void> {
  await apiRequest<void>(`/admin/cli/revoke/${jti}`, { method: "POST" });
}

export function shareUpstreamCredential(credentialId: string) {
  return apiRequest<UpstreamCredentialRecord>(`/me/upstream-credentials/${credentialId}/share`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function deleteMyUpstreamCredential(credentialId: string): Promise<void> {
  await apiRequest<void>(`/me/upstream-credentials/${credentialId}`, { method: "DELETE" });
}

export async function getMyStats(): Promise<{
  requests_this_month: number;
  tokens_this_month: number;
  active_api_keys: number;
}> {
  return apiRequest("/me/stats");
}

export async function getMyActivity(period: string = "7d"): Promise<{ data: ActivityPoint[]; period: string }> {
  return apiRequest(`/me/usage/activity?period=${period}`);
}

export async function getMyLogs(page: number = 1, pageSize: number = 50): Promise<{ data: UsageLogEntry[]; page: number; page_size: number }> {
  return apiRequest(`/me/usage/logs?page=${page}&page_size=${pageSize}`);
}

export async function getMyActivityByModel(period: string): Promise<{ data: ModelActivityRecord[] }> {
  const days = period === "7d" ? 7 : period === "30d" ? 30 : 90;
  return apiRequest(`/me/usage/activity/by-model?days=${days}`);
}

export async function getMyPreferences(): Promise<UserPreferences> {
  return apiRequest("/me/preferences");
}

export async function patchMyPreferences(patch: Partial<Pick<UserPreferences, "default_model" | "routing_config">>): Promise<UserPreferences> {
  return apiRequest("/me/preferences", { method: "PATCH", body: JSON.stringify(patch) });
}

export function refreshCredentialQuota(credentialId: string) {
  return apiRequest<UpstreamCredentialRecord>(`/me/upstream-credentials/${credentialId}/refresh-quota`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function listAdminModels(): Promise<CustomModelRecord[]> {
  const payload = await apiRequest<{ data: CustomModelRecord[] }>("/admin/models", { headers: {} });
  return payload.data;
}

export function createAdminModel(input: Omit<CustomModelRecord, "created_at" | "updated_at">) {
  return apiRequest<CustomModelRecord>("/admin/models", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function patchAdminModel(modelId: string, patch: Partial<CustomModelRecord>) {
  return apiRequest<CustomModelRecord>(`/admin/models/${modelId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteAdminModel(modelId: string): Promise<void> {
  await apiRequest<void>(`/admin/models/${modelId}`, { method: "DELETE" });
}

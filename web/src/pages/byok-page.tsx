import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { Select } from "@/components/ui/select";

import { CodePanel } from "@/components/code-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  addByokApiKey,
  deleteMyUpstreamCredential,
  listMyUpstreamCredentials,
  refreshCredentialQuota,
  shareUpstreamCredential,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatProviderLabel } from "@/lib/provider-labels";
import type { UpstreamCredentialRecord } from "@/lib/types";

interface ProviderDef {
  id: string;
  label: string;
  placeholder: string;
  needsBaseUrl?: boolean;
  baseUrlPlaceholder?: string;
  defaultBaseUrl?: string;
}

const API_KEY_PROVIDERS: ProviderDef[] = [
  { id: "anthropic", label: formatProviderLabel("anthropic"), placeholder: "sk-ant-..." },
  { id: "openai", label: formatProviderLabel("openai"), placeholder: "sk-..." },
  { id: "zhipu", label: formatProviderLabel("zhipu"), placeholder: "..." },
  { id: "deepseek", label: formatProviderLabel("deepseek"), placeholder: "sk-..." },
  { id: "qwen", label: formatProviderLabel("qwen"), placeholder: "sk-..." },
  { id: "minimax", label: formatProviderLabel("minimax"), placeholder: "..." },
  { id: "jina", label: formatProviderLabel("jina"), placeholder: "jina_..." },
];

const COMPAT_PROVIDERS: ProviderDef[] = [
  {
    id: "anthropic_compat",
    label: formatProviderLabel("anthropic_compat"),
    placeholder: "sk-...",
    needsBaseUrl: true,
    baseUrlPlaceholder: "https://my-server.com/v1",
    defaultBaseUrl: "https://api.anthropic.com/v1",
  },
  {
    id: "openai_compat",
    label: formatProviderLabel("openai_compat"),
    placeholder: "sk-...",
    needsBaseUrl: true,
    baseUrlPlaceholder: "https://my-server.com/v1",
    defaultBaseUrl: "https://api.openai.com/v1",
  },
];

function formatExpiry(expiresAt: string | null): string {
  if (!expiresAt) return "未披露";
  return new Date(expiresAt).toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" });
}

function stateBadgeVariant(state: string): "default" | "secondary" | "outline" | "destructive" {
  if (state === "active" || state === "ready") return "default";
  if (state === "expired" || state === "error") return "destructive";
  return "secondary";
}

export function ByokPage() {
  const queryClient = useQueryClient();
  const [addingProvider, setAddingProvider] = useState<string | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [labelInput, setLabelInput] = useState("");
  const [baseUrlInput, setBaseUrlInput] = useState("");
  const [billingModelInput, setBillingModelInput] = useState("");
  const [providerAliasInput, setProviderAliasInput] = useState("");

  const credentialsQuery = useQuery({
    queryKey: ["me", "upstream-credentials"],
    queryFn: listMyUpstreamCredentials,
  });

  const addApiKeyMutation = useMutation({
    mutationFn: ({ provider, apiKey, label, baseUrl, billingModel, providerAlias }: { provider: string; apiKey: string; label: string; baseUrl?: string; billingModel?: string; providerAlias?: string }) =>
      addByokApiKey(provider, apiKey, label || undefined, baseUrl || undefined, billingModel || undefined, providerAlias || undefined),
    onSuccess: (newCred) => {
      queryClient.setQueryData<UpstreamCredentialRecord[]>(
        ["me", "upstream-credentials"],
        (current) => [...(current ?? []), newCred]
      );
      queryClient.invalidateQueries({ queryKey: ["ui-models"] });
      setAddingProvider(null);
      setApiKeyInput("");
      setLabelInput("");
      setBaseUrlInput("");
      setBillingModelInput("");
      setProviderAliasInput("");
    },
  });

  const shareMutation = useMutation({
    mutationFn: shareUpstreamCredential,
    onSuccess: (updated) => {
      queryClient.setQueryData<UpstreamCredentialRecord[]>(
        ["me", "upstream-credentials"],
        (current) => (current ?? []).map((c) => (c.id === updated.id ? updated : c))
      );
    },
  });

  const refreshQuotaMutation = useMutation({
    mutationFn: refreshCredentialQuota,
    onSuccess: (updated) => {
      queryClient.setQueryData<UpstreamCredentialRecord[]>(
        ["me", "upstream-credentials"],
        (current) => (current ?? []).map((c) => (c.id === updated.id ? updated : c))
      );
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteMyUpstreamCredential,
    onSuccess: (_data, credentialId) => {
      queryClient.setQueryData<UpstreamCredentialRecord[]>(
        ["me", "upstream-credentials"],
        (current) => (current ?? []).filter((c) => c.id !== credentialId)
      );
    },
  });

  function handleDelete(credential: UpstreamCredentialRecord) {
    if (
      !window.confirm(
        `确定要删除凭证 "${credential.account_id}"（${formatProviderLabel(credential.provider)}）吗？此操作不可撤销。`
      )
    ) {
      return;
    }
    deleteMutation.mutate(credential.id);
  }

  function handleAddApiKey() {
    if (!addingProvider || !apiKeyInput.trim()) return;
    addApiKeyMutation.mutate({
      provider: addingProvider,
      apiKey: apiKeyInput.trim(),
      label: labelInput.trim(),
      baseUrl: baseUrlInput.trim() || undefined,
      billingModel: billingModelInput || undefined,
      providerAlias: providerAliasInput.trim() || undefined,
    });
  }

  function openProvider(p: ProviderDef) {
    if (addingProvider === p.id) {
      setAddingProvider(null);
      setApiKeyInput("");
      setLabelInput("");
      setBaseUrlInput("");
      setProviderAliasInput("");
    } else {
      setAddingProvider(p.id);
      setApiKeyInput("");
      setLabelInput("");
      setBaseUrlInput(p.defaultBaseUrl ?? "");
      setBillingModelInput("");
      setProviderAliasInput("");
    }
  }

  const credentials = credentialsQuery.data ?? [];
  const allProviders = [...API_KEY_PROVIDERS, ...COMPAT_PROVIDERS];
  const selectedProviderMeta = allProviders.find((p) => p.id === addingProvider);

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="space-y-1">
        <div className="flex items-center gap-3">
          <div className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Link2 className="h-4 w-4" />
          </div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">BYOK</h2>
        </div>
        <p className="text-sm leading-6 text-muted-foreground">
          将你自己的 Provider 账号绑定到 Router，请求优先消耗你自己的额度。
        </p>
      </div>

      {/* Add API Key section */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-lg">添加 API Key</CardTitle>
          <CardDescription>
            支持 Anthropic、OpenAI 及国内主流模型 Provider 的 API Key 直连接入。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Standard providers */}
          <div className="space-y-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">标准 Provider</div>
            <div className="flex flex-wrap gap-2">
              {API_KEY_PROVIDERS.map((p) => (
                <Button
                  key={p.id}
                  variant={addingProvider === p.id ? "default" : "outline"}
                  size="sm"
                  onClick={() => openProvider(p)}
                >
                  {addingProvider === p.id ? (
                    <X className="mr-1.5 h-3.5 w-3.5" />
                  ) : (
                    <Plus className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {p.label}
                </Button>
              ))}
            </div>
          </div>

          {/* Compat providers */}
          <div className="space-y-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">自定义兼容接口</div>
            <div className="flex flex-wrap gap-2">
              {COMPAT_PROVIDERS.map((p) => (
                <Button
                  key={p.id}
                  variant={addingProvider === p.id ? "default" : "outline"}
                  size="sm"
                  onClick={() => openProvider(p)}
                >
                  {addingProvider === p.id ? (
                    <X className="mr-1.5 h-3.5 w-3.5" />
                  ) : (
                    <Plus className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {p.label}
                </Button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              自托管或第三方的 Anthropic / OpenAI 兼容端点，指定 Base URL 后可直接接入。
            </p>
          </div>

          {/* Form */}
          {addingProvider && selectedProviderMeta ? (
            <div className="rounded-lg border border-border bg-secondary/30 p-4 space-y-3">
              <div className="text-sm font-medium text-foreground">
                添加 {selectedProviderMeta.label}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">API Key</label>
                  <Input
                    placeholder={selectedProviderMeta.placeholder}
                    value={apiKeyInput}
                    onChange={(e) => setApiKeyInput(e.target.value)}
                    type="password"
                    className="font-mono text-sm"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">名称（可选）</label>
                  <Input
                    placeholder="如：个人账号"
                    value={labelInput}
                    onChange={(e) => setLabelInput(e.target.value)}
                    className="text-sm"
                  />
                </div>
                {selectedProviderMeta.needsBaseUrl ? (
                  <div className="space-y-1 sm:col-span-2">
                    <label className="text-xs text-muted-foreground">Base URL</label>
                    <Input
                      placeholder={selectedProviderMeta.baseUrlPlaceholder}
                      value={baseUrlInput}
                      onChange={(e) => setBaseUrlInput(e.target.value)}
                      className="font-mono text-sm"
                    />
                  </div>
                ) : null}
                {selectedProviderMeta.needsBaseUrl ? (
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">Provider Alias</label>
                    <Input
                      placeholder="如：zai-org / mirothinker-1.7"
                      value={providerAliasInput}
                      onChange={(e) => setProviderAliasInput(e.target.value)}
                      className="font-mono text-sm"
                    />
                  </div>
                ) : null}
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">计费方式（可选）</label>
                  <Select
                    value={billingModelInput}
                    onChange={(e) => setBillingModelInput(e.target.value)}
                  >
                    <option value="">不指定</option>
                    <option value="subscription">订阅制</option>
                    <option value="pay_per_use">按量计费</option>
                  </Select>
                </div>
              </div>
              {addApiKeyMutation.error ? (
                <div className="text-sm text-red-700">{String(addApiKeyMutation.error)}</div>
              ) : null}
              <div className="flex gap-2">
                <Button
                  size="sm"
                  onClick={handleAddApiKey}
                  disabled={
                    !apiKeyInput.trim() ||
                    (selectedProviderMeta.needsBaseUrl ? !baseUrlInput.trim() : false) ||
                    (selectedProviderMeta.needsBaseUrl ? !providerAliasInput.trim() : false) ||
                    addApiKeyMutation.isPending
                  }
                >
                  {addApiKeyMutation.isPending ? "保存中…" : "保存"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setAddingProvider(null);
                    setApiKeyInput("");
                    setLabelInput("");
                    setBaseUrlInput("");
                    setProviderAliasInput("");
                  }}
                >
                  取消
                </Button>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* OAuth bindings (Codex / Claude Code) */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-lg">OAuth 绑定</CardTitle>
          <CardDescription>通过 routerctl CLI 完成 OAuth 授权绑定。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <CodePanel
            title="绑定 Codex（ChatGPT Plus / Pro）"
            value="routerctl codex bind"
            hint="执行后在浏览器完成 ChatGPT OAuth 授权。"
          />
        </CardContent>
      </Card>

      {/* Credentials list */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-lg">我的上游绑定</CardTitle>
          <CardDescription>
            {credentials.length > 0
              ? `共 ${credentials.length} 个绑定凭证。`
              : "还没有绑定任何上游凭证。"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {credentialsQuery.isLoading ? (
            <div className="py-8 text-center text-sm text-muted-foreground">正在加载…</div>
          ) : credentialsQuery.error ? (
            <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              加载失败：{String(credentialsQuery.error)}
            </div>
          ) : credentials.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-secondary/40 px-6 py-8 text-center">
              <div className="mb-1 text-sm font-medium text-foreground">还没有绑定上游账号</div>
              <p className="text-sm text-muted-foreground">
                添加 API Key 或执行 routerctl bind 命令完成绑定。
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {credentials.map((credential) => (
                <CredentialCard
                  key={credential.id}
                  credential={credential}
                  isSharing={shareMutation.isPending && shareMutation.variables === credential.id}
                  isDeleting={deleteMutation.isPending && deleteMutation.variables === credential.id}
                  isRefreshing={refreshQuotaMutation.isPending && refreshQuotaMutation.variables === credential.id}
                  onShare={() => shareMutation.mutate(credential.id)}
                  onDelete={() => handleDelete(credential)}
                  onRefreshQuota={() => refreshQuotaMutation.mutate(credential.id)}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function CredentialCard({
  credential,
  isSharing,
  isDeleting,
  isRefreshing,
  onShare,
  onDelete,
  onRefreshQuota,
}: {
  credential: UpstreamCredentialRecord;
  isSharing: boolean;
  isDeleting: boolean;
  isRefreshing: boolean;
  onShare: () => void;
  onDelete: () => void;
  onRefreshQuota: () => void;
}) {
  const isInPool = credential.visibility === "enterprise_pool";
  const needsCompatReconfig =
    (credential.provider === "openai_compat" || credential.provider === "anthropic_compat") &&
    (!credential.provider_alias || !(credential.catalog_info?.available_models?.length));

  return (
    <Card className="border-border">
      <CardContent className="flex flex-col gap-4 p-5 md:flex-row md:items-start md:justify-between">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="text-base font-semibold text-foreground">{credential.account_id}</div>
            <Badge variant="secondary">{formatProviderLabel(credential.provider)}</Badge>
            <Badge variant={stateBadgeVariant(credential.state)}>{credential.state}</Badge>
            <Badge variant="outline">{credential.visibility ?? "private"}</Badge>
            {credential.source ? <Badge variant="outline">{credential.source}</Badge> : null}
            {credential.provider_alias ? <Badge variant="outline">{credential.provider_alias}</Badge> : null}
            {credential.billing_model === "subscription" ? (
              <Badge variant="secondary">订阅制</Badge>
            ) : credential.billing_model === "pay_per_use" ? (
              <Badge variant="outline">按量计费</Badge>
            ) : null}
            {needsCompatReconfig ? <Badge variant="destructive">需要重配</Badge> : null}
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
            <span className="text-muted-foreground">认证方式</span>
            <span className="text-foreground">{credential.auth_kind}</span>
            {credential.expires_at ? (
              <>
                <span className="text-muted-foreground">过期时间</span>
                <span className="font-mono text-xs text-foreground">{formatExpiry(credential.expires_at)}</span>
              </>
            ) : null}
            <span className="text-muted-foreground">并发占用 / 上限</span>
            <span className="font-mono text-xs text-foreground">
              {credential.concurrent_leases} / {credential.max_concurrency}
            </span>
          </div>
          {credential.billing_model === "subscription" ? (
            <div className="space-y-1 text-sm">
              <span className="text-muted-foreground">剩余配额</span>
              {credential.quota_info?.windows?.length ? (
                <div className="grid grid-cols-3 gap-x-4 gap-y-1 text-sm">
                  {credential.quota_info.windows.map((w) => (
                    <div key={w.label} className="contents">
                      <span className="text-foreground">{w.label}</span>
                      <span className="font-mono text-xs text-foreground">{w.used_pct}%</span>
                      <span className="font-mono text-xs text-muted-foreground">{w.reset_at}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-muted-foreground">暂无配额数据</div>
              )}
            </div>
          ) : credential.billing_model === "pay_per_use" ? (
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
              <span className="text-muted-foreground">余额</span>
              <span className="font-mono text-xs text-foreground">
                {credential.billing_info?.balance_cny != null
                  ? `¥${credential.billing_info.balance_cny}`
                  : "N/A"}
              </span>
              {credential.billing_info?.input_cost_per_1m != null ? (
                <>
                  <span className="text-muted-foreground">输入价格</span>
                  <span className="font-mono text-xs text-foreground">
                    ¥{credential.billing_info.input_cost_per_1m} / 1M tokens
                  </span>
                </>
              ) : null}
              {credential.billing_info?.output_cost_per_1m != null ? (
                <>
                  <span className="text-muted-foreground">输出价格</span>
                  <span className="font-mono text-xs text-foreground">
                    ¥{credential.billing_info.output_cost_per_1m} / 1M tokens
                  </span>
                </>
              ) : null}
            </div>
          ) : null}
          {needsCompatReconfig ? (
            <div className="rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
              这是旧版兼容端点凭证，没有 provider alias 或模型目录。删除后按新规则重新录入，模型 ID 将变成 `provider_alias/model_name`。
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 gap-2">
          {(credential.provider === "zhipu" ||
            credential.provider === "minimax" ||
            credential.provider === "claude-max" ||
            credential.provider === "openai-codex") && (
            <Button variant="outline" size="sm" onClick={onRefreshQuota} disabled={isRefreshing}>
              <RefreshCw className={cn("h-3.5 w-3.5", isRefreshing && "animate-spin")} />
              <span className="ml-1.5">
                {credential.provider === "zhipu" || credential.provider === "minimax"
                  ? "刷新余额"
                  : "刷新配额"}
              </span>
            </Button>
          )}
          {!isInPool ? (
            <Button
              variant="outline"
              size="sm"
              onClick={onShare}
              disabled={isSharing || isDeleting || needsCompatReconfig}
            >
              共享到企业池
            </Button>
          ) : (
            <div className="flex items-center text-sm font-medium text-emerald-700">
              已在企业池中可路由
            </div>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={onDelete}
            disabled={isDeleting || isSharing}
            className="text-red-600 hover:border-red-300 hover:bg-red-50 hover:text-red-700"
          >
            <Trash2 className="h-3.5 w-3.5" />
            <span className="ml-1.5">删除</span>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

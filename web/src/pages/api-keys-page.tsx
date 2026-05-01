import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, KeyRound, Search, Trash2 } from "lucide-react";

import { CodePanel } from "@/components/code-panel";
import { CopyButton } from "@/components/copy-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { createDeveloperApiKey, deleteMyApiKey, getMyActivity, getUiModels, listMyApiKeys } from "@/lib/api";
import { groupModelsByProvider } from "@/lib/model-groups";
import type { ActivityPoint, DeveloperApiKeyResponse, PlatformApiKeyRecord, UiModelRecord } from "@/lib/types";

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSeconds = Math.floor(diffMs / 1000);

  if (diffSeconds < 60) return "刚刚";
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes} 分钟前`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} 小时前`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays} 天前`;
  const diffMonths = Math.floor(diffDays / 30);
  return `${diffMonths} 个月前`;
}

export function ApiKeysPage() {
  const queryClient = useQueryClient();
  const [keyName, setKeyName] = useState("");
  const [newKey, setNewKey] = useState<DeveloperApiKeyResponse | null>(null);

  const keysQuery = useQuery({
    queryKey: ["me", "api-keys"],
    queryFn: listMyApiKeys,
  });

  const activityQuery = useQuery({
    queryKey: ["me", "activity", "7d"],
    queryFn: () => getMyActivity("7d"),
  });

  const modelsQuery = useQuery({
    queryKey: ["ui-models", "routable"],
    queryFn: () => getUiModels({ routableOnly: true }),
  });

  const groupedModels = groupModelsByProvider(modelsQuery.data ?? []);

  const createMutation = useMutation({
    mutationFn: () => createDeveloperApiKey(keyName.trim() || "My API Key"),
    onSuccess: (data) => {
      setNewKey(data);
      setKeyName("");
      void queryClient.invalidateQueries({ queryKey: ["me", "api-keys"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (keyId: string) => deleteMyApiKey(keyId),
    onSuccess: (_data, keyId) => {
      queryClient.setQueryData<PlatformApiKeyRecord[]>(["me", "api-keys"], (current) =>
        (current ?? []).filter((k) => k.id !== keyId)
      );
      if (newKey?.id === keyId) {
        setNewKey(null);
      }
    },
  });

  function handleDelete(key: PlatformApiKeyRecord) {
    if (!window.confirm(`确定要删除 API Key "${key.name}"（${key.key_prefix}...）吗？此操作不可撤销。`)) {
      return;
    }
    deleteMutation.mutate(key.id);
  }

  const keys = keysQuery.data ?? [];

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="space-y-1">
        <div className="flex items-center gap-3">
          <div className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <KeyRound className="h-4 w-4" />
          </div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">API Keys</h2>
        </div>
        <p className="text-sm leading-6 text-muted-foreground">
          创建平台 API Key，用于直接调用 Router 的推理接口。
        </p>
      </div>

      {/* Usage summary */}
      <UsageSummary data={activityQuery.data?.data} />

      {/* Available models */}
      <AvailableModels groups={groupedModels} isLoading={modelsQuery.isLoading} />

      {/* Create new key */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-lg">创建 API Key</CardTitle>
          <CardDescription>
            API Key 用于{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">
              Authorization: Bearer elp_...
            </code>{" "}
            请求头，或直接设置为{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">
              ANTHROPIC_AUTH_TOKEN
            </code>
            。所有模型统一用{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">provider/model</code>{" "}
            格式，如{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">claude-max/claude-sonnet-4-6</code>
            （Claude Max）或{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">openai/gpt-4o</code>
            （OpenAI BYOK）。兼容端点使用{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">provider_alias/model_name</code>{" "}
            格式。详见{" "}
            <a href="/portal/docs" className="font-medium text-foreground underline-offset-2 hover:underline">API 文档</a>
            。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-3">
            <Input
              placeholder="Key 名称（例如：本地开发）"
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !createMutation.isPending) {
                  createMutation.mutate();
                }
              }}
              className="max-w-sm"
            />
            <Button
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending}
            >
              创建
            </Button>
          </div>

          {createMutation.error ? (
            <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              {String(createMutation.error)}
            </div>
          ) : null}

          {newKey ? (
            <Card className="border-emerald-900/10 bg-emerald-50">
              <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0 pb-3">
                <div>
                  <CardTitle className="text-base">API Key 已签发</CardTitle>
                  <CardDescription className="text-amber-700">
                    请立即复制，此后只显示前缀。
                  </CardDescription>
                </div>
                <CopyButton value={newKey.api_key} />
              </CardHeader>
              <CardContent className="space-y-3">
                <CodePanel
                  title={newKey.name}
                  value={newKey.api_key}
                  hint="这是唯一一次显示完整 Key 的机会。"
                />
                <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
                  <span>名称：{newKey.name}</span>
                  <span>前缀：{newKey.key_prefix}</span>
                </div>
              </CardContent>
            </Card>
          ) : null}
        </CardContent>
      </Card>

      {/* Keys list */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-lg">我的 API Keys</CardTitle>
          <CardDescription>
            {keys.length > 0
              ? `共 ${keys.length} 个 Key，只显示前缀，原始值不可恢复。`
              : "还没有 API Key。"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {keysQuery.isLoading ? (
            <div className="py-8 text-center text-sm text-muted-foreground">正在加载…</div>
          ) : keys.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-secondary/40 px-6 py-8 text-center">
              <p className="text-sm text-muted-foreground">
                还没有 API Key。创建一个开始使用 Router。
              </p>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {keys.map((key) => (
                <KeyRow
                  key={key.id}
                  apiKey={key}
                  isDeleting={deleteMutation.isPending && deleteMutation.variables === key.id}
                  onDelete={() => handleDelete(key)}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function UsageSummary({ data }: { data: ActivityPoint[] | undefined }) {
  if (!data) return null;
  const totalIn = data.reduce((s, d) => s + d.tokens_in, 0);
  const totalOut = data.reduce((s, d) => s + d.tokens_out, 0);
  const totalReqs = data.reduce((s, d) => s + d.request_count, 0);

  return (
    <div className="grid grid-cols-3 gap-4">
      {[
        { label: "Input Tokens（7天）", value: totalIn.toLocaleString() },
        { label: "Output Tokens（7天）", value: totalOut.toLocaleString() },
        { label: "请求次数（7天）", value: totalReqs.toLocaleString() },
      ].map(({ label, value }) => (
        <Card key={label}>
          <CardContent className="p-5">
            <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">{label}</div>
            <div className="mt-2 text-2xl font-bold tabular-nums text-foreground">{value}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function AvailableModels({
  groups,
  isLoading,
}: {
  groups: [string, UiModelRecord[]][];
  isLoading: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  // providers that are expanded (default: all collapsed)
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());

  if (isLoading) return null;
  if (groups.length === 0) return null;

  const totalModels = groups.reduce((sum, [, models]) => sum + models.length, 0);

  const q = query.toLowerCase().trim();
  const filteredGroups: [string, UiModelRecord[]][] = q
    ? groups
        .map(([label, models]) => [
          label,
          models.filter(
            (m) =>
              m.display_name.toLowerCase().includes(q) ||
              m.id.toLowerCase().includes(q)
          ),
        ] as [string, UiModelRecord[]])
        .filter(([, models]) => models.length > 0)
    : groups;
  const filteredCount = filteredGroups.reduce((s, [, ms]) => s + ms.length, 0);

  function toggleGroup(label: string) {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg">可用模型</CardTitle>
            <CardDescription>
              {totalModels} 个模型可通过 API Key 调用。
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setExpanded(!expanded);
              if (expanded) {
                setQuery("");
                setOpenGroups(new Set());
              }
            }}
          >
            {expanded ? "收起" : "展开"}
          </Button>
        </div>
      </CardHeader>
      {expanded ? (
        <CardContent className="pt-0">
          {/* Search */}
          <div className="relative mb-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="搜索模型名称或 ID…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="h-8 pl-8 text-sm"
            />
          </div>

          {filteredCount === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">无匹配模型</p>
          ) : (
            <>
              <div className="divide-y divide-border">
                {filteredGroups.map(([groupLabel, models]) => {
                  // while searching, always expand; otherwise respect open/closed state
                  const isOpen = q ? true : openGroups.has(groupLabel);
                  return (
                    <div key={groupLabel}>
                      <button
                        type="button"
                        className="flex w-full items-center gap-2 py-2.5 text-left transition-colors hover:text-foreground"
                        onClick={() => {
                          if (!q) toggleGroup(groupLabel);
                        }}
                      >
                        <ChevronRight
                          className={[
                            "h-3 w-3 shrink-0 text-muted-foreground transition-transform duration-150",
                            isOpen ? "rotate-90" : "",
                          ].join(" ")}
                        />
                        <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                          {groupLabel}
                        </span>
                        <span className="rounded-full border border-border px-1.5 py-0.5 text-[10px] tabular-nums text-muted-foreground">
                          {models.length}
                        </span>
                      </button>
                      {isOpen ? (
                        <div className="divide-y divide-border pb-1 pl-5">
                          {models.map((model) => (
                            <ModelRow key={model.id} model={model} />
                          ))}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
              {q ? (
                <p className="pt-3 text-center text-xs text-muted-foreground">
                  {filteredCount} / {totalModels} 个匹配
                </p>
              ) : null}
            </>
          )}
        </CardContent>
      ) : null}
    </Card>
  );
}

function ModelRow({ model }: { model: UiModelRecord }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-sm font-medium text-foreground">{model.display_name}</span>
        <code className="w-fit font-mono text-[11px] text-muted-foreground">{model.id}</code>
      </div>
      <CopyButton value={model.id} label="复制 ID" className="shrink-0 h-7 text-xs" />
    </div>
  );
}

function KeyRow({
  apiKey,
  isDeleting,
  onDelete,
}: {
  apiKey: PlatformApiKeyRecord;
  isDeleting: boolean;
  onDelete: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-4 first:pt-0 last:pb-0">
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-foreground">{apiKey.name}</span>
          <Badge variant="secondary" className="font-mono text-xs">
            {apiKey.key_prefix}...
          </Badge>
        </div>
        <div className="text-xs text-muted-foreground">
          创建于 {formatRelativeTime(apiKey.created_at)}
        </div>
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={onDelete}
        disabled={isDeleting}
        className="shrink-0 text-red-600 hover:border-red-300 hover:bg-red-50 hover:text-red-700"
      >
        <Trash2 className="h-3.5 w-3.5" />
        <span className="ml-1.5">删除</span>
      </Button>
    </div>
  );
}

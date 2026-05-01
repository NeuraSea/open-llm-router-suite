import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Settings } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { getMyPreferences, getUiModels, patchMyPreferences } from "@/lib/api";
import { formatModelGroupLabel, modelGroupKey } from "@/lib/provider-labels";
import type { UiModelRecord, UserPreferences } from "@/lib/types";

export function PreferencesPage() {
  const queryClient = useQueryClient();

  const prefsQuery = useQuery({
    queryKey: ["me", "preferences"],
    queryFn: getMyPreferences,
  });

  const modelsQuery = useQuery({
    queryKey: ["ui-models", "routable"],
    queryFn: () => getUiModels({ routableOnly: true }),
  });

  const allModels = modelsQuery.data ?? [];

  const providers = useMemo(() => {
    const map = new Map<string, { source: string; count: number; label: string }>();
    for (const m of allModels) {
      const groupId = modelGroupKey(m.provider, m.provider_alias);
      const existing = map.get(groupId);
      if (existing) {
        existing.count++;
      } else {
        map.set(groupId, {
          source: m.source ?? "catalog",
          count: 1,
          label: formatModelGroupLabel(m.provider, m.provider_alias),
        });
      }
    }
    return [...map.entries()]
      .map(([id, { source, count, label }]) => ({ id, label, source, count }))
      .sort((a, b) => {
        const aByok = a.source === "byok" ? 1 : 0;
        const bByok = b.source === "byok" ? 1 : 0;
        return aByok - bByok || a.label.localeCompare(b.label);
      });
  }, [allModels]);

  const [selectedProvider, setSelectedProvider] = useState<string>("");
  const [defaultModel, setDefaultModel] = useState<string>("");
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Sync local state once preferences are loaded
  useEffect(() => {
    if (prefsQuery.data && !defaultModel) {
      setDefaultModel(prefsQuery.data.default_model ?? "");
    }
  }, [prefsQuery.data, defaultModel]);

  // When default model is set, auto-select its provider
  useEffect(() => {
    if (defaultModel && allModels.length > 0 && !selectedProvider) {
      const m = allModels.find((x) => x.id === defaultModel);
      if (m) setSelectedProvider(modelGroupKey(m.provider, m.provider_alias));
    }
  }, [defaultModel, allModels, selectedProvider]);

  const staleDefaultModel = Boolean(
    prefsQuery.data?.default_model &&
    !allModels.some((model) => model.id === prefsQuery.data?.default_model)
  );

  const filteredModels: UiModelRecord[] = allModels
    .filter((m) => !selectedProvider || modelGroupKey(m.provider, m.provider_alias) === selectedProvider);

  const saveMutation = useMutation({
    mutationFn: (patch: Partial<Pick<UserPreferences, "default_model" | "routing_config">>) =>
      patchMyPreferences(patch),
    onSuccess: (updated) => {
      queryClient.setQueryData<UserPreferences>(["me", "preferences"], updated);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    },
  });

  function handleSave() {
    saveMutation.mutate({ default_model: defaultModel || null });
  }

  function handleProviderClick(providerId: string) {
    setSelectedProvider(providerId === selectedProvider ? "" : providerId);
    // Clear model selection if it doesn't belong to the new provider
    if (defaultModel) {
      const m = allModels.find((x) => x.id === defaultModel);
      if (m && modelGroupKey(m.provider, m.provider_alias) !== providerId) {
        setDefaultModel("");
      }
    }
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="space-y-1">
        <div className="flex items-center gap-3">
          <div className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Settings className="h-4 w-4" />
          </div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">Preferences</h2>
        </div>
        <p className="text-sm leading-6 text-muted-foreground">
          配置你的默认模型和路由偏好。
        </p>
      </div>

      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-lg">个人偏好设置</CardTitle>
          <CardDescription>
            这里的设置将覆盖系统默认值，仅对你的账号生效。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {prefsQuery.isLoading || modelsQuery.isLoading ? (
            <div className="py-6 text-sm text-muted-foreground">正在加载…</div>
          ) : prefsQuery.error ? (
            <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              加载失败：{String(prefsQuery.error)}
            </div>
          ) : (
            <>
              {/* Default model — two-step selector */}
              <div className="space-y-3">
                <div>
                  <label className="text-sm font-medium text-foreground">
                    默认模型
                  </label>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    当请求未指定模型时使用。留空则使用系统全局默认。
                  </p>
                </div>

                {/* Step 1: Provider chips */}
                <div className="space-y-1.5">
                  <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                    1. 选择 Provider
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {providers.map((p) => {
                      const active = selectedProvider === p.id;
                      return (
                        <button
                          key={p.id}
                          type="button"
                          onClick={() => handleProviderClick(p.id)}
                          className={[
                            "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                            active
                              ? "border-foreground bg-foreground text-background"
                              : "border-border bg-background text-foreground hover:border-foreground/40",
                          ].join(" ")}
                        >
                          {p.label}
                          {p.source === "byok" ? (
                            <span className="rounded bg-current/10 px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide opacity-70">
                              BYOK
                            </span>
                          ) : null}
                          <span className="tabular-nums opacity-50">{p.count}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Step 2: Model select */}
                <div className="space-y-1.5">
                  <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                    2. 选择模型
                  </div>
                  <Select
                    id="default-model"
                    value={defaultModel}
                    onChange={(e) => setDefaultModel(e.target.value)}
                    className="max-w-sm"
                  >
                    <option value="">（使用系统默认）</option>
                    {filteredModels.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.display_name}
                        {model.source === "byok" ? " (BYOK)" : ""}
                      </option>
                    ))}
                  </Select>
                  {defaultModel ? (
                    <p className="text-xs text-muted-foreground">
                      已选：<code className="rounded bg-secondary px-1 py-0.5 font-mono">{defaultModel}</code>
                    </p>
                  ) : null}
                </div>
              </div>

              {/* Save feedback */}
              {saveMutation.error ? (
                <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                  保存失败：{String(saveMutation.error)}
                </div>
              ) : null}

              {staleDefaultModel ? (
                <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm text-amber-700 dark:text-amber-300">
                  默认模型已失效，需要重新选择。
                </div>
              ) : null}

              {saveSuccess ? (
                <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-400">
                  偏好已保存。
                </div>
              ) : null}

              <Button onClick={handleSave} disabled={saveMutation.isPending}>
                {saveMutation.isPending ? "保存中…" : "保存偏好"}
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  createAdminModel,
  deleteAdminModel,
  getUiModels,
  listAdminModels,
  patchAdminModel,
} from "@/lib/api";
import { formatProviderLabel } from "@/lib/provider-labels";
import type { CustomModelRecord, UiModelRecord } from "@/lib/types";

const emptyForm = {
  id: "",
  display_name: "",
  provider: "",
  model_profile: "",
  upstream_model: "",
  description: "",
  auth_modes: "",
  supported_clients: "",
};

export function ModelsPage() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ ...emptyForm });

  const systemModelsQuery = useQuery({
    queryKey: ["ui", "models"],
    queryFn: getUiModels,
  });

  const customModelsQuery = useQuery({
    queryKey: ["admin", "models"],
    queryFn: listAdminModels,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createAdminModel({
        id: form.id,
        display_name: form.display_name,
        provider: form.provider,
        model_profile: form.model_profile,
        upstream_model: form.upstream_model,
        description: form.description,
        auth_modes: splitComma(form.auth_modes),
        supported_clients: splitComma(form.supported_clients),
        enabled: true,
      }),
    onSuccess: async () => {
      setOpen(false);
      setForm({ ...emptyForm });
      await queryClient.invalidateQueries({ queryKey: ["admin", "models"] });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      patchAdminModel(id, { enabled }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "models"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteAdminModel,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "models"] });
    },
  });

  const systemModels = systemModelsQuery.data ?? [];
  const customModels = customModelsQuery.data ?? [];

  const groupedSystem = groupByProvider(systemModels);

  return (
    <div className="space-y-6">
      {/* System Models (read-only) */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Database className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-[30px] text-foreground">模型目录</CardTitle>
          </div>
          <CardDescription>
            系统模型为只读（硬编码），自定义模型可由管理员动态添加和管理。
          </CardDescription>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>系统模型</CardTitle>
          <CardDescription>内置于代码中的模型定义，不可修改。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {Object.entries(groupedSystem).map(([provider, models]) => (
              <div key={provider}>
                <div className="mb-2 text-sm font-medium text-muted-foreground">
                  {formatProviderLabel(provider)}
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-muted-foreground">
                        <th className="pb-2 pr-4 font-medium">ID</th>
                        <th className="pb-2 pr-4 font-medium">显示名</th>
                        <th className="pb-2 pr-4 font-medium">Model Profile</th>
                        <th className="pb-2 font-medium">Auth Modes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {models.map((m) => (
                        <tr key={m.id} className="border-b border-border/50">
                          <td className="py-2 pr-4 font-mono text-xs">{m.id}</td>
                          <td className="py-2 pr-4">{m.display_name}</td>
                          <td className="py-2 pr-4 font-mono text-xs text-muted-foreground">
                            {m.model_profile}
                          </td>
                          <td className="py-2">
                            <div className="flex flex-wrap gap-1">
                              {m.auth_modes.map((a) => (
                                <Badge key={a} variant="secondary" className="text-xs">
                                  {a}
                                </Badge>
                              ))}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Custom Models (CRUD) */}
      <Card>
        <CardHeader className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <CardTitle>自定义模型</CardTitle>
            <CardDescription>管理员自定义的模型条目，支持添加、启停和删除。</CardDescription>
          </div>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>添加模型</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>添加自定义模型</DialogTitle>
                <DialogDescription>
                  自定义模型会和系统模型合并展示，相同 ID 时自定义模型优先。
                </DialogDescription>
              </DialogHeader>
              <div className="grid gap-4 md:grid-cols-2">
                <FormField label="ID (provider/model)">
                  <Input
                    value={form.id}
                    onChange={(e) => setForm({ ...form, id: e.target.value })}
                    placeholder="openai/my-model"
                  />
                </FormField>
                <FormField label="显示名称">
                  <Input
                    value={form.display_name}
                    onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                  />
                </FormField>
                <FormField label="Provider">
                  <Input
                    value={form.provider}
                    onChange={(e) => setForm({ ...form, provider: e.target.value })}
                  />
                </FormField>
                <FormField label="Model Profile">
                  <Input
                    value={form.model_profile}
                    onChange={(e) => setForm({ ...form, model_profile: e.target.value })}
                    placeholder="openai/my-model"
                  />
                </FormField>
                <FormField label="Upstream Model">
                  <Input
                    value={form.upstream_model}
                    onChange={(e) => setForm({ ...form, upstream_model: e.target.value })}
                    placeholder="my-model"
                  />
                </FormField>
                <FormField label="Auth Modes (逗号分隔)">
                  <Input
                    value={form.auth_modes}
                    onChange={(e) => setForm({ ...form, auth_modes: e.target.value })}
                    placeholder="api_key, oauth_subscription"
                  />
                </FormField>
                <FormField label="Supported Clients (逗号分隔)">
                  <Input
                    value={form.supported_clients}
                    onChange={(e) => setForm({ ...form, supported_clients: e.target.value })}
                    placeholder="claude_code, codex"
                  />
                </FormField>
                <FormField className="md:col-span-2" label="描述">
                  <Textarea
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                  />
                </FormField>
              </div>
              <DialogFooter>
                <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
                  提交
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </CardHeader>
        <CardContent>
          {customModels.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无自定义模型。</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="pb-2 pr-4 font-medium">ID</th>
                    <th className="pb-2 pr-4 font-medium">显示名</th>
                    <th className="pb-2 pr-4 font-medium">Provider</th>
                    <th className="pb-2 pr-4 font-medium">Model Profile</th>
                    <th className="pb-2 pr-4 font-medium">状态</th>
                    <th className="pb-2 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {customModels.map((m) => (
                    <tr key={m.id} className="border-b border-border/50">
                      <td className="py-2 pr-4 font-mono text-xs">{m.id}</td>
                      <td className="py-2 pr-4">{m.display_name}</td>
                      <td className="py-2 pr-4">{formatProviderLabel(m.provider)}</td>
                      <td className="py-2 pr-4 font-mono text-xs text-muted-foreground">
                        {m.model_profile}
                      </td>
                      <td className="py-2 pr-4">
                        <Badge variant={m.enabled ? "secondary" : "outline"}>
                          {m.enabled ? "启用" : "禁用"}
                        </Badge>
                      </td>
                      <td className="py-2">
                        <div className="flex items-center gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              toggleMutation.mutate({ id: m.id, enabled: !m.enabled })
                            }
                          >
                            {m.enabled ? "禁用" : "启用"}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => deleteMutation.mutate(m.id)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function FormField({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label className="mb-2 block text-sm font-medium text-foreground">{label}</label>
      {children}
    </div>
  );
}

function splitComma(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function groupByProvider(models: UiModelRecord[]): Record<string, UiModelRecord[]> {
  const groups: Record<string, UiModelRecord[]> = {};
  for (const m of models) {
    const key = m.provider;
    if (!groups[key]) groups[key] = [];
    groups[key].push(m);
  }
  return groups;
}

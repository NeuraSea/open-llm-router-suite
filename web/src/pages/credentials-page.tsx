import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { RotateCcw, Save, Trash2 } from "lucide-react";

import { DataTable } from "@/components/data-table";
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
  createCredential,
  demoteCredential,
  deleteCredential,
  listCredentials,
  promoteCredential,
  refreshCredential,
  updateCredential,
} from "@/lib/api";
import { formatProviderLabel } from "@/lib/provider-labels";
import type { CredentialRecord } from "@/lib/types";

export function CredentialsPage() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    provider: "openai",
    auth_kind: "api_key",
    account_id: "",
    scopes: "",
    access_token: "",
    refresh_token: "",
    owner_principal_id: "",
    visibility: "enterprise_pool",
    source: "",
    max_concurrency: "1",
  });

  const credentialsQuery = useQuery({
    queryKey: ["admin", "credentials"],
    queryFn: listCredentials,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createCredential({
        provider: form.provider,
        auth_kind: form.auth_kind,
        account_id: form.account_id,
        scopes: splitScopes(form.scopes),
        access_token: form.access_token || undefined,
        refresh_token: form.refresh_token || undefined,
        owner_principal_id: form.owner_principal_id || undefined,
        visibility: form.visibility || undefined,
        source: form.source || undefined,
        max_concurrency: Number.parseInt(form.max_concurrency, 10) || 1,
      }),
    onSuccess: async () => {
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["admin", "credentials"] });
    },
  });

  const refreshMutation = useMutation({
    mutationFn: refreshCredential,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "credentials"] });
    },
  });

  const updateConcurrencyMutation = useMutation({
    mutationFn: ({ credentialId, maxConcurrency }: { credentialId: string; maxConcurrency: number }) =>
      updateCredential(credentialId, { max_concurrency: maxConcurrency }),
    onSuccess: async (updated) => {
      queryClient.setQueryData<CredentialRecord[]>(["admin", "credentials"], (current) =>
        current?.map((credential) => (credential.id === updated.id ? updated : credential))
      );
      await queryClient.invalidateQueries({ queryKey: ["admin", "credentials"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteCredential,
    onSuccess: async (_result, credentialId) => {
      queryClient.setQueryData<CredentialRecord[]>(["admin", "credentials"], (current) =>
        current?.filter((credential) => credential.id !== credentialId)
      );
      await queryClient.invalidateQueries({ queryKey: ["admin", "credentials"] });
    },
  });

  const visibilityMutation = useMutation({
    mutationFn: ({
      credentialId,
      visibility,
    }: {
      credentialId: string;
      visibility: "enterprise_pool" | "private";
    }) =>
      visibility === "enterprise_pool"
        ? promoteCredential(credentialId)
        : demoteCredential(credentialId),
    onSuccess: async (updated) => {
      queryClient.setQueryData<CredentialRecord[]>(["admin", "credentials"], (current) =>
        current?.map((credential) => (credential.id === updated.id ? updated : credential))
      );
      await queryClient.invalidateQueries({ queryKey: ["admin", "credentials"] });
    },
  });

  function confirmDelete(credential: CredentialRecord) {
    if (window.confirm(`确定要删除上游凭证 "${credential.account_id}" 吗？此操作不可撤销。`)) {
      deleteMutation.mutate(credential.id);
    }
  }

  const columns = useMemo<ColumnDef<CredentialRecord>[]>(
    () => [
      {
        header: "provider",
        accessorKey: "provider",
        cell: ({ getValue }) => formatProviderLabel(String(getValue())),
      },
      { header: "auth_kind", accessorKey: "auth_kind" },
      { header: "account_id", accessorKey: "account_id" },
      {
        header: "scopes",
        accessorFn: (row) => row.scopes.join(", "),
        cell: ({ row }) => (
          <div className="max-w-[260px] text-sm text-muted-foreground">{row.original.scopes.join(", ") || "-"}</div>
        ),
      },
      {
        header: "state",
        accessorKey: "state",
        cell: ({ getValue }) => <Badge variant="secondary">{String(getValue())}</Badge>,
      },
      { header: "owner_principal_id", accessorKey: "owner_principal_id" },
      {
        header: "visibility",
        accessorKey: "visibility",
        cell: ({ getValue }) => <Badge variant="outline">{String(getValue() || "-")}</Badge>,
      },
      { header: "source", accessorKey: "source" },
      { header: "expires_at", accessorKey: "expires_at" },
      { header: "cooldown_until", accessorKey: "cooldown_until" },
      {
        header: "max_concurrency",
        accessorKey: "max_concurrency",
        cell: ({ row }) => (
          <MaxConcurrencyCell
            credential={row.original}
            isPending={updateConcurrencyMutation.isPending}
            onSave={(credentialId, maxConcurrency) =>
              updateConcurrencyMutation.mutate({ credentialId, maxConcurrency })
            }
          />
        ),
      },
      { header: "concurrent_leases", accessorKey: "concurrent_leases" },
      {
        header: "actions",
        id: "actions",
        cell: ({ row }) => {
          const credential = row.original;
          return (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                type="button"
                onClick={() => refreshMutation.mutate(credential.id)}
                disabled={refreshMutation.isPending}
              >
                <RotateCcw className="h-4 w-4" />
                刷新
              </Button>
              <Button
                aria-label={
                  credential.visibility === "enterprise_pool"
                    ? `收回 ${credential.account_id} 到私有`
                    : `提升 ${credential.account_id} 到企业池`
                }
                variant="outline"
                size="sm"
                type="button"
                onClick={() =>
                  visibilityMutation.mutate({
                    credentialId: credential.id,
                    visibility:
                      credential.visibility === "enterprise_pool"
                        ? "private"
                        : "enterprise_pool",
                  })
                }
                disabled={visibilityMutation.isPending}
              >
                {credential.visibility === "enterprise_pool" ? "收回到私有" : "提升到企业池"}
              </Button>
              <Button
                aria-label={`删除 ${credential.account_id}`}
                variant="destructive"
                size="sm"
                type="button"
                onClick={() => confirmDelete(credential)}
                disabled={deleteMutation.isPending}
              >
                <Trash2 className="h-4 w-4" />
                删除
              </Button>
            </div>
          );
        },
      },
    ],
    [deleteMutation, refreshMutation, updateConcurrencyMutation, visibilityMutation]
  );

  return (
    <div className="space-y-6">
      <Card className="">
        <CardHeader className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <CardTitle className="text-[30px] text-foreground">凭证池</CardTitle>
            <CardDescription>查看当前可用上游凭证，并按账号粒度刷新或补录。</CardDescription>
          </div>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>新增凭证</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>新增 Provider 凭证</DialogTitle>
                <DialogDescription>
                  这是试点阶段的最小管理界面，表单直接映射现有后端接口字段。
                </DialogDescription>
              </DialogHeader>
              <div className="grid gap-4 md:grid-cols-2">
                <FormField label="provider">
                  <Input value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} />
                </FormField>
                <FormField label="auth_kind">
                  <Input value={form.auth_kind} onChange={(e) => setForm({ ...form, auth_kind: e.target.value })} />
                </FormField>
                <FormField label="account_id">
                  <Input value={form.account_id} onChange={(e) => setForm({ ...form, account_id: e.target.value })} />
                </FormField>
                <FormField label="owner_principal_id">
                  <Input
                    value={form.owner_principal_id}
                    onChange={(e) => setForm({ ...form, owner_principal_id: e.target.value })}
                  />
                </FormField>
                <FormField label="visibility">
                  <Input
                    value={form.visibility}
                    onChange={(e) => setForm({ ...form, visibility: e.target.value })}
                  />
                </FormField>
                <FormField label="source">
                  <Input value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} />
                </FormField>
                <FormField label="max_concurrency">
                  <Input
                    value={form.max_concurrency}
                    onChange={(e) => setForm({ ...form, max_concurrency: e.target.value })}
                  />
                </FormField>
                <FormField className="md:col-span-2" label="scopes">
                  <Textarea
                    value={form.scopes}
                    onChange={(e) => setForm({ ...form, scopes: e.target.value })}
                    placeholder="scope_a, scope_b"
                  />
                </FormField>
                <FormField className="md:col-span-2" label="access_token">
                  <Textarea
                    value={form.access_token}
                    onChange={(e) => setForm({ ...form, access_token: e.target.value })}
                  />
                </FormField>
                <FormField className="md:col-span-2" label="refresh_token">
                  <Textarea
                    value={form.refresh_token}
                    onChange={(e) => setForm({ ...form, refresh_token: e.target.value })}
                  />
                </FormField>
              </div>
              <DialogFooter>
                <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
                  提交凭证
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={columns}
            data={credentialsQuery.data ?? []}
            emptyMessage="当前还没有凭证记录。"
          />
        </CardContent>
      </Card>
    </div>
  );
}

function MaxConcurrencyCell({
  credential,
  isPending,
  onSave,
}: {
  credential: CredentialRecord;
  isPending: boolean;
  onSave: (credentialId: string, maxConcurrency: number) => void;
}) {
  const [draft, setDraft] = useState(String(credential.max_concurrency));

  useEffect(() => {
    setDraft(String(credential.max_concurrency));
  }, [credential.id, credential.max_concurrency]);

  const parsed = Number.parseInt(draft, 10);
  const canSave = Number.isInteger(parsed) && parsed >= 1 && parsed !== credential.max_concurrency;

  return (
    <div className="flex items-center gap-2">
      <Input
        aria-label={`${credential.account_id} 并发上限`}
        className="h-8 w-20"
        min={1}
        type="number"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      <Button
        aria-label={`保存 ${credential.account_id} 并发上限`}
        disabled={!canSave || isPending}
        size="icon"
        type="button"
        variant="ghost"
        onClick={() => onSave(credential.id, parsed)}
      >
        <Save className="h-4 w-4" />
      </Button>
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

function splitScopes(scopes: string) {
  return scopes
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

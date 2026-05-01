import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";

import { DataTable } from "@/components/data-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { listQuotas, upsertQuota } from "@/lib/api";
import type { QuotaRule } from "@/lib/types";

export function QuotasPage() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<QuotaRule>({
    scope_type: "user",
    scope_id: "",
    limit: 100000,
  });

  const quotasQuery = useQuery({
    queryKey: ["admin", "quotas"],
    queryFn: listQuotas,
  });

  const saveMutation = useMutation({
    mutationFn: () => upsertQuota(form),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "quotas"] });
    },
  });

  const columns = useMemo<ColumnDef<QuotaRule>[]>(
    () => [
      { header: "scope_type", accessorKey: "scope_type" },
      { header: "scope_id", accessorKey: "scope_id" },
      { header: "limit", accessorKey: "limit" },
    ],
    []
  );

  return (
    <div className="grid gap-6 xl:grid-cols-[0.44fr_0.56fr]">
      <Card className="">
        <CardHeader>
          <CardTitle className="text-[30px] text-foreground">配额策略</CardTitle>
          <CardDescription>个人与团队配额统一走一个写入口，优先服务当前试点。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Field label="scope_type">
            <Input
              value={form.scope_type}
              onChange={(event) => setForm({ ...form, scope_type: event.target.value })}
            />
          </Field>
          <Field label="scope_id">
            <Input
              value={form.scope_id}
              onChange={(event) => setForm({ ...form, scope_id: event.target.value })}
            />
          </Field>
          <Field label="limit">
            <Input
              value={String(form.limit)}
              onChange={(event) =>
                setForm({ ...form, limit: Number.parseInt(event.target.value, 10) || 0 })
              }
            />
          </Field>
          <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
            保存配额
          </Button>
        </CardContent>
      </Card>

      <Card className="">
        <CardHeader>
          <CardTitle className="text-xl text-foreground">当前配额规则</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={columns}
            data={quotasQuery.data ?? []}
            emptyMessage="当前还没有配置任何配额。"
          />
        </CardContent>
      </Card>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-medium text-foreground">{label}</label>
      {children}
    </div>
  );
}

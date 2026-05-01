import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";

import { DataTable } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { listCliActivations, listCliSessions, revokeToken } from "@/lib/api";
import type { IssuedTokenRecord } from "@/lib/types";

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("zh-CN");
}

function StatusBadge({ isRevoked }: { isRevoked: boolean }) {
  return isRevoked ? (
    <Badge className="border-red-200 bg-red-100 text-red-800">已撤销</Badge>
  ) : (
    <Badge className="border-green-200 bg-green-100 text-green-800">活跃</Badge>
  );
}

function RevokeButton({ jti, queryKey }: { jti: string; queryKey: string[] }) {
  const queryClient = useQueryClient();
  const revokeMutation = useMutation({
    mutationFn: () => revokeToken(jti),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey });
    },
  });

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => revokeMutation.mutate()}
      disabled={revokeMutation.isPending}
    >
      强制下线
    </Button>
  );
}

export function SessionsPage() {
  const sessionsQuery = useQuery({
    queryKey: ["admin", "cli", "sessions"],
    queryFn: listCliSessions,
  });

  const activationsQuery = useQuery({
    queryKey: ["admin", "cli", "activations"],
    queryFn: listCliActivations,
  });

  const sessionColumns = useMemo<ColumnDef<IssuedTokenRecord>[]>(
    () => [
      { header: "用户邮箱", accessorKey: "email" },
      {
        header: "颁发时间",
        accessorKey: "issued_at",
        cell: ({ getValue }) => formatDate(String(getValue())),
      },
      {
        header: "过期时间",
        accessorKey: "expires_at",
        cell: ({ getValue }) => formatDate(String(getValue())),
      },
      {
        header: "状态",
        accessorKey: "is_revoked",
        cell: ({ getValue }) => <StatusBadge isRevoked={Boolean(getValue())} />,
      },
      {
        header: "操作",
        id: "actions",
        cell: ({ row }) => (
          <RevokeButton jti={row.original.jti} queryKey={["admin", "cli", "sessions"]} />
        ),
      },
    ],
    []
  );

  const activationColumns = useMemo<ColumnDef<IssuedTokenRecord>[]>(
    () => [
      { header: "用户邮箱", accessorKey: "email" },
      { header: "客户端", accessorKey: "client", cell: ({ getValue }) => String(getValue() ?? "-") },
      { header: "模型", accessorKey: "model", cell: ({ getValue }) => String(getValue() ?? "-") },
      {
        header: "颁发时间",
        accessorKey: "issued_at",
        cell: ({ getValue }) => formatDate(String(getValue())),
      },
      {
        header: "过期时间",
        accessorKey: "expires_at",
        cell: ({ getValue }) => formatDate(String(getValue())),
      },
      {
        header: "状态",
        accessorKey: "is_revoked",
        cell: ({ getValue }) => <StatusBadge isRevoked={Boolean(getValue())} />,
      },
      {
        header: "操作",
        id: "actions",
        cell: ({ row }) => (
          <RevokeButton jti={row.original.jti} queryKey={["admin", "cli", "activations"]} />
        ),
      },
    ],
    []
  );

  return (
    <div className="space-y-6">
      <Card className="">
        <CardHeader>
          <CardTitle className="text-[30px] text-foreground">会话管理</CardTitle>
          <CardDescription>查看当前活跃的 CLI Session 和模型激活，并可强制下线任意 token。</CardDescription>
        </CardHeader>
      </Card>

      <Card className="">
        <CardHeader>
          <CardTitle className="text-xl text-foreground">活跃 CLI Session</CardTitle>
          <CardDescription>通过 routerctl bootstrap 颁发的 cli_session 类型 token。</CardDescription>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={sessionColumns}
            data={sessionsQuery.data ?? []}
            emptyMessage="当前没有活跃的 CLI Session。"
          />
        </CardContent>
      </Card>

      <Card className="">
        <CardHeader>
          <CardTitle className="text-xl text-foreground">活跃模型激活</CardTitle>
          <CardDescription>通过 CLI activate 颁发的 client_access 类型 token，绑定了具体客户端和模型。</CardDescription>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={activationColumns}
            data={activationsQuery.data ?? []}
            emptyMessage="当前没有活跃的模型激活。"
          />
        </CardContent>
      </Card>
    </div>
  );
}

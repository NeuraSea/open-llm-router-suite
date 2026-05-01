import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";

import { DataTable } from "@/components/data-table";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { listUsage, listUsageSummary } from "@/lib/api";
import type { UsageEventRecord, UsageSummaryRecord } from "@/lib/types";

export function UsagePage() {
  const [search, setSearch] = useState("");
  const [period, setPeriod] = useState("30d");

  const usageQuery = useQuery({
    queryKey: ["admin", "usage"],
    queryFn: listUsage,
  });

  const summaryQuery = useQuery({
    queryKey: ["admin", "usage", "summary", period],
    queryFn: () => listUsageSummary(period),
  });

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) {
      return usageQuery.data ?? [];
    }
    return (usageQuery.data ?? []).filter((item) =>
      [
        item.request_id,
        item.principal_id,
        item.model_profile,
        item.provider,
        item.credential_id,
        item.status,
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle)
    );
  }, [search, usageQuery.data]);

  const sortedSummary = useMemo(() => {
    const data = summaryQuery.data ?? [];
    return [...data].sort((a, b) => b.tokens_in + b.tokens_out - (a.tokens_in + a.tokens_out));
  }, [summaryQuery.data]);

  const eventColumns = useMemo<ColumnDef<UsageEventRecord>[]>(
    () => [
      { header: "request_id", accessorKey: "request_id" },
      { header: "principal_id", accessorKey: "principal_id" },
      { header: "model_profile", accessorKey: "model_profile" },
      { header: "provider", accessorKey: "provider" },
      { header: "credential_id", accessorKey: "credential_id" },
      { header: "tokens_in", accessorKey: "tokens_in" },
      { header: "tokens_out", accessorKey: "tokens_out" },
      { header: "latency_ms", accessorKey: "latency_ms" },
      { header: "status", accessorKey: "status" },
      {
        header: "created_at",
        accessorKey: "created_at",
        cell: ({ getValue }) => new Date(Number(getValue()) * 1000).toLocaleString("zh-CN"),
      },
    ],
    []
  );

  const summaryColumns = useMemo<ColumnDef<UsageSummaryRecord>[]>(
    () => [
      {
        header: "用户",
        id: "user",
        accessorFn: (row) => row.principal_email ?? row.principal_id,
        cell: ({ getValue }) => (
          <span className="font-mono text-sm">{String(getValue())}</span>
        ),
      },
      { header: "模型档位", accessorKey: "model_profile" },
      {
        header: "输入 Token",
        accessorKey: "tokens_in",
        cell: ({ getValue }) => Number(getValue()).toLocaleString(),
      },
      {
        header: "输出 Token",
        accessorKey: "tokens_out",
        cell: ({ getValue }) => Number(getValue()).toLocaleString(),
      },
      {
        header: "请求次数",
        accessorKey: "request_count",
        cell: ({ getValue }) => Number(getValue()).toLocaleString(),
      },
    ],
    []
  );

  return (
    <div className="space-y-6">
      <Card className="">
        <CardHeader>
          <CardTitle className="text-[30px] text-foreground">用量审计</CardTitle>
          <CardDescription>模型调用用量统计与原始事件记录。</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="summary">
            <TabsList>
              <TabsTrigger value="summary">用量概览</TabsTrigger>
              <TabsTrigger value="events">原始事件</TabsTrigger>
            </TabsList>

            <TabsContent value="summary">
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <label className="text-sm font-medium text-muted-foreground">统计周期</label>
                  <Select
                    value={period}
                    onChange={(e) => setPeriod(e.target.value)}
                    className="w-40"
                  >
                    <option value="7d">最近 7 天</option>
                    <option value="30d">最近 30 天</option>
                    <option value="all">全部时间</option>
                  </Select>
                </div>
                <DataTable
                  columns={summaryColumns}
                  data={sortedSummary}
                  emptyMessage="当前统计周期内没有用量数据。"
                />
              </div>
            </TabsContent>

            <TabsContent value="events">
              <div className="space-y-4">
                <div className="w-full md:max-w-sm">
                  <Input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="搜索 request_id / principal_id / model"
                  />
                </div>
                <DataTable columns={eventColumns} data={filtered} emptyMessage="当前还没有用量事件。" />
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}

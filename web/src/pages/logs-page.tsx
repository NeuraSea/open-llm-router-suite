import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, ChevronLeft, ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getMyLogs } from "@/lib/api";
import type { UsageLogEntry } from "@/lib/types";

const PAGE_SIZE = 50;

function formatTime(unixTs: number): string {
  return new Date(unixTs * 1000).toLocaleString("zh-CN", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function statusBadge(status: string) {
  if (status === "success") {
    return (
      <Badge className="bg-emerald-100 text-emerald-800 border-emerald-200 hover:bg-emerald-100">
        {status}
      </Badge>
    );
  }
  if (status.startsWith("4")) {
    return (
      <Badge className="bg-amber-100 text-amber-800 border-amber-200 hover:bg-amber-100">
        {status}
      </Badge>
    );
  }
  if (status.startsWith("5") || status === "error") {
    return (
      <Badge className="bg-red-100 text-red-800 border-red-200 hover:bg-red-100">
        {status}
      </Badge>
    );
  }
  return <Badge variant="secondary">{status}</Badge>;
}

export function LogsPage() {
  const [page, setPage] = useState(1);

  const logsQuery = useQuery({
    queryKey: ["me", "logs", page],
    queryFn: () => getMyLogs(page, PAGE_SIZE),
  });

  const logs = logsQuery.data?.data ?? [];
  const hasNextPage = logs.length === PAGE_SIZE;
  const hasPrevPage = page > 1;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="space-y-1">
        <div className="flex items-center gap-3">
          <div className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <FileText className="h-4 w-4" />
          </div>
          <h2 className="text-2xl font-bold tracking-tight text-slate-950 dark:text-slate-50">Logs</h2>
        </div>
        <p className="text-sm leading-6 text-muted-foreground">
          查看每一次推理请求的详细记录。
        </p>
      </div>

      <Card className="border-slate-900/10 bg-white/80 dark:bg-background">
        <CardHeader className="pb-4">
          <CardTitle className="text-lg text-slate-950 dark:text-slate-50">请求记录</CardTitle>
          <CardDescription>
            {logsQuery.isLoading
              ? "正在加载…"
              : logs.length > 0
              ? `第 ${page} 页，每页 ${PAGE_SIZE} 条`
              : "暂无请求记录"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {logsQuery.isLoading ? (
            <div className="py-8 text-center text-sm text-muted-foreground">正在加载…</div>
          ) : logsQuery.error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
              加载失败：{String(logsQuery.error)}
            </div>
          ) : logs.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-secondary/40 px-6 py-8 text-center">
              <p className="text-sm text-muted-foreground">暂无请求记录</p>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="pb-3 pr-4 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        时间
                      </th>
                      <th className="pb-3 pr-4 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        模型
                      </th>
                      <th className="pb-3 pr-4 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Provider
                      </th>
                      <th className="pb-3 pr-4 text-right text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Tokens In→Out
                      </th>
                      <th className="pb-3 pr-4 text-right text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        延迟
                      </th>
                      <th className="pb-3 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        状态
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {logs.map((log) => (
                      <LogRow key={log.request_id} log={log} />
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="mt-4 flex items-center justify-between">
                <span className="text-xs text-muted-foreground">第 {page} 页</span>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={!hasPrevPage || logsQuery.isLoading}
                  >
                    <ChevronLeft className="h-4 w-4" />
                    上一页
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => p + 1)}
                    disabled={!hasNextPage || logsQuery.isLoading}
                  >
                    下一页
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function LogRow({ log }: { log: UsageLogEntry }) {
  return (
    <tr className="hover:bg-secondary/40 transition-colors">
      <td className="py-3 pr-4 font-mono text-xs text-muted-foreground whitespace-nowrap">
        {formatTime(log.created_at)}
      </td>
      <td className="py-3 pr-4 max-w-[200px]">
        <span className="truncate text-xs text-foreground">{log.model_profile}</span>
      </td>
      <td className="py-3 pr-4">
        <Badge variant="secondary" className="text-xs">
          {log.provider}
        </Badge>
      </td>
      <td className="py-3 pr-4 text-right font-mono text-xs text-foreground whitespace-nowrap">
        {log.tokens_in.toLocaleString()}→{log.tokens_out.toLocaleString()}
      </td>
      <td className="py-3 pr-4 text-right font-mono text-xs text-muted-foreground whitespace-nowrap">
        {formatLatency(log.latency_ms)}
      </td>
      <td className="py-3">{statusBadge(log.status)}</td>
    </tr>
  );
}

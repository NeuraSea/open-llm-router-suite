import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { Activity } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getMyActivity, getMyActivityByModel } from "@/lib/api";
import type { ModelActivityRecord } from "@/lib/types";

type Period = "7d" | "30d" | "90d";

const PERIOD_LABELS: Record<Period, string> = {
  "7d": "7 天",
  "30d": "30 天",
  "90d": "90 天",
};

export function ActivityPage() {
  const [period, setPeriod] = useState<Period>("7d");

  const activityQuery = useQuery({
    queryKey: ["me", "activity", period],
    queryFn: () => getMyActivity(period),
  });

  const byModelQuery = useQuery({
    queryKey: ["me", "activity", "by-model", period],
    queryFn: () => getMyActivityByModel(period),
  });

  const data = activityQuery.data?.data ?? [];
  const hasData = data.length > 0 && data.some((d) => d.tokens_in > 0 || d.tokens_out > 0);

  const totalTokensIn = data.reduce((sum, d) => sum + d.tokens_in, 0);
  const totalTokensOut = data.reduce((sum, d) => sum + d.tokens_out, 0);
  const totalRequests = data.reduce((sum, d) => sum + d.request_count, 0);

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="space-y-1">
        <div className="flex items-center gap-3">
          <div className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Activity className="h-4 w-4" />
          </div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">Activity</h2>
        </div>
        <p className="text-sm leading-6 text-muted-foreground">
          查看你的 API 用量、Token 消耗和请求趋势。
        </p>
      </div>

      {/* Period selector */}
      <div className="flex gap-1 rounded-lg border border-border bg-secondary/40 p-1 w-fit">
        {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={[
              "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              period === p
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            ].join(" ")}
          >
            {PERIOD_LABELS[p]}
          </button>
        ))}
      </div>

      {/* Stats summary */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard label="Input Tokens" value={hasData ? totalTokensIn.toLocaleString() : "—"} />
        <StatCard label="Output Tokens" value={hasData ? totalTokensOut.toLocaleString() : "—"} />
        <StatCard label="请求次数" value={hasData ? totalRequests.toLocaleString() : "—"} />
      </div>

      {/* Token chart */}
      <Card className="border-slate-900/10 bg-white/80 dark:bg-background">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg text-foreground">Token 消耗趋势</CardTitle>
          <CardDescription>蓝色为 Input Tokens，紫色为 Output Tokens（堆叠）</CardDescription>
        </CardHeader>
        <CardContent>
          {activityQuery.isLoading ? (
            <div className="flex h-[300px] items-center justify-center text-sm text-muted-foreground">
              正在加载…
            </div>
          ) : activityQuery.error ? (
            <div className="flex h-[300px] items-center justify-center rounded-lg border border-red-200 bg-red-50 text-sm text-red-900">
              加载失败：{String(activityQuery.error)}
            </div>
          ) : !hasData ? (
            <EmptyState />
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={50} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 6, border: "1px solid #E5E5E5" }}
                  formatter={(value, name) => [Number(value ?? 0).toLocaleString(), String(name)]}
                />
                <Legend iconSize={10} wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="tokens_in" name="Input tokens" stackId="a" fill="#6366f1" radius={[0, 0, 0, 0]} />
                <Bar dataKey="tokens_out" name="Output tokens" stackId="a" fill="#a78bfa" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      {/* Request count chart */}
      {hasData && (
        <Card className="border-slate-900/10 bg-white/80 dark:bg-background">
          <CardHeader className="pb-2">
            <CardTitle className="text-lg text-foreground">请求次数趋势</CardTitle>
            <CardDescription>每日推理请求数量</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 6, border: "1px solid #E5E5E5" }}
                  formatter={(value) => [Number(value ?? 0).toLocaleString(), "请求数"]}
                />
                <Bar dataKey="request_count" name="请求数" fill="#0969DA" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Model usage breakdown */}
      <Card className="border-slate-900/10 bg-white/80 dark:bg-background">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg text-foreground">模型用量排行</CardTitle>
          <CardDescription>选定时段内各模型的 Token 消耗占比</CardDescription>
        </CardHeader>
        <CardContent>
          {byModelQuery.isLoading ? (
            <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
              正在加载…
            </div>
          ) : byModelQuery.error ? (
            <div className="flex h-32 items-center justify-center rounded-lg border border-red-200 bg-red-50 text-sm text-red-900">
              加载失败：{String(byModelQuery.error)}
            </div>
          ) : !byModelQuery.data?.data?.length ? (
            <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
              此时段暂无用量记录
            </div>
          ) : (
            <ModelBreakdownTable rows={byModelQuery.data.data} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="py-5 px-5">
        <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
          {label}
        </div>
        <div className="text-2xl font-semibold text-foreground font-mono tabular-nums">{value}</div>
      </CardContent>
    </Card>
  );
}

function EmptyState() {
  return (
    <div className="flex h-[300px] flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-secondary/40">
      <div className="text-sm font-medium text-foreground">暂无用量数据</div>
      <p className="max-w-sm text-center text-sm leading-6 text-muted-foreground">
        开始使用 <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">cc-switch claude</code> 或配置{" "}
        <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">ANTHROPIC_BASE_URL</code>{" "}
        后，数据将在此显示。
      </p>
    </div>
  );
}

function ModelBreakdownTable({ rows }: { rows: ModelActivityRecord[] }) {
  const grandTotal = rows.reduce((s, r) => s + r.tokens_in + r.tokens_out, 0);

  return (
    <div className="space-y-2">
      {/* Header */}
      <div className="grid grid-cols-[1fr_120px_80px_80px] gap-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground px-1">
        <span>Model</span>
        <span className="text-right">Tokens</span>
        <span className="text-right">占比</span>
        <span className="text-right">请求数</span>
      </div>
      {/* Rows */}
      {rows.map((row) => {
        const total = row.tokens_in + row.tokens_out;
        const pct = grandTotal > 0 ? (total / grandTotal) * 100 : 0;
        return (
          <div
            key={row.model_profile}
            className="grid grid-cols-[1fr_120px_80px_80px] gap-2 items-center rounded-md border border-border px-3 py-2"
          >
            <code className="text-xs font-mono text-foreground truncate">{row.model_profile}</code>
            <span className="text-right text-sm font-mono tabular-nums text-foreground">
              {total.toLocaleString()}
            </span>
            <div className="flex items-center justify-end gap-1.5">
              <div className="h-1.5 w-16 rounded-full bg-secondary overflow-hidden">
                <div
                  className="h-full rounded-full bg-[#0969DA]"
                  style={{ width: `${Math.max(pct, 1)}%` }}
                />
              </div>
              <span className="text-xs font-mono tabular-nums text-muted-foreground w-10 text-right">
                {pct.toFixed(1)}%
              </span>
            </div>
            <span className="text-right text-sm font-mono tabular-nums text-muted-foreground">
              {row.request_count.toLocaleString()}
            </span>
          </div>
        );
      })}
    </div>
  );
}

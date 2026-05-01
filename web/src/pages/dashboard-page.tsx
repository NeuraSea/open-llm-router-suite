import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { CodePanel } from "@/components/code-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useUiShell } from "@/context/ui-shell-context";
import { getMyStats } from "@/lib/api";

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatRequests(n: number): string {
  return n.toLocaleString();
}

export function DashboardPage() {
  const { config } = useUiShell();
  const statsQuery = useQuery({ queryKey: ["me", "stats"], queryFn: getMyStats });

  const claudeCodeSnippet = [
    `export ANTHROPIC_BASE_URL="${config.router_public_base_url}"`,
    `export ANTHROPIC_AUTH_TOKEN="<your_api_key>"`,
    `unset ANTHROPIC_API_KEY`,
  ].join("\n");

  return (
    <div className="space-y-6">
      {/* Quick Setup */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <Badge variant="secondary" className="text-xs font-medium mb-2">
                One API for any model
              </Badge>
              <CardTitle className="text-xl">快速接入</CardTitle>
              <CardDescription className="text-sm leading-6">
                用你的平台 API Key 直接配置 Claude Code 或 Codex，无需安装任何 CLI。
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <CodePanel
            title="Claude Code 配置"
            value={claudeCodeSnippet}
            hint="将以下环境变量添加到你的 shell profile 或 .env 文件中"
          />
          <div className="flex items-center gap-2">
            <Button asChild variant="outline" size="sm">
              <Link to="/portal/keys">管理 API Keys →</Link>
            </Button>
            <p className="text-xs text-muted-foreground">
              在 API Keys 页面创建并复制你的 Key，替换上方的{" "}
              <code className="font-mono text-[11px] bg-secondary px-1 py-0.5 rounded">&lt;your_api_key&gt;</code>
            </p>
          </div>
        </CardContent>
      </Card>

      {/* routerctl Setup — secondary, muted */}
      <Card className="border-dashed bg-secondary/30">
        <CardContent className="py-4 px-5">
          <p className="text-sm text-muted-foreground leading-6">
            需要 Claude Code OAuth 或 Codex 加速？安装 routerctl 完成高级配置。{" "}
            <Link
              to="/portal/setup"
              className="text-foreground underline underline-offset-4 hover:text-primary transition-colors"
            >
              前往安装向导 →
            </Link>
          </p>
        </CardContent>
      </Card>

      {/* Stats Overview */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard
          label="本月请求数"
          value={statsQuery.data ? formatRequests(statsQuery.data.requests_this_month) : "—"}
          error={!!statsQuery.error}
        />
        <StatCard
          label="Token 消耗"
          value={statsQuery.data ? formatTokens(statsQuery.data.tokens_this_month) : "—"}
          error={!!statsQuery.error}
        />
        <StatCard
          label="活跃 API Keys"
          value={statsQuery.data ? String(statsQuery.data.active_api_keys) : "—"}
          error={!!statsQuery.error}
        />
      </div>
    </div>
  );
}

function StatCard({ label, value, error }: { label: string; value: string; error?: boolean }) {
  return (
    <Card>
      <CardContent className="py-5 px-5">
        <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
          {label}
        </div>
        <div className={`text-2xl font-semibold font-mono tabular-nums ${error ? "text-red-600" : "text-foreground"}`}>{value}</div>
      </CardContent>
    </Card>
  );
}

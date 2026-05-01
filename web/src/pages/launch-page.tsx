import { useEffect } from "react";
import type { ComponentType } from "react";
import { ArrowUpRight, BadgeCheck, KeyRound, Shield } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { getUiConfig } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function LaunchPage() {
  const configQuery = useQuery({
    queryKey: ["ui-config"],
    queryFn: getUiConfig,
    retry: false,
  });

  const authorizeUrl = configQuery.data?.feishu_authorize_url ?? null;

  useEffect(() => {
    if (!authorizeUrl || import.meta.env.MODE === "test") {
      return;
    }
    const timer = window.setTimeout(() => {
      window.location.replace(authorizeUrl);
    }, 700);
    return () => window.clearTimeout(timer);
  }, [authorizeUrl]);

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(21,94,117,0.18),_transparent_24%),linear-gradient(180deg,_#f8f7f2,_#f3efe7)] px-4 py-8 text-foreground">
      <div className="mx-auto grid w-full max-w-6xl gap-6 lg:grid-cols-[1.15fr_0.85fr]">
        <Card className="overflow-hidden ">
          <CardContent className="space-y-8 p-8 md:p-10">
            <div className="space-y-5">
              <Badge>Feishu SSO</Badge>
              <div className="space-y-4">
                <h1 className="max-w-2xl text-4xl font-bold tracking-tight text-foreground md:text-6xl">
                  一次飞书登录，接通整个企业 Router。
                </h1>
                <p className="max-w-2xl text-base leading-8 text-muted-foreground md:text-lg">
                  登录成功后，你会进入统一开发者控制台，生成平台 API Key，并为 Claude
                  Code 或 Codex 领取专用接入脚本。
                </p>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <FeatureCard
                icon={BadgeCheck}
                title="统一身份"
                description="飞书会话完成后，直接带着平台身份进入控制台。"
              />
              <FeatureCard
                icon={KeyRound}
                title="专用 Key"
                description="开发者拿平台密钥，不暴露上游 OpenAI 或 Anthropic 凭证。"
              />
              <FeatureCard
                icon={Shield}
                title="统一治理"
                description="模型、配额、凭证健康和用量审计都回到同一个控制面。"
              />
            </div>

            <div className="flex flex-col gap-4 rounded-lg border border-border bg-secondary/70 p-6 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-1">
                <div className="text-sm font-semibold text-foreground">
                  {authorizeUrl ? "正在跳转到飞书授权页" : "缺少飞书登录配置"}
                </div>
                <div className="text-sm text-muted-foreground">
                  {authorizeUrl
                    ? "如果没有自动跳转，请手动点击右侧按钮继续。"
                    : "请先检查后端的 App ID 和回调地址配置。"}
                </div>
              </div>
              <Button asChild size="lg" disabled={!authorizeUrl}>
                <a href={authorizeUrl ?? "#"} aria-disabled={!authorizeUrl}>
                  继续使用飞书登录
                  <ArrowUpRight className="h-4 w-4" />
                </a>
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-foreground text-background">
          <CardHeader>
            <CardTitle className="text-background">登录后你会得到什么</CardTitle>
            <CardDescription className="text-background/60">
              默认流程不展示多余技术细节，但会把真正需要复制的内容保留下来。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm leading-7 text-background/60">
            <ChecklistItem title="1. 查看当前会话" description="确认你的飞书身份、角色、团队和 Router API Base。" />
            <ChecklistItem title="2. 生成平台 API Key" description="用于终端工具、脚本或后续自定义集成。" />
            <ChecklistItem title="3. 选择客户端" description="Claude Code 与 Codex 共享同一控制台，但分别生成独立脚本。" />
            <ChecklistItem title="4. 完成验证" description="每个脚本都会附带验证提示，确保本地接入没有跑偏。" />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function FeatureCard({
  icon: Icon,
  title,
  description,
}: {
  icon: ComponentType<{ className?: string }>;
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-background p-5">
      <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Icon className="h-5 w-5" />
      </div>
      <div className="mt-4 text-lg font-semibold text-foreground">{title}</div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{description}</p>
    </div>
  );
}

function ChecklistItem({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-lg border border-background/15 bg-background/10 p-4">
      <div className="font-semibold text-background">{title}</div>
      <div className="mt-1 text-background/60">{description}</div>
    </div>
  );
}

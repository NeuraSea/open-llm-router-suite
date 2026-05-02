import { BookOpen } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { ApiSidebar } from "@/components/api-reference/api-sidebar";
import { EndpointSection } from "@/components/api-reference/endpoint-section";
import { useUiShell } from "@/context/ui-shell-context";
import { CATEGORIES, ENDPOINTS } from "@/lib/api-reference-data";

const PROVIDER_TABLE = [
  { access: "OAuth 订阅", provider: "Claude Max", prefix: "claude-max/", example: "claude-max/claude-sonnet-4-6" },
  { access: "OAuth 订阅", provider: "Codex / ChatGPT", prefix: "openai-codex/", example: "openai-codex/gpt-5-codex" },
  { access: "API Key", provider: "OpenAI", prefix: "openai/", example: "openai/gpt-4.1, openai/gpt-4o" },
  { access: "API Key", provider: "Anthropic", prefix: "anthropic/", example: "anthropic/claude-3-5-sonnet-20241022" },
  { access: "API Key", provider: "DeepSeek", prefix: "deepseek/", example: "deepseek/deepseek-chat" },
  { access: "API Key", provider: "ZhipuAI (智谱 Z-AI)", prefix: "zai/", example: "zai/glm-4.5" },
  { access: "API Key", provider: "Qwen (通义千问)", prefix: "dashscope/", example: "dashscope/qwen-plus" },
  { access: "API Key", provider: "MiniMax", prefix: "minimax/", example: "minimax/minimax-01" },
  { access: "API Key", provider: "Jina AI", prefix: "jina/", example: "jina/jina-reranker-v3" },
  { access: "兼容端点", provider: "LM Studio", prefix: "lmstudio/", example: "lmstudio/zai-org/glm-4.7-flash" },
  { access: "兼容端点", provider: "Anthropic 兼容端点", prefix: "provider_alias/", example: "my-claude/claude-sonnet-4-6" },
  { access: "兼容端点", provider: "OpenAI 兼容端点", prefix: "provider_alias/", example: "zai-org/glm-4.7-flash" },
];

export function DocsPage() {
  const { config } = useUiShell();
  const base = config.router_public_base_url.replace(/\/$/, "");
  const controlPlaneBase = config.router_control_plane_base_url.replace(/\/$/, "");

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div className="space-y-1">
        <div className="flex items-center gap-3">
          <div className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <BookOpen className="h-4 w-4" />
          </div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">API 文档</h2>
        </div>
        <p className="text-sm leading-6 text-muted-foreground">
          routerctl 绑定、New API 调用、模型命名规则与完整 API Reference。
        </p>
      </div>

      <section className="space-y-4" id="routerctl-newapi-quickstart">
        <div className="space-y-1">
          <h3 className="text-lg font-semibold text-foreground">routerctl + New API Quickstart</h3>
          <p className="text-sm leading-6 text-muted-foreground">
            routerctl 只负责登录和导入本机 OAuth 凭证。绑定完成后，Router bridge 会同步为 New API channel；
            业务调用继续使用 New API token 请求 /v1。
          </p>
        </div>

        <div className="grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
          <Card className="border-border">
            <CardContent className="space-y-3 p-4">
              <div className="text-sm font-semibold text-foreground">最小命令</div>
              <ol className="space-y-2 text-sm text-muted-foreground">
                <li>
                  <code className="block rounded-md bg-secondary px-3 py-2 font-mono text-xs text-foreground">
                    {`routerctl auth login --router-base-url ${controlPlaneBase}`}
                  </code>
                </li>
                <li>
                  <code className="block rounded-md bg-secondary px-3 py-2 font-mono text-xs text-foreground">
                    routerctl codex bind
                  </code>
                </li>
                <li>
                  <code className="block rounded-md bg-secondary px-3 py-2 font-mono text-xs text-foreground">
                    routerctl claude bind
                  </code>
                </li>
              </ol>
            </CardContent>
          </Card>

          <Card className="border-border">
            <CardContent className="space-y-3 p-4">
              <div className="text-sm font-semibold text-foreground">New API 调用方向</div>
              <div className="space-y-2 text-sm leading-6 text-muted-foreground">
                <p>
                  使用 New API token，请求{" "}
                  <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">{base}</code>
                  。模型走 New API 中已同步的 Codex/Claude channel。
                </p>
                <p>
                  Codex OAuth 模型使用{" "}
                  <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">openai-codex/</code>{" "}
                  前缀；Claude Max OAuth 模型使用{" "}
                  <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">claude-max/</code>{" "}
                  前缀。
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* Model naming + prefix table */}
      <section className="space-y-3" id="cat-naming">
        <h3 className="text-lg font-semibold text-foreground">模型命名规则</h3>
        <p className="text-sm leading-6 text-muted-foreground">
          所有模型统一使用{" "}
          <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">provider/model</code>{" "}
          格式。兼容端点使用{" "}
          <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">provider_alias/model_name</code>{" "}
          格式。Router 根据前缀路由到对应上游凭证。
        </p>

        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-secondary/50">
                <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">接入方式</th>
                <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Provider</th>
                <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">调用前缀</th>
                <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">示例 model 字段</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {PROVIDER_TABLE.map((row, idx) => (
                <tr key={idx} className="bg-background">
                  <td className="px-4 py-2.5 text-foreground">{row.access}</td>
                  <td className="px-4 py-2.5 text-foreground">{row.provider}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-foreground">{row.prefix}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">{row.example}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Hint */}
      <Card className="border-border bg-secondary/30">
        <CardContent className="flex items-start gap-3 p-4">
          <BookOpen className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="text-sm text-muted-foreground">
            完整可用模型列表在{" "}
            <a href="/portal/keys" className="font-medium text-foreground underline-offset-2 hover:underline">
              API Keys 页 → 可用模型
            </a>{" "}
            中查看。认证使用{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">Authorization: Bearer elp_...</code>{" "}
            或 <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">x-api-key</code> 请求头。
          </div>
        </CardContent>
      </Card>

      {/* API Reference */}
      <section>
        <h3 className="text-lg font-semibold text-foreground mb-6">API Reference</h3>

        <div className="grid gap-8 lg:grid-cols-[180px_1fr]">
          {/* Sidebar */}
          <ApiSidebar categories={CATEGORIES} endpoints={ENDPOINTS} />

          {/* Endpoint sections grouped by category */}
          <div className="min-w-0">
            {CATEGORIES.map((cat) => {
              const catEndpoints = ENDPOINTS.filter((e) => e.category === cat.id);
              if (catEndpoints.length === 0) return null;
              return (
                <div key={cat.id} className="mb-12">
                  <div id={`cat-${cat.id}`} className="scroll-mt-4 mb-6">
                    <h3 className="text-xl font-bold text-foreground">{cat.title}</h3>
                    {cat.description && (
                      <p className="mt-1 text-sm text-muted-foreground">{cat.description}</p>
                    )}
                  </div>
                  <div className="space-y-0">
                    {catEndpoints.map((ep) => (
                      <EndpointSection key={ep.id} endpoint={ep} base={base} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </div>
  );
}

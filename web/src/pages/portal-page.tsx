import { useEffect, useMemo, useRef, useState, type ComponentType, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckCircle2, ChevronDown, Link2, Search, Sparkles, TerminalSquare } from "lucide-react";

import { CodePanel } from "@/components/code-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  bootstrapRouterctl,
  getUiModels,
  listMyUpstreamCredentials,
  shareUpstreamCredential,
  startCodexOAuthBinding,
} from "@/lib/api";
import type {
  RouterctlBootstrapResponse,
  UiConfig,
  UiModelRecord,
  UiSession,
  UpstreamCredentialRecord,
} from "@/lib/types";
import { formatProviderLabel } from "@/lib/provider-labels";
import { useUiShell } from "@/context/ui-shell-context";

type PortalDependencies = {
  session: UiSession;
  config: UiConfig;
};

export function PortalPage(props: { session?: UiSession; config?: UiConfig }) {
  const context = usePortalDependencies(props);
  const queryClient = useQueryClient();
  const [claudeModel, setClaudeModel] = useState(context.config.default_claude_model);
  const [codexModel, setCodexModel] = useState(context.config.default_codex_model);

  const modelsQuery = useQuery({
    queryKey: ["ui-models"],
    queryFn: getUiModels,
  });
  const upstreamCredentialsQuery = useQuery({
    queryKey: ["me", "upstream-credentials"],
    queryFn: listMyUpstreamCredentials,
  });

  const allModels = useMemo(
    () => modelsQuery.data ?? buildFallbackModels(context.config),
    [context.config, modelsQuery.data]
  );
  const claudeOptions = allModels;
  const codexOptions = allModels;
  const upstreamCredentials = upstreamCredentialsQuery.data ?? [];

  useEffect(() => {
    if (claudeOptions.length && !claudeOptions.some((item) => item.id === claudeModel)) {
      setClaudeModel(claudeOptions[0].id);
    }
  }, [claudeModel, claudeOptions]);

  useEffect(() => {
    if (codexOptions.length && !codexOptions.some((item) => item.id === codexModel)) {
      setCodexModel(codexOptions[0].id);
    }
  }, [codexModel, codexOptions]);

  const routerctlBootstrapMutation = useMutation({
    mutationFn: bootstrapRouterctl,
  });
  const codexOauthMutation = useMutation({
    mutationFn: startCodexOAuthBinding,
    onSuccess: (payload) => {
      if (typeof window !== "undefined") {
        window.location.assign(payload.authorize_url);
      }
    },
  });
  const shareMutation = useMutation({
    mutationFn: shareUpstreamCredential,
    onSuccess: (updatedCredential) => {
      queryClient.setQueryData<UpstreamCredentialRecord[]>(
        ["me", "upstream-credentials"],
        (current) =>
          (current ?? []).map((item) => (item.id === updatedCredential.id ? updatedCredential : item))
      );
    },
  });

  const sessionChips = useMemo(() => {
    const email = context.session.email || "飞书未返回邮箱";
    return [
      { label: "身份", value: context.session.name || "未命名用户" },
      { label: "邮箱", value: email },
      { label: "角色", value: context.session.role === "admin" ? "管理员" : "成员" },
      {
        label: "团队",
        value: context.session.team_ids.length ? context.session.team_ids.join(", ") : "default",
      },
    ];
  }, [context.session]);

  const selectedClaudeModel = claudeOptions.find((item) => item.id === claudeModel);
  const selectedCodexModel = codexOptions.find((item) => item.id === codexModel);
  const claudeSwitchCommand = `cc-switch claude --model ${claudeModel}`;
  const codexSwitchCommand = `cc-switch codex --model ${codexModel}`;
  const codexBindCommand = "routerctl codex bind";

  return (
    <div className="space-y-6">
      <Card className="overflow-hidden ">
        <CardContent className="grid gap-8 p-8 md:grid-cols-[1.25fr_0.75fr] md:p-10">
          <div className="space-y-5">
            <Badge>Developer Access Portal</Badge>
            <div className="space-y-4">
              <h2 className="max-w-3xl text-4xl font-bold tracking-tight text-foreground md:text-5xl">
                安装 routerctl，绑定上游账号，然后用 cc-switch 启动客户端。
              </h2>
              <p className="max-w-3xl text-base leading-8 text-muted-foreground">
                routerctl 只负责登录和绑定；模型切换/客户端启动交给 cc-switch。
              </p>
            </div>
          </div>
          <div className="rounded-lg border border-border bg-secondary/80 p-6">
            <div className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              当前会话
            </div>
            <div className="mt-4 grid gap-3">
              {sessionChips.map((item) => (
                <div key={item.label} className="rounded-md bg-background px-4 py-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    {item.label}
                  </div>
                  <div className="mt-1 break-all text-sm font-medium text-foreground">{item.value}</div>
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <StepCard
          step="Step 1"
          title="安装 routerctl"
          description="先复制一次性 bootstrap token，再执行当前平台的安装命令。"
          icon={TerminalSquare}
        >
          <div className="space-y-4">
            <Button
              onClick={() => routerctlBootstrapMutation.mutate()}
              disabled={routerctlBootstrapMutation.isPending}
            >
              生成 routerctl 安装命令
            </Button>
            {routerctlBootstrapMutation.data ? (
              <>
                <RouterctlInstallReveal
                  payload={routerctlBootstrapMutation.data}
                  config={context.config}
                />
              </>
            ) : null}
          </div>
        </StepCard>

        <StepCard
          step="Step 2"
          title="绑定上游账号"
          description="Codex OAuth 默认仅本人可用；你或管理员显式授权后，才会进入企业共享池。"
          icon={Link2}
        >
          <div className="space-y-5">

            <CodePanel
              title="绑定 Claude Max 账号"
              value="routerctl claude bind"
              hint="从本机 Keychain 读取 Claude Code OAuth 凭证，导入企业 Router。需要已在本机用 `claude` 完成登录。"
            />

            <div className="flex flex-col gap-3 rounded-lg border border-border bg-secondary/60 p-5 md:flex-row md:items-center md:justify-between">
              <div className="space-y-1">
                <div className="text-sm font-semibold text-foreground">绑定 Codex / ChatGPT 账号</div>
                <div className="text-sm leading-6 text-muted-foreground">
                  默认推荐直接在本机运行 `routerctl codex bind`。如果服务端已经配置浏览器 broker，再使用网页直连绑定。
                </div>
              </div>
              {context.config.codex_oauth_browser_enabled ? (
                <Button
                  onClick={() => codexOauthMutation.mutate()}
                  disabled={codexOauthMutation.isPending}
                >
                  绑定 Codex 账号
                </Button>
              ) : null}
            </div>

            <CodePanel
              title="绑定 Codex / ChatGPT 账号"
              value={codexBindCommand}
              hint="先在本机完成 Codex 登录，再把私有 OAuth 凭证导入企业 Router。"
            />

            {context.config.codex_oauth_browser_enabled && codexOauthMutation.error ? (
              <InlineMessage>{String(codexOauthMutation.error.message)}</InlineMessage>
            ) : null}

            <div className="space-y-3">
              <div className="text-sm font-semibold text-foreground">我的上游绑定</div>
              {upstreamCredentials.length ? (
                <div className="space-y-3">
                  {upstreamCredentials.map((credential) => (
                    <Card key={credential.id} className="">
                      <CardContent className="flex flex-col gap-4 p-5 md:flex-row md:items-start md:justify-between">
                        <div className="space-y-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <div className="text-base font-semibold text-foreground">
                              {credential.account_id}
                            </div>
                            <Badge variant="secondary">
                              {formatProviderLabel(credential.provider)}
                            </Badge>
                            <Badge variant="outline">{credential.visibility ?? "private"}</Badge>
                            {credential.source ? <Badge variant="outline">{credential.source}</Badge> : null}
                            {credential.billing_model === "subscription" ? (
                              <Badge variant="secondary">订阅制</Badge>
                            ) : credential.billing_model === "pay_per_use" ? (
                              <Badge variant="outline">按量计费</Badge>
                            ) : null}
                          </div>
                          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-muted-foreground">
                            <span>认证方式</span>
                            <span className="text-foreground">{credential.auth_kind}</span>
                            <span>状态</span>
                            <span className="text-foreground">{credential.state}</span>
                            <span>过期时间</span>
                            <span className="text-foreground">
                              {credential.expires_at
                                ? new Date(credential.expires_at).toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" })
                                : "未披露"}
                            </span>
                          </div>
                        </div>
                        {credential.visibility !== "enterprise_pool" ? (
                          <Button
                            variant="outline"
                            onClick={() => shareMutation.mutate(credential.id)}
                            disabled={shareMutation.isPending}
                          >
                            共享到企业池
                          </Button>
                        ) : (
                          <div className="text-sm font-medium text-emerald-700">已在企业池中可路由</div>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-border bg-background p-5 text-sm leading-6 text-muted-foreground">
                  你还没有绑定上游账号。先绑定自己的 Codex 账号，后续就可以决定是仅本人可用，还是显式提升到企业池。
                </div>
              )}
            </div>
          </div>
        </StepCard>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <StepCard
          step="Step 3"
          title="用 cc-switch 启动 Coding CLI"
          description="routerctl 不再启动客户端；cc-switch 负责注入路由配置、选择模型并启动 Claude Code 或 Codex。"
          icon={Bot}
        >
          <Tabs defaultValue="claude" className="w-full space-y-5">
            <TabsList>
              <TabsTrigger value="claude">Claude Code</TabsTrigger>
              <TabsTrigger value="codex">Codex</TabsTrigger>
            </TabsList>
            <TabsContent value="claude" className="space-y-5">
              <div className="rounded-lg border border-border bg-secondary/30 px-4 py-3 text-sm text-muted-foreground">
                所有模型统一使用{" "}
                <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">provider/model</code>{" "}
                格式。Claude Max OAuth 模型用{" "}
                <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">claude-max/</code>{" "}
                前缀（如{" "}
                <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">claude-max/claude-sonnet-4-6</code>
                ），其他 BYOK 模型用对应 provider 前缀（如{" "}
                <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">openai/gpt-4o</code>
                ）。完整规则见{" "}
                <a href="/portal/docs" className="font-medium text-foreground underline-offset-2 hover:underline">API 文档</a>
                。
              </div>
              <div className="grid gap-5 md:grid-cols-[0.95fr_1.05fr]">
                <div className="space-y-4 rounded-lg border border-border bg-secondary/50 p-5">
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-foreground">
                      目标模型（可选，默认使用服务端配置）
                    </label>
                    <ModelSearchSelect
                      label="Claude Code 目标模型"
                      models={claudeOptions}
                      value={claudeModel}
                      onChange={setClaudeModel}
                    />
                  </div>
                  <ModelSummary model={selectedClaudeModel} />
                </div>
                <div>
                  <CommandResult
                    title="启动 Claude Code"
                    value={claudeSwitchCommand}
                    note="用 cc-switch 统一切换/启动模型；routerctl 仅保留 auth 和 bind。"
                  />
                </div>
              </div>
            </TabsContent>
            <TabsContent value="codex" className="space-y-5">
              <div className="rounded-lg border border-border bg-secondary/30 px-4 py-3 text-sm text-muted-foreground">
                所有模型统一使用{" "}
                <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">provider/model</code>{" "}
                格式。Codex OAuth 模型用{" "}
                <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">openai-codex/</code>{" "}
                前缀（如{" "}
                <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">openai-codex/gpt-5-codex</code>
                ），其他 BYOK 模型用对应 provider 前缀（如{" "}
                <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">openai/gpt-4o</code>
                ）。完整规则见{" "}
                <a href="/portal/docs" className="font-medium text-foreground underline-offset-2 hover:underline">API 文档</a>
                。
              </div>
              <div className="grid gap-5 md:grid-cols-[0.95fr_1.05fr]">
                <div className="space-y-4 rounded-lg border border-border bg-secondary/50 p-5">
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-foreground">
                      Codex 目标模型
                    </label>
                    <ModelSearchSelect
                      label="Codex 目标模型"
                      models={codexOptions}
                      value={codexModel}
                      onChange={setCodexModel}
                    />
                  </div>
                  <ModelSummary model={selectedCodexModel} />
                </div>
                <div>
                  <CommandResult
                    title="启动 Codex"
                    value={codexSwitchCommand}
                    note="用 cc-switch 统一切换/启动模型；routerctl 仅保留 auth 和 bind。"
                  />
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </StepCard>

        <StepCard
          step="Step 4"
          title="按顺序执行命令"
          description="安装好 routerctl 后，按顺序完成绑定，再用 cc-switch 启动。"
          icon={TerminalSquare}
        >
          <div className="space-y-4 text-sm leading-7 text-muted-foreground">
            <p>推荐顺序：</p>
            <ol className="space-y-3">
              <li>1. 在本机执行 Step 1 的安装命令，完成 routerctl 安装与首次登录。</li>
              <li>2. 如需 Codex OAuth 上游，执行 `routerctl codex bind`。</li>
              <li>3. 用 `cc-switch` 选择模型并启动 Claude Code 或 Codex，走企业 Router。</li>
              <li>4. 本机原有的 Claude Code 配置和 API Key 不受影响。</li>
            </ol>
            <Separator />
            <p className="font-mono text-xs text-muted-foreground">{context.config.router_public_base_url}</p>
          </div>
        </StepCard>

        <StepCard
          step="Step 5"
          title="完成直连验证"
          description="确认安装和登录都完成后，可以正常通过企业 Router 访问目标客户端。"
          icon={CheckCircle2}
        >
          <div className="space-y-4">
            <ValidationHint
              title="Claude Code"
              detail="运行 `cc-switch claude`，确认 Claude Code 正常启动并走企业 Router。"
            />
            <ValidationHint
              title="Codex"
              detail="运行 `cc-switch codex`，确认 Codex 正常启动并走企业 Router。"
            />
            <ValidationHint
              title="下一步"
              detail={
                context.session.role === "admin"
                  ? "你还可以进入 Admin 区，继续查看凭证池、配额策略和用量审计。"
                  : "如果需要配额或凭证支持，请联系管理员进入 Admin 区处理。"
              }
            />
          </div>
        </StepCard>
      </div>
    </div>
  );
}

function usePortalDependencies(props: { session?: UiSession; config?: UiConfig }): PortalDependencies {
  if (props.session && props.config) {
    return {
      session: props.session,
      config: props.config,
    };
  }
  return useUiShell();
}

function buildFallbackModels(config: UiConfig): UiModelRecord[] {
  return [
    {
      id: config.default_claude_model,
      display_name: config.default_claude_model,
      provider: "anthropic",
      description: "默认 Claude Code 模型",
      model_profile: `anthropic/${config.default_claude_model}`,
      supported_protocols: ["anthropic_messages"],
      supported_clients: ["claude_code"],
      auth_modes: ["oauth_subscription", "api_key"],
      experimental: false,
    },
    {
      id: config.default_codex_model,
      display_name: config.default_codex_model,
      provider: "openai-codex",
      description: "默认 Codex 模型",
      model_profile: `openai-codex/${config.default_codex_model}`,
      supported_protocols: ["openai_responses", "anthropic_messages"],
      supported_clients: ["claude_code", "codex"],
      auth_modes: ["codex_chatgpt_oauth_managed", "codex_chatgpt_oauth_imported"],
      experimental: true,
    },
  ];
}

function StepCard({
  step,
  title,
  description,
  icon: Icon,
  children,
}: {
  step: string;
  title: string;
  description: string;
  icon: ComponentType<{ className?: string }>;
  children: ReactNode;
}) {
  return (
    <Card className="">
      <CardHeader className="space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-2">
            <Badge variant="secondary">{step}</Badge>
            <CardTitle className="text-[28px] text-foreground">{title}</CardTitle>
            <CardDescription>{description}</CardDescription>
          </div>
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Icon className="h-6 w-6" />
          </div>
        </div>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

const POWERSHELL_WRAPPER_PREFIX = 'powershell -NoProfile -ExecutionPolicy Bypass -Command "';

function unwrapPowerShellCommand(command: string) {
  if (command.startsWith(POWERSHELL_WRAPPER_PREFIX) && command.endsWith('"')) {
    return command.slice(POWERSHELL_WRAPPER_PREFIX.length, -1);
  }
  return command;
}

function RouterctlInstallReveal({
      payload,
      config,
}: {
  payload: RouterctlBootstrapResponse;
  config: UiConfig;
}) {
  const unixTokenCommand = `export ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN="${payload.bootstrap_token}"`;
  const unixInstallCommand = `curl -fsSL ${config.routerctl_install_url} | bash`;
  const windowsTokenCommand = `$env:ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN="${payload.bootstrap_token}"`;
  const windowsInstallCommand = unwrapPowerShellCommand(payload.windows_install_command);

  return (
    <Card className="mt-4 border-border bg-background">
      <CardHeader>
        <CardTitle className="text-base text-foreground">routerctl 安装命令</CardTitle>
        <CardDescription>请按下面两步执行：先设置一次性 bootstrap token，再执行你当前平台的安装命令。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Tabs defaultValue="unix" className="w-full space-y-4">
          <TabsList>
            <TabsTrigger value="unix">macOS / Linux</TabsTrigger>
            <TabsTrigger value="windows">Windows</TabsTrigger>
          </TabsList>

          <TabsContent value="unix" className="space-y-4">
            <CodePanel title="先执行这一行" value={unixTokenCommand} />
            <CodePanel title="再执行安装命令" value={unixInstallCommand} />
            <ol className="list-decimal space-y-2 pl-5 text-sm leading-6 text-muted-foreground">
              <li>先在当前终端执行第一行，写入一次性 bootstrap token。</li>
              <li>再执行第二行，脚本会安装 `routerctl` 并自动完成首次登录。</li>
              <li>看到安装完成后，回到本页继续绑定上游账号或启动客户端。</li>
            </ol>
          </TabsContent>

          <TabsContent value="windows" className="space-y-4">
            <CodePanel title="先执行这一行" value={windowsTokenCommand} />
            <CodePanel title="再执行安装命令" value={windowsInstallCommand} />
            <ol className="list-decimal space-y-2 pl-5 text-sm leading-6 text-muted-foreground">
              <li>打开 PowerShell，先执行第一行，写入一次性 bootstrap token。</li>
              <li>再执行第二行，脚本会安装 `routerctl`，并自动执行 `routerctl auth bootstrap` 完成首次登录。</li>
              <li>看到安装完成后，回到本页继续绑定上游账号或启动客户端。</li>
            </ol>
          </TabsContent>
        </Tabs>

        <div className="text-sm text-muted-foreground">有效期至：{payload.expires_at}</div>
      </CardContent>
    </Card>
  );
}

function ModelSummary({ model }: { model: UiModelRecord | undefined }) {
  if (!model) {
    return (
      <div className="rounded-md border border-dashed border-border bg-background p-4 text-sm text-muted-foreground">
        还没有拿到可用模型目录。
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border bg-background p-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="text-sm font-semibold text-foreground">{model.display_name}</div>
        <Badge variant="secondary">{formatProviderLabel(model.provider)}</Badge>
        {model.experimental ? <Badge variant="outline">experimental</Badge> : null}
      </div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{model.description}</p>
      <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
        {model.supported_protocols.map((protocol) => (
          <span key={protocol} className="rounded-full bg-secondary px-3 py-1">
            {protocol}
          </span>
        ))}
      </div>
    </div>
  );
}

function CommandResult({
  title,
  value,
  note,
}: {
  title: string;
  value: string;
  note: string;
}) {
  return (
    <CodePanel title={title} value={value} hint={note} />
  );
}

function InlineMessage({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      {children}
    </div>
  );
}

function ModelSearchSelect({
  label,
  models,
  value,
  onChange,
}: {
  label: string;
  models: UiModelRecord[];
  value: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    if (!q) return models;
    return models.filter(
      (m) =>
        m.display_name.toLowerCase().includes(q) ||
        m.id.toLowerCase().includes(q) ||
        m.provider.toLowerCase().includes(q)
    );
  }, [models, search]);

  const selected = models.find((m) => m.id === value);
  const listboxId = `${label.replace(/\s+/g, "-").toLowerCase()}-listbox`;

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSearch("");
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Focus search input when opened
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm transition-colors hover:border-foreground/40 focus:outline-none focus:ring-1 focus:ring-ring"
      >
        <span className="truncate">
          {selected ? `${selected.display_name} (${selected.id})` : "选择模型…"}
        </span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div
          id={listboxId}
          role="listbox"
          aria-label={label}
          className="absolute z-50 mt-1 w-full rounded-md border border-border bg-background shadow-lg"
        >
          {/* Search input */}
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <input
              ref={inputRef}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索模型…"
              className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
            />
          </div>
          {/* Options list */}
          <div className="max-h-52 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <div className="px-4 py-3 text-xs text-muted-foreground">未找到匹配模型</div>
            ) : (
              filtered.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  role="option"
                  aria-selected={m.id === value}
                  onClick={() => { onChange(m.id); setOpen(false); setSearch(""); }}
                  className={[
                    "flex w-full flex-col items-start px-3 py-2 text-left text-sm transition-colors hover:bg-secondary",
                    m.id === value ? "bg-primary/10 text-primary" : "text-foreground",
                  ].join(" ")}
                >
                  <span className="font-medium">{m.display_name}</span>
                  <span className="font-mono text-[11px] text-muted-foreground">{m.id}</span>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ValidationHint({
  title,
  detail,
}: {
  title: string;
  detail: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-background p-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <Sparkles className="h-4 w-4 text-primary" />
        {title}
      </div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{detail}</p>
    </div>
  );
}

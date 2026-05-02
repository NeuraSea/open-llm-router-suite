import { Activity, BookOpen, Database, Gauge, Key, KeyRound, Moon, Plug2, ScrollText, Settings, ShieldCheck, Sun, Terminal, Users2 } from "lucide-react";
import type { ComponentType, ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { useTheme } from "@/hooks/use-theme";
import type { UiConfig, UiSession } from "@/lib/types";

type NavItem = {
  label: string;
  to: string;
  icon: ComponentType<{ className?: string }>;
};

function buildNav(session: UiSession): { primary: NavItem[]; admin: NavItem[] } {
  const primary: NavItem[] = [
    { label: "API Keys", to: "/portal/keys", icon: Key },
    { label: "Activity", to: "/portal/activity", icon: Activity },
    { label: "Logs", to: "/portal/logs", icon: ScrollText },
    { label: "BYOK", to: "/portal/byok", icon: Plug2 },
    { label: "Preferences", to: "/portal/preferences", icon: Settings },
    { label: "routerctl / OAuth 绑定", to: "/portal/setup", icon: Terminal },
    { label: "API 文档", to: "/portal/docs", icon: BookOpen },
  ];
  const admin: NavItem[] =
    session.role === "admin"
      ? [
          { label: "凭证池", to: "/portal/admin/credentials", icon: KeyRound },
          { label: "用量审计", to: "/portal/admin/usage", icon: Gauge },
          { label: "会话管理", to: "/portal/admin/users", icon: Users2 },
          { label: "配额策略", to: "/portal/admin/quotas", icon: ShieldCheck },
          { label: "模型目录", to: "/portal/admin/models", icon: Database },
        ]
      : [];

  return { primary, admin };
}

export function AppShell({
  session,
  config,
  children,
}: {
  session: UiSession;
  config: UiConfig;
  children: ReactNode;
}) {
  const location = useLocation();
  const nav = buildNav(session);
  const { theme, toggle } = useTheme();

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-4 px-4 py-4 lg:flex-row lg:px-6">
        <aside className="w-full lg:sticky lg:top-4 lg:w-[280px] lg:self-start">
          <Card className="overflow-hidden border-border/80">
            <CardContent className="space-y-5 p-5">
              {/* Brand */}
              <Link to="/portal" className="block space-y-1.5 group">
                <h1 className="text-lg font-semibold tracking-tight text-foreground leading-snug group-hover:text-primary transition-colors">
                  Enterprise Router
                </h1>
                <p className="text-sm text-muted-foreground leading-5">
                  One API for any model.
                </p>
              </Link>

              {/* Session */}
              <div className="rounded-lg border border-border bg-muted/50 p-3.5">
                <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-2.5">
                  当前会话
                </div>
                <div className="space-y-1.5">
                  <div className="text-base font-semibold text-foreground">
                    {session.name || "未命名用户"}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {session.email || "飞书未返回邮箱"}
                  </div>
                  <div className="flex flex-wrap gap-1.5 pt-0.5">
                    <Badge variant="outline" className="text-xs">
                      {session.role === "admin" ? "管理员" : "成员"}
                    </Badge>
                    {(session.team_ids.length ? session.team_ids : ["default"]).map((teamId) => (
                      <Badge variant="secondary" key={teamId} className="text-xs">
                        {teamId}
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>

              {/* Nav */}
              <div className="space-y-4">
                <div className="space-y-1">
                  <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground px-1 mb-1">
                    工作区
                  </div>
                  <nav className="space-y-0.5">
                    {nav.primary.map((item) => (
                      <NavItemLink key={item.to} item={item} currentPath={location.pathname} />
                    ))}
                  </nav>
                </div>
                {nav.admin.length ? (
                  <div className="space-y-1">
                    <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground px-1 mb-1">
                      Admin
                    </div>
                    <nav className="space-y-0.5">
                      {nav.admin.map((item) => (
                        <NavItemLink key={item.to} item={item} currentPath={location.pathname} />
                      ))}
                    </nav>
                  </div>
                ) : null}
              </div>

              {/* API Base */}
              <div className="rounded-lg border border-dashed border-border p-3">
                <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-1.5">
                  API Base
                </div>
                <div className="font-mono text-xs text-foreground break-all leading-5">
                  {config.router_public_base_url}
                </div>
              </div>

              {/* Theme toggle */}
              <Button
                variant="ghost"
                size="sm"
                onClick={toggle}
                className="w-full justify-start gap-2 text-muted-foreground hover:text-foreground"
              >
                {theme === "dark" ? (
                  <>
                    <Sun className="h-3.5 w-3.5" />
                    <span className="text-xs">切换亮色</span>
                  </>
                ) : (
                  <>
                    <Moon className="h-3.5 w-3.5" />
                    <span className="text-xs">切换暗色</span>
                  </>
                )}
              </Button>
            </CardContent>
          </Card>
        </aside>
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

function NavItemLink({
  item,
  currentPath,
}: {
  item: NavItem;
  currentPath: string;
}) {
  const Icon = item.icon;
  const active = currentPath === item.to || currentPath.startsWith(`${item.to}/`);

  return (
    <NavLink
      to={item.to}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
        active
          ? "bg-primary text-primary-foreground font-medium"
          : "text-muted-foreground font-normal hover:bg-secondary hover:text-foreground"
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span>{item.label}</span>
    </NavLink>
  );
}

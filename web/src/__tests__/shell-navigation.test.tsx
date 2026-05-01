import { MemoryRouter } from "react-router-dom";
import { render, screen } from "@testing-library/react";

import { AppShell } from "@/components/app-shell";
import type { UiConfig, UiSession } from "@/lib/types";

const config: UiConfig = {
  app_name: "企业级 LLM Router 控制台",
  router_public_base_url: "https://router.example.com/v1",
  router_control_plane_base_url: "https://router.example.com",
  routerctl_install_url: "https://router.example.com/install/routerctl.sh",
  routerctl_windows_install_url: "https://router.example.com/install/routerctl.ps1",
  default_claude_model: "claude-sonnet-4-20250514",
  default_codex_model: "gpt-5-codex",
  platform_api_key_env: "ENTERPRISE_LLM_PROXY_API_KEY",
  feishu_authorize_url: "https://accounts.feishu.cn/open-apis/authen/v1/authorize?client_id=cli_test",
  codex_oauth_browser_enabled: false,
};

describe("AppShell", () => {
  it("hides admin navigation for member users", () => {
    const session: UiSession = {
      user_id: "u-member",
      email: "member@example.com",
      name: "Member",
      team_ids: ["platform"],
      role: "member",
    };

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppShell session={session} config={config}>
          <div>content</div>
        </AppShell>
      </MemoryRouter>
    );

    expect(screen.queryByText("凭证池")).not.toBeInTheDocument();
  });

  it("shows admin navigation for admin users", () => {
    const session: UiSession = {
      user_id: "u-admin",
      email: "admin@example.com",
      name: "Admin",
      team_ids: ["platform"],
      role: "admin",
    };

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppShell session={session} config={config}>
          <div>content</div>
        </AppShell>
      </MemoryRouter>
    );

    expect(screen.getByText("凭证池")).toBeInTheDocument();
    expect(screen.getByText("配额策略")).toBeInTheDocument();
    expect(screen.getByText("用量审计")).toBeInTheDocument();
  });
});

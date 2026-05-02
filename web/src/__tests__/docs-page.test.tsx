import { render, screen } from "@testing-library/react";

import { UiShellProvider } from "@/context/ui-shell-context";
import { DocsPage } from "@/pages/docs-page";
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

const session: UiSession = {
  user_id: "u-member",
  email: "member@example.com",
  name: "Member",
  team_ids: ["platform"],
  role: "member",
};

function renderPage() {
  const observe = vi.fn();
  const disconnect = vi.fn();
  vi.stubGlobal(
    "IntersectionObserver",
    vi.fn(() => ({
      observe,
      disconnect,
      unobserve: vi.fn(),
      takeRecords: vi.fn(() => []),
    }))
  );

  return render(
    <UiShellProvider value={{ config, session }}>
      <DocsPage />
    </UiShellProvider>
  );
}

describe("DocsPage", () => {
  it("surfaces the routerctl to New API quickstart before the API reference", () => {
    renderPage();

    expect(screen.getByText("routerctl + New API Quickstart")).toBeInTheDocument();
    expect(screen.getByText("routerctl auth login --router-base-url https://router.example.com")).toBeInTheDocument();
    expect(screen.getByText("routerctl codex bind")).toBeInTheDocument();
    expect(screen.getByText("routerctl claude bind")).toBeInTheDocument();
    expect(screen.getAllByText(/使用 New API token/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/https:\/\/router\.example\.com\/v1/).length).toBeGreaterThan(0);
  });
});

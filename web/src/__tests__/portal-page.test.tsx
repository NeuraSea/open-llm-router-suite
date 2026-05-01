import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PortalPage } from "@/pages/portal-page";
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

const memberSession: UiSession = {
  user_id: "u-member",
  email: "member@example.com",
  name: "Member",
  team_ids: ["platform"],
  role: "member",
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PortalPage session={memberSession} config={config} />
    </QueryClientProvider>
  );
}

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    status: 200,
    headers: {
      get: () => "application/json",
    },
    json: async () => payload,
  };
}

describe("PortalPage", () => {
  it("surfaces routerctl install commands for unix and windows", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/ui/models") {
        return Promise.resolve(jsonResponse({ data: [] }));
      }
      if (url === "/me/upstream-credentials") {
        return Promise.resolve(jsonResponse({ data: [] }));
      }
      if (url === "/developer/bootstrap/routerctl" && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse({
            bootstrap_token: "bootstrap-token",
            expires_at: "2026-03-19T00:10:00+00:00",
            install_command:
              'export NO_PROXY="router.example.com,localhost,127.0.0.1"; export no_proxy="$NO_PROXY"; export ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN="bootstrap-token"; curl --noproxy router.example.com -fsSL https://router.example.com/install/routerctl.sh | bash',
            windows_install_command:
              'powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; $env:NO_PROXY=\'router.example.com,localhost,127.0.0.1\'; $env:no_proxy=$env:NO_PROXY; $env:ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN=\'bootstrap-token\'; iwr \'https://router.example.com/install/routerctl.ps1\' -UseBasicParsing | iex"',
          })
        );
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();
    await user.click(screen.getByRole("button", { name: "生成 routerctl 安装命令" }));

    await waitFor(() => {
      expect(screen.getByText(/install\/routerctl\.sh/)).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "macOS / Linux" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "Windows" })).toBeInTheDocument();
      expect(screen.getByText("请按下面两步执行：先设置一次性 bootstrap token，再执行你当前平台的安装命令。")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("tab", { name: "Windows" }));

    await waitFor(() => {
      expect(screen.getByText(/\[Net\.ServicePointManager\]::SecurityProtocol/)).toBeInTheDocument();
      expect(screen.getByText(/install\/routerctl\.ps1/)).toBeInTheDocument();
      expect(screen.getByText("打开 PowerShell，先执行第一行，写入一次性 bootstrap token。")).toBeInTheDocument();
      expect(screen.getByText("再执行第二行，脚本会安装 `routerctl`，并自动执行 `routerctl auth bootstrap` 完成首次登录。")).toBeInTheDocument();
    });
  });

  it("keeps private LAN bootstrap copy out of the protected portal flow", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/ui/models") {
        return Promise.resolve(
          jsonResponse({
            data: [
              {
                id: "claude-sonnet-4-20250514",
                display_name: "Claude Sonnet 4",
                provider: "anthropic",
                description: "Anthropic native model",
                model_profile: "anthropic/claude-sonnet-4-20250514",
                supported_protocols: ["anthropic_messages"],
                supported_clients: ["claude_code"],
                auth_modes: ["oauth_subscription", "api_key"],
                experimental: false,
              },
              {
                id: "gpt-5-codex",
                display_name: "GPT-5 Codex",
                provider: "openai-codex",
                description: "Codex OAuth backed GPT model",
                model_profile: "openai-codex/gpt-5-codex",
                supported_protocols: ["openai_responses", "anthropic_messages"],
                supported_clients: ["claude_code", "codex"],
                auth_modes: ["codex_chatgpt_oauth_managed"],
                experimental: true,
              },
            ],
          })
        );
      }
      if (url === "/me/upstream-credentials") {
        return Promise.resolve(jsonResponse({ data: [] }));
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(screen.queryByRole("button", { name: "生成直连安装命令" })).not.toBeInTheDocument();
    expect(screen.queryByText(/公司局域网/)).not.toBeInTheDocument();
    expect(screen.queryByText(/内网页面/)).not.toBeInTheDocument();
    expect(screen.queryByText(/internal\.example\.com/)).not.toBeInTheDocument();
  });

  it("renders cc-switch command guidance for Claude Code", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/ui/models") {
        return Promise.resolve(
          jsonResponse({
            data: [
              {
                id: "claude-sonnet-4-20250514",
                display_name: "Claude Sonnet 4",
                provider: "anthropic",
                description: "Anthropic native model",
                model_profile: "anthropic/claude-sonnet-4-20250514",
                supported_protocols: ["anthropic_messages"],
                supported_clients: ["claude_code"],
                auth_modes: ["oauth_subscription", "api_key"],
                experimental: false,
              },
              {
                id: "gpt-5-codex",
                display_name: "GPT-5 Codex",
                provider: "openai-codex",
                description: "Codex OAuth backed GPT model",
                model_profile: "openai-codex/gpt-5-codex",
                supported_protocols: ["openai_responses", "anthropic_messages"],
                supported_clients: ["claude_code", "codex"],
                auth_modes: ["codex_chatgpt_oauth_managed"],
                experimental: true,
              },
            ],
          })
        );
      }
      if (url === "/me/upstream-credentials") {
        return Promise.resolve(jsonResponse({ data: [] }));
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    await user.click(screen.getByRole("button", { name: "Claude Code 目标模型" }));
    await user.click(await screen.findByRole("option", { name: /GPT-5 Codex\s+gpt-5-codex/ }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Claude Code 目标模型" })).toHaveTextContent(
        "GPT-5 Codex (gpt-5-codex)"
      );
      expect(screen.getAllByText(/cc-switch/).length).toBeGreaterThan(0);
      expect(screen.getByText("routerctl claude bind")).toBeInTheDocument();
    });
  });

  it("shows routerctl bind codex as the default upstream binding path", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/ui/models") {
        return Promise.resolve(
          jsonResponse({
            data: [
              {
                id: "gpt-5-codex",
                display_name: "GPT-5 Codex",
                provider: "openai-codex",
                description: "Codex OAuth backed GPT model",
                model_profile: "openai-codex/gpt-5-codex",
                supported_protocols: ["openai_responses", "anthropic_messages"],
                supported_clients: ["claude_code", "codex"],
                auth_modes: ["codex_chatgpt_oauth_managed"],
                experimental: true,
              },
            ],
          })
        );
      }
      if (url === "/me/upstream-credentials") {
        return Promise.resolve(
          jsonResponse({
            data: [
              {
                id: "cred_1",
                provider: "openai-codex",
                auth_kind: "codex_chatgpt_oauth_managed",
                account_id: "openai-user-1",
                scopes: ["openid", "offline_access"],
                state: "active",
                expires_at: "2030-01-01T00:00:00+00:00",
                cooldown_until: null,
                owner_principal_id: "u-member",
                visibility: "private",
                source: "codex_chatgpt_oauth_managed",
                max_concurrency: 1,
                concurrent_leases: 0,
              },
            ],
          })
        );
      }
      if (url === "/me/upstream-credentials/cred_1/share" && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse({
            id: "cred_1",
            provider: "openai-codex",
            auth_kind: "codex_chatgpt_oauth_managed",
            account_id: "openai-user-1",
            scopes: ["openid", "offline_access"],
            state: "active",
            expires_at: "2030-01-01T00:00:00+00:00",
            cooldown_until: null,
            owner_principal_id: "u-member",
            visibility: "enterprise_pool",
            source: "codex_chatgpt_oauth_managed",
            max_concurrency: 1,
            concurrent_leases: 0,
          })
        );
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(await screen.findByText("openai-user-1")).toBeInTheDocument();
    expect(screen.getByText("routerctl codex bind")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "共享到企业池" }));

    await waitFor(() => {
      expect(screen.getByText("enterprise_pool")).toBeInTheDocument();
    });
  });
});

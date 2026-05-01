import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";

import { App } from "@/app";
import { CredentialsPage } from "@/pages/credentials-page";
import { QuotasPage } from "@/pages/quotas-page";
import { UsagePage } from "@/pages/usage-page";

function renderWithQueryClient(node: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>);
}

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: true,
    status,
    headers: {
      get: () => "application/json",
    },
    json: async () => payload,
  };
}

describe("Admin UI", () => {
  it("renders credentials from the admin API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          data: [
            {
              id: "cred_1",
              provider: "openai-codex",
              auth_kind: "codex_chatgpt_oauth_managed",
              account_id: "acct_01",
              scopes: ["responses", "messages"],
              state: "active",
              expires_at: null,
              cooldown_until: null,
              owner_principal_id: "u_member",
              visibility: "private",
              source: "codex_chatgpt_oauth_managed",
              max_concurrency: 4,
              concurrent_leases: 1,
            },
          ],
        })
      )
    );

    renderWithQueryClient(<CredentialsPage />);

    expect(await screen.findByText("acct_01")).toBeInTheDocument();
    expect(screen.getByText("responses, messages")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByText("u_member")).toBeInTheDocument();
    expect(screen.getByText("private")).toBeInTheDocument();
    expect(screen.getAllByText("codex_chatgpt_oauth_managed")).toHaveLength(2);
  });

  it("updates and deletes credentials from the admin page", async () => {
    const user = userEvent.setup();
    let credentials = [
      {
        id: "cred_1",
        provider: "openai-codex",
        auth_kind: "codex_chatgpt_oauth_managed",
        account_id: "acct_01",
        scopes: ["responses"],
        state: "active",
        expires_at: null,
        cooldown_until: null,
        owner_principal_id: "u_member",
        visibility: "enterprise_pool",
        source: "codex_chatgpt_oauth_managed",
        max_concurrency: 4,
        concurrent_leases: 1,
      },
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/admin/credentials" && method === "GET") {
        return Promise.resolve(jsonResponse({ data: credentials }));
      }
      if (url === "/admin/credentials/cred_1" && method === "PATCH") {
        const body = JSON.parse(String(init?.body));
        credentials = credentials.map((credential) =>
          credential.id === "cred_1"
            ? { ...credential, max_concurrency: body.max_concurrency }
            : credential
        );
        return Promise.resolve(jsonResponse(credentials[0]));
      }
      if (url === "/admin/upstream-credentials/cred_1/demote" && method === "POST") {
        credentials = credentials.map((credential) =>
          credential.id === "cred_1"
            ? { ...credential, visibility: "private" }
            : credential
        );
        return Promise.resolve(jsonResponse(credentials[0]));
      }
      if (url === "/admin/credentials/cred_1" && method === "DELETE") {
        credentials = [];
        return Promise.resolve(jsonResponse(null, 204));
      }
      return Promise.reject(new Error(`Unexpected request: ${method} ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn(() => true));

    renderWithQueryClient(<CredentialsPage />);

    const concurrencyInput = await screen.findByLabelText("acct_01 并发上限");
    await user.clear(concurrencyInput);
    await user.type(concurrencyInput, "6");
    expect(concurrencyInput).toHaveValue(6);
    const saveButton = screen.getByLabelText("保存 acct_01 并发上限");
    await waitFor(() => {
      expect(saveButton).toBeEnabled();
    });
    await user.click(saveButton);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/admin/credentials/cred_1",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ max_concurrency: 6 }),
        })
      );
    });

    await user.click(screen.getByLabelText("收回 acct_01 到私有"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/admin/upstream-credentials/cred_1/demote",
        expect.objectContaining({ method: "POST" })
      );
      expect(screen.getByText("private")).toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("删除 acct_01"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/admin/credentials/cred_1",
        expect.objectContaining({ method: "DELETE" })
      );
    });
    expect(window.confirm).toHaveBeenCalledWith(
      '确定要删除上游凭证 "acct_01" 吗？此操作不可撤销。'
    );
  });

  it("renders quotas from the admin API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          data: [{ scope_type: "team", scope_id: "platform", limit: 250000 }],
        })
      )
    );

    renderWithQueryClient(<QuotasPage />);

    expect(await screen.findByText("platform")).toBeInTheDocument();
    expect(screen.getByText("250000")).toBeInTheDocument();
  });

  it("filters usage records by keyword", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/admin/usage") {
          return Promise.resolve(
            jsonResponse({
              data: [
                {
                  request_id: "req_success",
                  principal_id: "u_admin",
                  model_profile: "gpt-5-codex",
                  provider: "openai",
                  credential_id: "cred_openai",
                  tokens_in: 100,
                  tokens_out: 200,
                  latency_ms: 900,
                  status: "success",
                  created_at: 1710806400,
                },
                {
                  request_id: "req_failed",
                  principal_id: "u_admin",
                  model_profile: "claude-sonnet-4-20250514",
                  provider: "anthropic",
                  credential_id: "cred_anthropic",
                  tokens_in: 120,
                  tokens_out: 0,
                  latency_ms: 1300,
                  status: "failed",
                  created_at: 1710807400,
                },
              ],
            })
          );
        }
        if (url === "/admin/usage/summary?period=30d") {
          return Promise.resolve(
            jsonResponse({
              data: [
                {
                  principal_id: "u_admin",
                  principal_email: "admin@example.com",
                  model_profile: "gpt-5-codex",
                  tokens_in: 100,
                  tokens_out: 200,
                  request_count: 1,
                },
                {
                  principal_id: "u_admin",
                  principal_email: "admin@example.com",
                  model_profile: "claude-sonnet-4-20250514",
                  tokens_in: 120,
                  tokens_out: 0,
                  request_count: 1,
                },
              ],
            })
          );
        }
        return Promise.reject(new Error(`Unexpected request: ${url}`));
      })
    );

    renderWithQueryClient(<UsagePage />);

    await user.click(await screen.findByRole("tab", { name: "原始事件" }));

    expect(await screen.findByText("req_success")).toBeInTheDocument();
    expect(screen.getByText("req_failed")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("搜索 request_id / principal_id / model"), "failed");

    await waitFor(() => {
      expect(screen.queryByText("req_success")).not.toBeInTheDocument();
      expect(screen.getByText("req_failed")).toBeInTheDocument();
    });
  });

  it("shows a friendly 403 page when a member opens an admin route directly", async () => {
    window.history.pushState({}, "", "/portal/admin/credentials");

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/ui/config") {
          return Promise.resolve(
            jsonResponse({
              app_name: "企业级 LLM Router 控制台",
              router_public_base_url: "https://router.example.com/v1",
              default_claude_model: "claude-sonnet-4-20250514",
              default_codex_model: "gpt-5-codex",
              platform_api_key_env: "ENTERPRISE_LLM_PROXY_API_KEY",
              feishu_authorize_url:
                "https://accounts.feishu.cn/open-apis/authen/v1/authorize?client_id=cli_test",
            })
          );
        }
        if (url === "/ui/session") {
          return Promise.resolve(
            jsonResponse({
              user_id: "u_member",
              email: "member@example.com",
              name: "Member",
              team_ids: ["platform"],
              role: "member",
            })
          );
        }
        return Promise.reject(new Error(`Unexpected request: ${url}`));
      })
    );

    render(<App />);

    expect(await screen.findByText("你没有访问这个区域的权限")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "回到开发者接入页" })).toHaveAttribute("href", "/portal");
  });
});

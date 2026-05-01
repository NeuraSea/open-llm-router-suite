import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";

import { PreferencesPage } from "@/pages/preferences-page";

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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PreferencesPage />
    </QueryClientProvider>
  );
}

describe("PreferencesPage", () => {
  it("requests routable-only ui models and warns when the saved default model is stale", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/me/preferences") {
        return Promise.resolve(
          jsonResponse({
            user_id: "u-member",
            default_model: "openai/gpt-4.1",
            routing_config: {},
          })
        );
      }
      if (url === "/ui/models?routable_only=true") {
        return Promise.resolve(
          jsonResponse({
            data: [
              {
                id: "openai-codex/gpt-5.4",
                display_name: "GPT-5.4 (Codex)",
                provider: "openai-codex",
                provider_alias: null,
                description: "GPT-5.4 via Codex OAuth backend.",
                model_profile: "openai-codex/gpt-5.4",
                upstream_model: "gpt-5.4",
                supported_protocols: ["openai_chat", "openai_responses", "anthropic_messages"],
                supported_clients: ["claude_code", "codex"],
                auth_modes: ["codex_chatgpt_oauth_imported"],
                experimental: true,
                source: "catalog",
              },
            ],
          })
        );
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("默认模型已失效，需要重新选择。")).toBeInTheDocument();
    });
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiKeysPage } from "@/pages/api-keys-page";

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
      <ApiKeysPage />
    </QueryClientProvider>
  );
}

describe("ApiKeysPage", () => {
  it("requests routable-only ui models and groups compat models by alias", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/me/api-keys") {
        return Promise.resolve(jsonResponse({ data: [] }));
      }
      if (url === "/me/usage/activity?period=7d") {
        return Promise.resolve(jsonResponse({ data: [], period: "7d" }));
      }
      if (url === "/ui/models?routable_only=true") {
        return Promise.resolve(
          jsonResponse({
            data: [
              {
                id: "zai-org/glm-4.7-flash",
                display_name: "glm-4.7-flash",
                provider: "openai_compat",
                provider_alias: "zai-org",
                description: "glm-4.7-flash via zai-org",
                model_profile: "glm-4.7-flash",
                upstream_model: "glm-4.7-flash",
                supported_protocols: ["openai_chat", "openai_responses"],
                supported_clients: ["codex"],
                auth_modes: ["api_key"],
                experimental: false,
                source: "byok",
              },
            ],
          })
        );
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    await user.click(await screen.findByRole("button", { name: "展开" }));

    await waitFor(() => {
      expect(screen.getByText("zai-org")).toBeInTheDocument();
      expect(screen.queryByText("OpenAI API")).not.toBeInTheDocument();
    });
  });
});

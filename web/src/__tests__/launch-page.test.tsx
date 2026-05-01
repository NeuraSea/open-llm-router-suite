import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { LaunchPage } from "@/pages/launch-page";

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={["/feishu/launch"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <LaunchPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("LaunchPage", () => {
  it("renders the Feishu authorize CTA from ui config", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        app_name: "企业级 LLM Router 控制台",
        feishu_authorize_url:
          "https://accounts.feishu.cn/open-apis/authen/v1/authorize?client_id=cli_test",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("link", { name: "继续使用飞书登录" })).toHaveAttribute(
        "href",
        "https://accounts.feishu.cn/open-apis/authen/v1/authorize?client_id=cli_test"
      );
    });
  });
});

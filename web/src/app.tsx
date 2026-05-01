import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useEffect, type ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { LoadingScreen } from "@/components/loading-screen";
import { UiShellProvider, useUiShell } from "@/context/ui-shell-context";
import { getUiConfig, getUiSession } from "@/lib/api";
import { ApiError } from "@/lib/types";
import { ActivityPage } from "@/pages/activity-page";
import { ApiKeysPage } from "@/pages/api-keys-page";
import { DocsPage } from "@/pages/docs-page";
import { ByokPage } from "@/pages/byok-page";
import { CredentialsPage } from "@/pages/credentials-page";
import { DashboardPage } from "@/pages/dashboard-page";
import { ForbiddenPage } from "@/pages/forbidden-page";
import { LaunchPage } from "@/pages/launch-page";
import { LogsPage } from "@/pages/logs-page";
import { PlaceholderPage } from "@/pages/placeholder-page";
import { PortalPage } from "@/pages/portal-page";
import { PreferencesPage } from "@/pages/preferences-page";
import { QuotasPage } from "@/pages/quotas-page";
import { SessionsPage } from "@/pages/sessions-page";
import { ModelsPage } from "@/pages/models-page";
import { UsagePage } from "@/pages/usage-page";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/" element={<Navigate to="/portal" replace />} />
          <Route path="/feishu/launch" element={<LaunchPage />} />
          <Route path="/portal/*" element={<PortalLayout />}>
            <Route index element={<DashboardPage />} />
            <Route path="keys" element={<ApiKeysPage />} />
            <Route path="activity" element={<ActivityPage />} />
            <Route path="logs" element={<LogsPage />} />
            <Route path="byok" element={<ByokPage />} />
            <Route path="preferences" element={<PreferencesPage />} />
            <Route path="setup" element={<PortalPage />} />
            <Route path="docs" element={<DocsPage />} />
            <Route
              path="admin/credentials"
              element={
                <AdminOnly>
                  <CredentialsPage />
                </AdminOnly>
              }
            />
            <Route
              path="admin/quotas"
              element={
                <AdminOnly>
                  <QuotasPage />
                </AdminOnly>
              }
            />
            <Route
              path="admin/usage"
              element={
                <AdminOnly>
                  <UsagePage />
                </AdminOnly>
              }
            />
            <Route
              path="admin/users"
              element={
                <AdminOnly>
                  <SessionsPage />
                </AdminOnly>
              }
            />
            <Route
              path="admin/models"
              element={
                <AdminOnly>
                  <ModelsPage />
                </AdminOnly>
              }
            />
            <Route path="*" element={<Navigate to="/portal" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

function PortalLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const configQuery = useQuery({
    queryKey: ["ui-config"],
    queryFn: getUiConfig,
  });
  const sessionQuery = useQuery({
    queryKey: ["ui-session"],
    queryFn: getUiSession,
  });

  useEffect(() => {
    if (sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401) {
      navigate("/feishu/launch", { replace: true, state: { from: location.pathname } });
    }
  }, [location.pathname, navigate, sessionQuery.error]);

  if (configQuery.isLoading || sessionQuery.isLoading) {
    return <LoadingScreen title="正在载入控制台" description="我们在拉取当前会话和前端配置。" />;
  }

  if (configQuery.error || sessionQuery.error) {
    if (sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401) {
      return <LoadingScreen title="正在跳转到飞书登录" description="你还没有可用登录态，马上转入登录入口。" />;
    }

    return (
      <LoadingScreen
        title="控制台暂时不可用"
        description="后端接口返回了异常，请刷新页面或检查服务日志。"
      />
    );
  }

  const config = configQuery.data;
  const session = sessionQuery.data;
  if (!config || !session) {
    return <LoadingScreen title="正在载入控制台" description="我们在拉取当前会话和前端配置。" />;
  }

  return (
    <UiShellProvider value={{ config, session }}>
      <AppShell session={session} config={config}>
        <Outlet />
      </AppShell>
    </UiShellProvider>
  );
}

function AdminOnly({ children }: { children: ReactNode }) {
  const { session } = useUiShell();

  if (session.role !== "admin") {
    return <ForbiddenPage />;
  }

  return <>{children}</>;
}

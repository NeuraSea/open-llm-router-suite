import { type QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  Outlet,
  redirect,
} from '@tanstack/react-router'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { TanStackRouterDevtools } from '@tanstack/react-router-devtools'
import { useSystemConfig } from '@/hooks/use-system-config'
import { getSelf, getStatus } from '@/lib/api'
import { useAuthStore } from '@/stores/auth-store'
import { Toaster } from '@/components/ui/sonner'
import { NavigationProgress } from '@/components/navigation-progress'
import { GeneralError } from '@/features/errors/general-error'
import { NotFoundError } from '@/features/errors/not-found-error'
import { getSetupStatus } from '@/features/setup/api'

function RootComponent() {
  // Load system configuration (logo, system name, etc.) from backend
  useSystemConfig({ autoLoad: true })

  return (
    <>
      <NavigationProgress />
      <Outlet />
      <Toaster duration={5000} />
      {import.meta.env.MODE === 'development' && (
        <>
          <ReactQueryDevtools buttonPosition='bottom-left' />
          <TanStackRouterDevtools position='bottom-right' />
        </>
      )}
    </>
  )
}

// 缓存 setup 状态检查结果，避免每次导航都重复调用 API
// 使用 localStorage 持久化，避免页面刷新后重复检查
const SETUP_CHECKED_KEY = 'setup_status_checked'

function getSetupStatusFromCache(): boolean {
  try {
    if (typeof window !== 'undefined') {
      return window.localStorage.getItem(SETUP_CHECKED_KEY) === 'true'
    }
  } catch {
    /* empty */
  }
  return false
}

function setSetupStatusCache(value: boolean): void {
  try {
    if (typeof window !== 'undefined') {
      if (value) {
        window.localStorage.setItem(SETUP_CHECKED_KEY, 'true')
      } else {
        window.localStorage.removeItem(SETUP_CHECKED_KEY)
      }
    }
  } catch {
    /* empty */
  }
}

// 内存中的标记，避免同一会话中重复检查
let setupStatusChecked = getSetupStatusFromCache()
let routerSSOChecked = false

function cachedRouterSSOEnabled(): boolean {
  try {
    if (typeof window === 'undefined') return false
    const saved = window.localStorage.getItem('status')
    if (!saved) return false
    const status = JSON.parse(saved)
    return Boolean(
      status?.router_sso_enabled ?? status?.data?.router_sso_enabled
    )
  } catch {
    return false
  }
}

async function syncRouterSSOUser(): Promise<void> {
  if (routerSSOChecked) return
  const { auth } = useAuthStore.getState()
  if (auth.user) {
    routerSSOChecked = true
    return
  }

  let routerSSOEnabled = cachedRouterSSOEnabled()
  if (!routerSSOEnabled) {
    const status = await getStatus().catch(() => null)
    const statusData = status as {
      router_sso_enabled?: boolean
      data?: { router_sso_enabled?: boolean }
    } | null
    routerSSOEnabled = Boolean(
      statusData?.router_sso_enabled ?? statusData?.data?.router_sso_enabled
    )
  }
  if (!routerSSOEnabled) {
    routerSSOChecked = true
    return
  }

  const self = await getSelf().catch(() => null)
  if (self?.success && self.data) {
    auth.setUser(self.data)
  }
  routerSSOChecked = true
}

export const Route = createRootRouteWithContext<{
  queryClient: QueryClient
}>()({
  // 应用初始化与路由解析前统一校验会话
  beforeLoad: async ({ location }) => {
    const pathname = location?.pathname || ''
    const needsSetupCheck =
      !setupStatusChecked && !pathname.startsWith('/setup')

    // 用户信息已通过 auth-store 从 localStorage 恢复
    // 如果 auth.user 存在，说明用户已登录（有缓存的用户数据）
    // 如果 auth.user 为 null，说明用户未登录，直接让 _authenticated 路由处理重定向
    // 不再调用 getSelf() API，避免不必要的网络请求和等待

    // 只检查 setup 状态（如果需要）
    if (needsSetupCheck) {
      const status = await getSetupStatus().catch((error) => {
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.warn('[root.beforeLoad] setup status check failed', error)
        }
        return null
      })

      if (status?.success && status.data && !status.data.status) {
        throw redirect({ to: '/setup' })
      }
      setupStatusChecked = true
      setSetupStatusCache(true)
    }

    await syncRouterSSOUser()
  },
  component: RootComponent,
  notFoundComponent: NotFoundError,
  errorComponent: GeneralError,
})

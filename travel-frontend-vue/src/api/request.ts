import axios, { type AxiosRequestConfig } from 'axios'
import router from '../router'
import { useUserStore } from '../store/user'
import { toast } from '../components/ui/toast'

export type ApiRequestConfig = AxiosRequestConfig & {
  /** Optional background calls can fail without interrupting the current page. */
  skipErrorMessage?: boolean
}

export interface ApiResult<T = unknown> {
  code: number
  message: string
  data: T
}

const request = axios.create({
  baseURL: '/api',
  timeout: 180000, // 生成行程含联网搜索，放宽超时
  // HttpOnly Cookie 会话：必须携带凭证（同源 Vite 代理下天然同源）
  withCredentials: true,
})

request.interceptors.request.use((config) => {
  // 主凭据是 HttpOnly Cookie；内存 token 仅作联调/脚本兜底
  const memToken = useUserStore().token
  if (memToken) {
    config.headers.Authorization = `Bearer ${memToken}`
  }
  return config
})

request.interceptors.response.use(
  (response) => {
    const res = response.data as ApiResult
    if (res.code !== 200) {
      const cfg = response.config as ApiRequestConfig | undefined
      if (!cfg?.skipErrorMessage) {
        ElMessage.error(res.message || '请求失败')
      }
      return Promise.reject(new Error(res.message || '请求失败'))
    }
    return res as unknown as typeof response
  },
  (error) => {
    // 由具体页面展示更友好的超时说明，避免额外弹出英文 "canceled"。
    if (axios.isCancel(error)) {
      return Promise.reject(error)
    }
    if (error.response?.status === 401) {
      try {
        useUserStore().clearSession()
      } catch {
        localStorage.removeItem('username')
        localStorage.removeItem('role')
      }
      // 携带当前页地址：重新登录后回跳（如正在看的行程详情页）
      const current = router.currentRoute.value
      const redirect = current && current.name !== 'login' && current.fullPath !== '/' ? { redirect: current.fullPath } : {}
      router.push({ name: 'login', query: redirect })
      ElMessage.warning('登录已过期，请重新登录')
      return Promise.reject(error)
    }
    if (!error.config?.skipErrorMessage) {
      const message = error.response?.data?.message || error.message || '网络错误'
      // 离线只读（C2.5）：断网时的写操作给明确提示，不静默失败（用自研 toast，不增 EP 记账）
      const method = String(error.config?.method ?? '').toLowerCase()
      if (!navigator.onLine && method !== 'get') {
        toast.warning('离线状态，编辑需联网')
        return Promise.reject(error)
      }
      ElMessage.error(message)
    }
    return Promise.reject(error)
  }
)

export function requestGet<T>(url: string, config?: ApiRequestConfig): Promise<ApiResult<T>> {
  return request.get<unknown, ApiResult<T>>(url, config)
}

export function requestPost<T>(url: string, data?: unknown, config?: ApiRequestConfig): Promise<ApiResult<T>> {
  return request.post<unknown, ApiResult<T>>(url, data, config)
}

export function requestDelete<T>(url: string, config?: ApiRequestConfig): Promise<ApiResult<T>> {
  return request.delete<unknown, ApiResult<T>>(url, config)
}

export function requestPut<T>(url: string, data?: unknown, config?: ApiRequestConfig): Promise<ApiResult<T>> {
  return request.put<unknown, ApiResult<T>>(url, data, config)
}

export function requestPatch<T>(url: string, data?: unknown, config?: ApiRequestConfig): Promise<ApiResult<T>> {
  return request.patch<unknown, ApiResult<T>>(url, data, config)
}

export default request

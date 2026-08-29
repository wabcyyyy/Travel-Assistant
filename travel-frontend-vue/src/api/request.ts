import axios, { type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'

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
})

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

request.interceptors.response.use(
  (response) => {
    const res = response.data as ApiResult
    if (res.code !== 200) {
      ElMessage.error(res.message || '请求失败')
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
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      router.push({ name: 'login' })
      ElMessage.warning('登录已过期，请重新登录')
      return Promise.reject(error)
    }
    if (!error.config?.skipErrorMessage) {
      const message = error.response?.data?.message || error.message || '网络错误'
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

export function requestPut<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<ApiResult<T>> {
  return request.put<unknown, ApiResult<T>>(url, data, config)
}

export default request

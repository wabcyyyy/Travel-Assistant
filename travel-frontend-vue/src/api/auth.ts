import { requestGet, requestPost } from './request'
import type { LoginResponse, UserInfo } from '../types/itinerary'

/** 认证域：登录/注册/登出/用户信息。主凭据为 HttpOnly Cookie。 */

export function login(data: { username: string; password: string }) {
  return requestPost<LoginResponse>('/auth/login', data)
}

export function register(data: { username: string; password: string; nickname?: string }) {
  return requestPost<void>('/auth/register', data)
}

/** 服务端吊销 JWT（logout）；本地清理仍由 user store 执行。 */
export function logoutApi() {
  return requestPost<void>('/auth/logout')
}

export function getUserInfo() {
  return requestGet<UserInfo>('/user/info')
}

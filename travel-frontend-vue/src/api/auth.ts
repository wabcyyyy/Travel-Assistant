import { requestGet, requestPost } from './request'
import type * as Contracts from '../types/generated/contracts'

/** 认证域：登录/注册/登出/用户信息。主凭据为 HttpOnly Cookie。
 * 请求/响应类型来自契约单一源（app/schemas/business/auth.py 的生成类型）。 */

export function login(data: Contracts.LoginBody) {
  return requestPost<Contracts.LoginData>('/auth/login', data)
}

export function register(data: Contracts.RegisterBody) {
  return requestPost<void>('/auth/register', data)
}

/** 服务端吊销 JWT（logout）；本地清理仍由 user store 执行。 */
export function logoutApi() {
  return requestPost<void>('/auth/logout')
}

export function getUserInfo() {
  return requestGet<Contracts.UserInfoVO>('/user/info')
}

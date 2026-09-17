import { defineStore } from 'pinia'
import { clearUserSnapshots } from '../utils/offlineSnapshots'

interface UserState {
  /** 仅内存中的 token（兼容脚本/联调）；浏览器主凭据是 HttpOnly Cookie */
  token: string
  username: string
  role: string
}

export const useUserStore = defineStore('user', {
  state: (): UserState => ({
    token: '',
    username: localStorage.getItem('username') || '',
    role: localStorage.getItem('role') || '',
  }),
  getters: {
    /** Cookie 会话：以本地是否保存用户展示信息判断「看起来已登录」 */
    isLoggedIn: (s) => Boolean(s.username),
  },
  actions: {
    setToken(token: string) {
      // 不写入 localStorage：HttpOnly Cookie 才是持久凭据，避免 XSS 直接读走
      this.token = token || ''
    },
    setUsername(username: string) {
      this.username = username
      if (username) {
        localStorage.setItem('username', username)
      } else {
        localStorage.removeItem('username')
      }
    },
    setRole(role?: string | null) {
      this.role = role === 'admin' ? 'admin' : ''
      if (this.role) {
        localStorage.setItem('role', this.role)
      } else {
        localStorage.removeItem('role')
      }
    },
    logout() {
      // 离线快照（C2.5）：退出即清本账号私有快照（按 username 隔离，异步尽力而为）
      const name = this.username
      if (name) void clearUserSnapshots(name).catch(() => {})
      this.token = ''
      this.username = ''
      this.role = ''
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      localStorage.removeItem('role')
    },
    /** 401/过期时与拦截器共用：清本地凭证并复位 store。 */
    clearSession() {
      this.logout()
    },
  },
})

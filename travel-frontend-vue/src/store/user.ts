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
    /** 会话过期（401）：只清凭据，**不动**离线快照。 */
    expireSession() {
      this.token = ''
      this.username = ''
      this.role = ''
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      localStorage.removeItem('role')
    },
    logout() {
      // 离线快照（C2.5）：只有**用户主动退出**才清本账号私有快照（按 username 隔离）。
      // 这条必须是主动语义：401 是日常事件（JWT 到期，默认 72h），若在此清库，
      // "令牌一过期就把用户的离线行程快照全抹掉"会让 C2.5 变成数据丢失功能。
      const name = this.username
      if (name) void clearUserSnapshots(name).catch(() => {})
      this.expireSession()
    },
  },
})

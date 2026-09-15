import { reactive } from 'vue'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface ToastItem {
  id: number
  type: ToastType
  message: string
}

// 自研全局提示（v2.6 §19.2，替换 ElMessage）：模块级队列 + AppToastHost 单例渲染。
// 最多同时可见 4 条，超出的挤掉最老一条；定时消散由入队时注册。
const MAX_VISIBLE = 4
const state = reactive<{ items: ToastItem[] }>({ items: [] })
let seq = 0

function dismiss(id: number): void {
  const index = state.items.findIndex((item) => item.id === id)
  if (index >= 0) state.items.splice(index, 1)
}

function show(type: ToastType, message: string, duration = 2600): number {
  const id = ++seq
  state.items.push({ id, type, message })
  if (state.items.length > MAX_VISIBLE) state.items.shift()
  if (duration > 0) window.setTimeout(() => dismiss(id), duration)
  return id
}

export const toast = {
  show,
  success: (message: string, duration?: number) => show('success', message, duration),
  error: (message: string, duration?: number) => show('error', message, duration),
  warning: (message: string, duration?: number) => show('warning', message, duration),
  info: (message: string, duration?: number) => show('info', message, duration),
  dismiss,
  state,
  /** 测试辅助：清空队列（生产代码不应调用） */
  resetForTests: (): void => {
    state.items.splice(0)
  },
}

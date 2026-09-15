import { reactive } from 'vue'

export interface ConfirmState {
  open: boolean
  title: string
  message: string
  confirmText: string
  cancelText: string
}

// 自研确认对话框服务（v2.6 §19.2，替换 ElMessageBox.confirm）：
// 模块级单例状态 + AppConfirmHost 渲染；调用方 `await confirmDialog('确认删除？')` 拿布尔结果。
const state = reactive<ConfirmState>({
  open: false,
  title: '确认操作',
  message: '',
  confirmText: '确认',
  cancelText: '取消',
})

let resolveCurrent: ((value: boolean) => void) | null = null

function settle(value: boolean): void {
  state.open = false
  const resolve = resolveCurrent
  resolveCurrent = null
  resolve?.(value)
}

export function confirmDialog(
  message: string,
  options: { title?: string; confirmText?: string; cancelText?: string } = {},
): Promise<boolean> {
  // 同一时刻只保留一个确认框：旧的在开状态下再次调用视为确认前一个（罕见路径，保守处理）
  if (resolveCurrent) settle(false)
  state.title = options.title ?? '确认操作'
  state.message = message
  state.confirmText = options.confirmText ?? '确认'
  state.cancelText = options.cancelText ?? '取消'
  state.open = true
  return new Promise<boolean>((resolve) => {
    resolveCurrent = resolve
  })
}

export const confirmService = {
  state,
  confirm: (): void => settle(true),
  cancel: (): void => settle(false),
  /** 测试辅助：强制重置（生产代码不应调用） */
  resetForTests: (): void => {
    state.open = false
    resolveCurrent = null
  },
}

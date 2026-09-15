import { nextTick, onBeforeUnmount, watch, type Ref } from 'vue'

/**
 * 模态面板的公共行为（AppDialog / AppSheet 共用）：
 * 焦点管理（打开聚焦首个可聚焦元素、Tab 圈定在面板内、关闭还原焦点）、
 * Esc 关闭、打开期间锁背景滚动。z 层叠与外观不在本文件职责内（组件消费令牌）。
 */
export function useModalA11y(options: {
  open: Ref<boolean>
  panel: Ref<HTMLElement | null>
  onClose: () => void
}): void {
  const FOCUSABLE =
    'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
  let lastActive: HTMLElement | null = null
  let prevOverflow = ''

  function focusables(): HTMLElement[] {
    if (!options.panel.value) return []
    return Array.from(options.panel.value.querySelectorAll<HTMLElement>(FOCUSABLE))
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.stopPropagation()
      options.onClose()
      return
    }
    if (event.key !== 'Tab' || !options.panel.value) return
    const items = focusables()
    if (!items.length) {
      event.preventDefault()
      options.panel.value.focus()
      return
    }
    const first = items[0]
    const last = items[items.length - 1]
    const active = document.activeElement as HTMLElement | null
    if (event.shiftKey && (active === first || !options.panel.value.contains(active))) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && active === last) {
      event.preventDefault()
      first.focus()
    }
  }

  watch(
    options.open,
    async (isOpen) => {
      if (isOpen) {
        lastActive = document.activeElement as HTMLElement | null
        prevOverflow = document.body.style.overflow
        document.body.style.overflow = 'hidden'
        document.addEventListener('keydown', onKeydown, true)
        await nextTick()
        ;(focusables()[0] ?? options.panel.value)?.focus()
      } else {
        document.removeEventListener('keydown', onKeydown, true)
        document.body.style.overflow = prevOverflow
        lastActive?.focus?.()
        lastActive = null
      }
    },
    { immediate: true },
  )

  onBeforeUnmount(() => {
    document.removeEventListener('keydown', onKeydown, true)
    document.body.style.overflow = prevOverflow
  })
}

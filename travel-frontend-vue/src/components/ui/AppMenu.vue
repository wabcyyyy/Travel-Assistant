<template>
  <div ref="root" class="app-menu">
    <button
      ref="trigger"
      type="button"
      class="menu-trigger"
      :aria-expanded="open ? 'true' : 'false'"
      aria-haspopup="menu"
      :aria-label="triggerLabel"
      @click="toggle"
    >
      <slot name="trigger"><Ellipsis :size="18" /></slot>
    </button>
    <Transition name="lp-menu">
      <div
        v-if="open"
        ref="list"
        class="menu-list"
        :class="align === 'start' ? 'is-start' : 'is-end'"
        role="menu"
        @keydown="onListKeydown"
      >
        <template v-for="item in items" :key="item.key">
          <div v-if="item.divided" class="menu-divider" role="separator" />
          <button
            type="button"
            role="menuitem"
            class="menu-item"
            :class="{ 'is-danger': item.danger }"
            :disabled="item.disabled"
            @click="onSelect(item)"
          >
            {{ item.label }}
          </button>
        </template>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Ellipsis } from 'lucide-vue-next'

// 自研下拉菜单（v2.6 §19.2，替换 el-dropdown）：触发器 + 菜单项，键盘可达
// （打开聚焦首项、↑↓ 循环、Home/End、Esc 关闭并还原焦点、点击外部关闭）。
// 用于行操作菜单与选择态批量条；菜单项数据经 items 传入，选中的 key 经 select 事件抛出。
withDefaults(
  defineProps<{
    items: {
      key: string
      label: string
      danger?: boolean
      disabled?: boolean
      divided?: boolean
    }[]
    align?: 'start' | 'end'
    triggerLabel?: string
  }>(),
  { align: 'end', triggerLabel: '更多操作' },
)
const emit = defineEmits<{ select: [key: string] }>()

const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const list = ref<HTMLElement | null>(null)
const open = ref(false)

function itemButtons(): HTMLButtonElement[] {
  if (!list.value) return []
  return Array.from(list.value.querySelectorAll<HTMLButtonElement>('.menu-item:not(:disabled)'))
}

function toggle(): void {
  open.value = !open.value
}

function close(restoreFocus = false): void {
  open.value = false
  if (restoreFocus) trigger.value?.focus()
}

function onSelect(item: { key: string; disabled?: boolean }): void {
  if (item.disabled) return
  emit('select', item.key)
  close()
}

function onListKeydown(event: KeyboardEvent): void {
  const buttons = itemButtons()
  if (!buttons.length) return
  const active = document.activeElement as HTMLElement | null
  const index = buttons.findIndex((b) => b === active)
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    buttons[(index + 1 + buttons.length) % buttons.length].focus()
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    buttons[(index - 1 + buttons.length) % buttons.length].focus()
  } else if (event.key === 'Home') {
    event.preventDefault()
    buttons[0].focus()
  } else if (event.key === 'End') {
    event.preventDefault()
    buttons[buttons.length - 1].focus()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    close(true)
  } else if (event.key === 'Tab') {
    close()
  }
}

function onDocumentPointerdown(event: PointerEvent): void {
  if (root.value && !root.value.contains(event.target as Node)) close()
}

watch(open, async (isOpen) => {
  if (isOpen) {
    document.addEventListener('pointerdown', onDocumentPointerdown)
    await nextTick()
    itemButtons()[0]?.focus()
  } else {
    document.removeEventListener('pointerdown', onDocumentPointerdown)
  }
})

onBeforeUnmount(() => document.removeEventListener('pointerdown', onDocumentPointerdown))
</script>

<style scoped>
.app-menu {
  position: relative;
  display: inline-flex;
}

.menu-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: none;
  border-radius: var(--lp-radius-xs);
  background: transparent;
  color: var(--lp-text-muted);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.menu-trigger:hover,
.menu-trigger[aria-expanded='true'] {
  background: var(--lp-surface-hover);
  color: var(--lp-text-1);
}

.menu-list {
  position: absolute;
  top: calc(100% + 6px);
  z-index: var(--lp-z-panel);
  min-width: 160px;
  padding: var(--lp-space-1);
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-sm);
  background: var(--lp-surface-elevated);
  box-shadow: var(--lp-shadow-dropdown);
}

.menu-list.is-end {
  right: 0;
}

.menu-list.is-start {
  left: 0;
}

.menu-divider {
  height: 1px;
  margin: var(--lp-space-1) 0;
  background: var(--lp-edge-faint);
}

.menu-item {
  display: block;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: var(--lp-radius-xs);
  background: transparent;
  color: var(--lp-text-2);
  font-size: 13px;
  font-weight: 500;
  text-align: left;
  white-space: nowrap;
  cursor: pointer;
  transition: background 0.12s ease, color 0.12s ease;
}

.menu-item:hover,
.menu-item:focus-visible {
  background: var(--lp-surface-hover);
  color: var(--lp-text-1);
}

.menu-item.is-danger {
  color: var(--lp-danger);
}

.menu-item.is-danger:hover,
.menu-item.is-danger:focus-visible {
  background: var(--lp-danger-soft);
  color: var(--lp-danger);
}

.menu-item:disabled {
  color: var(--lp-text-faint);
  cursor: default;
}

.menu-item:disabled:hover {
  background: transparent;
}

/* 入场：90ms 淡入 + 轻微下移（reduce 偏好下被全局规则压成瞬时） */
.lp-menu-enter-active,
.lp-menu-leave-active {
  transition: opacity 0.09s ease, transform 0.09s ease;
}

.lp-menu-enter-from,
.lp-menu-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>

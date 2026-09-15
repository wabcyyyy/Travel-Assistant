<template>
  <span ref="root" class="app-popover">
    <span class="pop-anchor" @click="toggle"><slot name="trigger" /></span>
    <Transition name="lp-pop">
      <div
        v-if="open"
        ref="panel"
        class="pop-panel"
        :class="align === 'start' ? 'is-start' : 'is-end'"
        role="dialog"
        :aria-label="label || undefined"
        tabindex="-1"
      >
        <slot />
      </div>
    </Transition>
  </span>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

// 轻量弹出层（v2.6 §19.2，替换 el-popover）：触发器插槽 + 自由内容插槽。
// 非模态（不锁滚动/不圈焦点）：点击外部与 Esc 关闭；打开时聚焦面板内首个 input/button（表单场景友好）。
// 用法：`<AppPopover v-model:open="x"><template #trigger><button/></template>内容</AppPopover>`。
const open = defineModel<boolean>('open', { default: false })
withDefaults(defineProps<{ label?: string; align?: 'start' | 'end' }>(), { label: '', align: 'end' })

const root = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)

function toggle(): void {
  open.value = !open.value
}

function onDocPointerdown(event: PointerEvent): void {
  if (root.value && !root.value.contains(event.target as Node)) open.value = false
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') open.value = false
}

watch(open, async (isOpen) => {
  if (isOpen) {
    document.addEventListener('pointerdown', onDocPointerdown)
    document.addEventListener('keydown', onKeydown)
    await nextTick()
    panel.value?.querySelector<HTMLElement>('input, button, textarea')?.focus()
  } else {
    document.removeEventListener('pointerdown', onDocPointerdown)
    document.removeEventListener('keydown', onKeydown)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocPointerdown)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.app-popover {
  position: relative;
  display: inline-flex;
}

.pop-anchor {
  display: inline-flex;
}

.pop-panel {
  position: absolute;
  top: calc(100% + 6px);
  z-index: var(--lp-z-panel);
  min-width: 200px;
  max-width: min(320px, calc(100vw - 32px));
  padding: var(--lp-space-3);
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-sm);
  background: var(--lp-surface-elevated);
  box-shadow: var(--lp-shadow-dropdown);
  text-align: left;
}

.pop-panel.is-end {
  right: 0;
}

.pop-panel.is-start {
  left: 0;
}

/* 入场：90ms 淡入 + 轻微下移（reduce 偏好下被全局规则压成瞬时） */
.lp-pop-enter-active,
.lp-pop-leave-active {
  transition: opacity 0.09s ease, transform 0.09s ease;
}

.lp-pop-enter-from,
.lp-pop-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>

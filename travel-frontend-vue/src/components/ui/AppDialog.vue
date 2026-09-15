<template>
  <Teleport to="body">
    <Transition name="lp-dialog">
      <div v-if="model" class="dialog-mask" role="presentation" @pointerdown.self="onMask">
        <div
          ref="panel"
          class="dialog-panel"
          role="dialog"
          aria-modal="true"
          :aria-label="title || undefined"
          :style="{ '--dialog-w': width }"
          tabindex="-1"
        >
          <header class="dialog-head">
            <h2 v-if="title" class="dialog-title">{{ title }}</h2>
            <slot name="header" />
            <button type="button" class="dialog-close" aria-label="关闭" @click="close">
              <X :size="18" />
            </button>
          </header>
          <div class="dialog-body"><slot /></div>
          <footer v-if="$slots.footer" class="dialog-foot"><slot name="footer" /></footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { X } from 'lucide-vue-next'

import { useModalA11y } from './useModalA11y'

// 自研对话框（v2.6 §19.2，替换 el-dialog）：Esc/遮罩关闭、焦点圈定、锁背景滚动；
// 外观全走 --lp-* 令牌；z 走 --lp-z-modal。插槽：默认体 / #header（标题同行）/ #footer（操作行）。
const model = defineModel<boolean>({ required: true })
const props = withDefaults(
  defineProps<{
    title?: string
    /** CSS 宽度（默认随内容安全回落） */
    width?: string
    /** 点击遮罩关闭 */
    closeOnMask?: boolean
  }>(),
  { title: '', width: 'min(440px, calc(100vw - 32px))', closeOnMask: true },
)
const emit = defineEmits<{ close: [] }>()

const panel = ref<HTMLElement | null>(null)

function close(): void {
  model.value = false
  emit('close')
}

function onMask(): void {
  if (props.closeOnMask) close()
}

useModalA11y({ open: model, panel, onClose: close })
</script>

<style scoped>
.dialog-mask {
  position: fixed;
  inset: 0;
  z-index: var(--lp-z-modal);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--lp-space-4);
  background: var(--lp-overlay);
}

.dialog-panel {
  width: var(--dialog-w);
  max-height: calc(100vh - 64px);
  display: flex;
  flex-direction: column;
  background: var(--lp-surface-card);
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-card-lg);
  box-shadow: var(--lp-shadow-modal);
  outline: none;
}

.dialog-head {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
  padding: var(--lp-space-4) var(--lp-space-5) var(--lp-space-3);
}

.dialog-title {
  flex: 1;
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--lp-text-1);
}

.dialog-close {
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

.dialog-close:hover {
  background: var(--lp-surface-hover);
  color: var(--lp-text-1);
}

.dialog-body {
  padding: 0 var(--lp-space-5) var(--lp-space-4);
  overflow: auto;
  color: var(--lp-text-2);
  font-size: var(--lp-text-body);
}

.dialog-foot {
  display: flex;
  justify-content: flex-end;
  gap: var(--lp-space-2);
  padding: var(--lp-space-3) var(--lp-space-5) var(--lp-space-4);
}

/* 入场/出场：150ms 淡入 + 上浮（reduce 偏好下被全局规则压成瞬时） */
.lp-dialog-enter-active,
.lp-dialog-leave-active {
  transition: opacity 0.15s ease;
}

.lp-dialog-enter-active .dialog-panel,
.lp-dialog-leave-active .dialog-panel {
  transition: transform 0.15s ease;
}

.lp-dialog-enter-from,
.lp-dialog-leave-to {
  opacity: 0;
}

.lp-dialog-enter-from .dialog-panel,
.lp-dialog-leave-to .dialog-panel {
  transform: translateY(6px) scale(0.99);
}
</style>

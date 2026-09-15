<template>
  <Teleport to="body">
    <Transition name="lp-sheet">
      <div v-if="model" class="sheet-mask" role="presentation" @pointerdown.self="onMask">
        <div
          ref="panel"
          class="sheet-panel"
          :class="direction === 'btt' ? 'is-btt' : 'is-rtl'"
          role="dialog"
          aria-modal="true"
          :aria-label="title || undefined"
          :style="{ '--sheet-size': size }"
          tabindex="-1"
        >
          <header class="sheet-head">
            <h2 v-if="title" class="sheet-title">{{ title }}</h2>
            <slot name="header" />
            <button type="button" class="sheet-close" aria-label="关闭" @click="close">
              <X :size="18" />
            </button>
          </header>
          <div class="sheet-body"><slot /></div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { X } from 'lucide-vue-next'

import { useModalA11y } from './useModalA11y'

// 自研抽屉（v2.6 §19.2，替换 el-drawer）：btt=底部面板（移动端承载侧栏）/ rtl=右侧抽屉。
// 与 AppDialog 同一套模态行为（Esc/遮罩/焦点/锁滚动），外观走 --lp-* 令牌。
const model = defineModel<boolean>({ required: true })
const props = withDefaults(
  defineProps<{
    title?: string
    direction?: 'btt' | 'rtl'
    /** btt 时为 max-height，rtl 时为宽度（CSS 长度/百分比） */
    size?: string
    closeOnMask?: boolean
  }>(),
  { title: '', direction: 'btt', size: '72%', closeOnMask: true },
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
.sheet-mask {
  position: fixed;
  inset: 0;
  z-index: var(--lp-z-modal);
  display: flex;
  background: var(--lp-overlay);
}

.sheet-mask:has(.is-btt) {
  align-items: flex-end;
  justify-content: center;
  padding: var(--lp-space-4) var(--lp-space-3) 0;
}

.sheet-mask:has(.is-rtl) {
  align-items: stretch;
  justify-content: flex-end;
}

.sheet-panel {
  display: flex;
  flex-direction: column;
  background: var(--lp-surface-card);
  box-shadow: var(--lp-shadow-modal);
  outline: none;
}

.sheet-panel.is-btt {
  width: min(640px, 100%);
  max-height: var(--sheet-size);
  border: 1px solid var(--lp-edge-1);
  border-bottom: none;
  border-radius: var(--lp-radius-card-lg) var(--lp-radius-card-lg) 0 0;
}

.sheet-panel.is-rtl {
  width: min(var(--sheet-size), calc(100vw - 48px));
  height: 100%;
  border-left: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-card-lg) 0 0 var(--lp-radius-card-lg);
}

.sheet-head {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
  padding: var(--lp-space-4) var(--lp-space-5) 0;
}

.sheet-title {
  flex: 1;
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--lp-text-1);
}

.sheet-close {
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

.sheet-close:hover {
  background: var(--lp-surface-hover);
  color: var(--lp-text-1);
}

.sheet-body {
  flex: 1;
  min-height: 0;
  padding: var(--lp-space-3) var(--lp-space-5) var(--lp-space-5);
  overflow: auto;
  color: var(--lp-text-2);
  font-size: var(--lp-text-body);
}

/* btt 从下浮入 / rtl 从右滑入（reduce 偏好下被全局规则压成瞬时） */
.lp-sheet-enter-active,
.lp-sheet-leave-active {
  transition: opacity 0.18s ease;
}

.lp-sheet-enter-active .sheet-panel,
.lp-sheet-leave-active .sheet-panel {
  transition: transform 0.18s ease;
}

.lp-sheet-enter-from,
.lp-sheet-leave-to {
  opacity: 0;
}

.lp-sheet-enter-from .is-btt,
.lp-sheet-leave-to .is-btt {
  transform: translateY(24px);
}

.lp-sheet-enter-from .is-rtl,
.lp-sheet-leave-to .is-rtl {
  transform: translateX(24px);
}
</style>

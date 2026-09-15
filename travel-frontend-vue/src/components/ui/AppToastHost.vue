<template>
  <Teleport to="body">
    <div class="toast-host" role="status" aria-live="polite">
      <TransitionGroup name="lp-toast">
        <div
          v-for="item in toast.state.items"
          :key="item.id"
          class="toast-item"
          :class="`tone-${item.type}`"
        >
          <component :is="ICONS[item.type]" :size="16" class="toast-icon" aria-hidden="true" />
          <span class="toast-msg">{{ item.message }}</span>
          <button type="button" class="toast-close" aria-label="关闭提示" @click="toast.dismiss(item.id)">
            <X :size="14" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { CircleAlert, CircleCheck, CircleX, Info, X } from 'lucide-vue-next'

import { toast, type ToastType } from './toast'

// 提示宿主（v2.6 §19.2）：在 App.vue 挂载一次；队列在 toast.ts，任何模块经 toast.success(…) 触发。
const ICONS: Record<ToastType, unknown> = {
  success: CircleCheck,
  error: CircleX,
  warning: CircleAlert,
  info: Info,
}
</script>

<style scoped>
.toast-host {
  position: fixed;
  top: var(--lp-space-4);
  left: 50%;
  transform: translateX(-50%);
  z-index: var(--lp-z-toast);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--lp-space-2);
  pointer-events: none;
}

.toast-item {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
  max-width: min(420px, calc(100vw - 32px));
  padding: 8px 10px 8px 12px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-sm);
  background: var(--lp-surface-elevated);
  box-shadow: var(--lp-shadow-dropdown);
  color: var(--lp-text-1);
  font-size: 13px;
  font-weight: 500;
  pointer-events: auto;
}

.toast-icon {
  flex: none;
}

.tone-success .toast-icon {
  color: var(--lp-success);
}

.tone-error .toast-icon {
  color: var(--lp-danger);
}

.tone-warning .toast-icon {
  color: var(--lp-warning);
}

.tone-info .toast-icon {
  color: var(--lp-accent);
}

.toast-msg {
  flex: 1;
  min-width: 0;
}

.toast-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: var(--lp-radius-xs);
  background: transparent;
  color: var(--lp-text-muted);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.toast-close:hover {
  background: var(--lp-surface-hover);
  color: var(--lp-text-1);
}

/* 入场/离场：上浮淡入（reduce 偏好下被全局规则压成瞬时） */
.lp-toast-enter-active,
.lp-toast-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.lp-toast-enter-from,
.lp-toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.lp-toast-move {
  transition: transform 0.18s ease;
}
</style>

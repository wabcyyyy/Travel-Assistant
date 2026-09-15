<template>
  <AppDialog
    :model-value="confirmService.state.open"
    :title="confirmService.state.title"
    width="min(360px, calc(100vw - 32px))"
    @update:model-value="onUpdate"
  >
    <p class="confirm-msg">{{ confirmService.state.message }}</p>
    <template #footer>
      <button type="button" class="confirm-btn" @click="confirmService.cancel()">
        {{ confirmService.state.cancelText }}
      </button>
      <button type="button" class="confirm-btn is-primary" @click="confirmService.confirm()">
        {{ confirmService.state.confirmText }}
      </button>
    </template>
  </AppDialog>
</template>

<script setup lang="ts">
import AppDialog from './AppDialog.vue'
import { confirmService } from './confirm'

// 确认对话框宿主（v2.6 §19.2）：在 App.vue 挂载一次；任何模块经 confirmDialog() 调用。
// 遮罩/Esc 关闭 = 取消（AppDialog 的既有行为）。
function onUpdate(value: boolean): void {
  if (!value) confirmService.cancel()
}
</script>

<style scoped>
.confirm-msg {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--lp-text-2);
}

.confirm-btn {
  padding: 6px 16px;
  border: 1px solid var(--lp-edge-2);
  border-radius: var(--lp-radius-xs);
  background: var(--lp-surface-card);
  color: var(--lp-text-2);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}

.confirm-btn:hover {
  color: var(--lp-accent);
  border-color: var(--lp-accent);
}

.confirm-btn.is-primary {
  border-color: var(--lp-accent);
  background: var(--lp-accent);
  color: var(--lp-accent-on-fill);
}

.confirm-btn.is-primary:hover {
  background: var(--lp-accent-hover);
  border-color: var(--lp-accent-hover);
  color: var(--lp-accent-on-fill);
}
</style>

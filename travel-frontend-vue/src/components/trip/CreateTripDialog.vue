<template>
  <AppDialog v-model="open" title="新建行程" width="min(920px, calc(100vw - 48px))">
    <div class="create-trip-dialog">
      <CreateTripForm ref="formRef" :prefill-city="ui.createTripCity" @created="onCreated" />
      <footer class="dialog-foot">
        <div class="brief">
          <template v-if="formBrief">
            <span class="brief-city">{{ formBrief.city }}</span>
            <span class="brief-meta">{{ formBrief.summary }}</span>
          </template>
          <span v-else class="brief-empty">选定目的地后，这里会汇总你的行程安排</span>
        </div>
        <div class="foot-actions">
          <button type="button" class="btn-ghost" @click="close">取消</button>
          <button type="button" class="btn-primary" :disabled="submitting" @click="submit">
            {{ submitting ? '生成中…' : '开始生成' }}
          </button>
        </div>
      </footer>
    </div>
  </AppDialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useUiStore } from '../../store/ui'
import AppDialog from '../ui/AppDialog.vue'
import CreateTripForm from './CreateTripForm.vue'

const ui = useUiStore()
const router = useRouter()
const formRef = ref<InstanceType<typeof CreateTripForm> | null>(null)
const submitting = ref(false)

const open = computed({
  get: () => ui.createTripOpen,
  set: (v: boolean) => {
    if (!v) ui.closeCreateTrip()
  },
})

const formBrief = computed(() => formRef.value?.brief ?? null)

function close(): void {
  ui.closeCreateTrip()
}

async function submit(): Promise<void> {
  if (!formRef.value) return
  submitting.value = true
  try {
    await formRef.value.submit()
  } finally {
    submitting.value = false
  }
}

function onCreated(id: string | number): void {
  close()
  router.push({ name: 'trip-detail', params: { id: String(id) } })
}
</script>

<style scoped>
.create-trip-dialog {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.dialog-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--lp-edge-1);
}

.brief {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 6px 12px;
  min-width: 0;
}

.brief-city {
  font-family: var(--lp-font-display);
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--lp-text-1);
}

.brief-meta {
  color: var(--lp-text-2);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.brief-empty {
  color: var(--lp-text-muted);
  font-size: 13px;
}

.foot-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: none;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 0 20px;
  border: none;
  border-radius: var(--lp-radius-sm);
  background: var(--lp-accent);
  color: var(--lp-accent-on-fill);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary:hover:not(:disabled) {
  background: var(--lp-accent-hover);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-ghost {
  min-height: 40px;
  padding: 0 14px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-sm);
  background: transparent;
  color: var(--lp-text-2);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
</style>

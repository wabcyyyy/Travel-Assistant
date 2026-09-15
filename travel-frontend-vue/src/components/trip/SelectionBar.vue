<template>
  <div v-if="selectedIds.length" class="selection-bar" role="toolbar" aria-label="批量操作">
    <span class="sel-count">已选 {{ selectedIds.length }} 项</span>
    <button type="button" class="sel-act" :disabled="busy" @click="openDialog('move')">移动到…</button>
    <button type="button" class="sel-act" :disabled="busy" @click="openDialog('copy')">复制到…</button>
    <button type="button" class="sel-act is-danger" :disabled="busy" @click="onDelete">删除</button>
    <button type="button" class="sel-act is-ghost" @click="emit('clear')">取消</button>

    <AppDialog
      v-model="dialogVisible"
      :title="mode === 'move' ? '批量移动到' : '批量复制到'"
      width="min(380px, calc(100vw - 32px))"
    >
      <div class="day-grid">
        <button
          v-for="d in dayOptions"
          :key="d.dayId"
          type="button"
          class="day-pick"
          :disabled="busy"
          @click="confirmBatch(d.dayId)"
        >
          第 {{ d.dayNo }} 天<template v-if="d.travelDate"> · {{ d.travelDate }}</template>
        </button>
      </div>
      <p v-if="!dayOptions.length" class="bar-hint">行程暂无可用天</p>
    </AppDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'

import { useItineraryStore } from '../../store/itinerary'
import { useItineraryActions } from '../../composables/useItineraryActions'
import type { TripItem } from '../../types/itinerary'
import AppDialog from '../ui/AppDialog.vue'
import { confirmDialog } from '../ui/confirm'
import { toast } from '../ui/toast'

// 选择态批量条（v2.6 §19.3，TREK 式）：勾选 ≥1 项时底部浮出。
// 移动/复制/删除均**循环调用既有单条 API**（不加批量端点）；每项独立 try/catch，
// 失败如实计数（不静默吞）；全部结束后清空选择并 toast 汇总。
const props = defineProps<{ selectedIds: number[] }>()
const emit = defineEmits<{ clear: [] }>()

const store = useItineraryStore()
const { detail } = storeToRefs(store)
const actions = useItineraryActions()

const mode = ref<'move' | 'copy'>('move')
const dialogVisible = ref(false)
const busy = ref(false)

const dayOptions = computed(() => detail.value?.dayList ?? [])

function openDialog(next: 'move' | 'copy'): void {
  mode.value = next
  dialogVisible.value = true
}

function findItems(): { item: TripItem }[] {
  const wanted = new Set(props.selectedIds)
  const found: { item: TripItem }[] = []
  for (const day of detail.value?.dayList ?? []) {
    for (const item of day.items || []) {
      if (item.id != null && wanted.has(item.id)) found.push({ item })
    }
  }
  return found
}

async function confirmBatch(dayId: number): Promise<void> {
  if (busy.value) return
  busy.value = true
  const entries = findItems()
  let failed = 0
  for (const { item } of entries) {
    try {
      if (mode.value === 'move') {
        await actions.moveToDay(item.id!, dayId)
      } else {
        // 复制到：位置属性随行；时间字段是当天排序语义，不随复制
        await actions.addItem(detail.value!.id, {
          dayId,
          itemType: item.itemType,
          poiName: item.poiName,
          poiId: item.poiId,
          address: item.address,
          latitude: item.latitude,
          longitude: item.longitude,
          cost: item.cost ?? undefined,
          tag: item.tag || undefined,
          remark: item.remark || undefined,
        })
      }
    } catch {
      failed += 1
    }
  }
  busy.value = false
  dialogVisible.value = false
  const done = entries.length - failed
  if (failed > 0) toast.warning(`完成 ${done} 项，${failed} 项失败`)
  else toast.success(mode.value === 'move' ? `已移动 ${done} 项` : `已复制 ${done} 项`)
  emit('clear')
}

async function onDelete(): Promise<void> {
  if (busy.value) return
  const ok = await confirmDialog(`确认删除选中的 ${props.selectedIds.length} 项？`, {
    title: '批量删除',
    confirmText: '删除',
  })
  if (!ok) return
  busy.value = true
  const entries = findItems()
  let failed = 0
  for (const { item } of entries) {
    try {
      await actions.deleteItem(item.id!)
    } catch {
      failed += 1
    }
  }
  busy.value = false
  const done = entries.length - failed
  if (failed > 0) toast.warning(`已删除 ${done} 项，${failed} 项失败`)
  else toast.success(`已删除 ${done} 项`)
  emit('clear')
}
</script>

<style scoped>
.selection-bar {
  position: fixed;
  left: 50%;
  bottom: 24px;
  transform: translateX(-50%);
  z-index: var(--lp-z-panel);
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
  padding: 8px 12px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-pill);
  background: var(--lp-surface-elevated);
  box-shadow: var(--lp-shadow-lg);
}

.sel-count {
  padding: 0 4px;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--lp-text-1);
  white-space: nowrap;
}

.sel-act {
  padding: 5px 12px;
  border: 1px solid var(--lp-edge-2);
  border-radius: var(--lp-radius-xs);
  background: var(--lp-surface-card);
  color: var(--lp-text-2);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.sel-act:hover:not(:disabled) {
  color: var(--lp-accent);
  border-color: var(--lp-accent);
}

.sel-act.is-danger:hover:not(:disabled) {
  color: var(--lp-danger);
  border-color: var(--lp-danger);
}

.sel-act.is-ghost {
  border-color: transparent;
}

.sel-act:disabled {
  color: var(--lp-text-faint);
  cursor: default;
}

.day-grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lp-space-2);
}

.day-pick {
  padding: 6px 12px;
  border: 1px solid var(--lp-edge-2);
  border-radius: var(--lp-radius-xs);
  background: var(--lp-surface-card);
  color: var(--lp-text-2);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.day-pick:hover:not(:disabled) {
  color: var(--lp-accent);
  border-color: var(--lp-accent);
}

.bar-hint {
  margin: 8px 0 0;
  font-size: 12.5px;
  color: var(--lp-text-muted);
}

@media (max-width: 767px) {
  .selection-bar {
    bottom: 84px;
    max-width: calc(100vw - 16px);
    overflow-x: auto;
  }
}
</style>

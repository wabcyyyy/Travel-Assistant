/**
 * 条目行内联快捷编辑（时间/时长/费用）的状态逻辑（自 DayListCard 提取）。
 *
 * 语义：
- `quickEdit` 同时只开一个编辑器（id+field 定位），打开时预填草稿、关闭时清空；
- 保存走 `actions.updateItem`，载荷与 ItemEditDialog 同口径——后端 PUT 是
  **全量语义**，缺字段会丢坐标（见 baseUpdatePayload）；
- 时间归一：原生 time 输入 HH:mm，后端契约 HH:mm:ss。

用法：`const qe = useQuickEdit({ updateItem: actions.updateItem })`；actions
经参数注入（可测性）。纯 ref/computed，不依赖组件实例（无生命周期钩子），
可在 vitest 直接调用。
*/

import { ref } from 'vue'

import { toast } from '../../ui/toast'
import type { TripItem } from '../../../types/itinerary'

export type QuickEditField = 'time' | 'cost'
export type QuickEditState = { id: number; field: QuickEditField } | null

interface UpdateItemFn {
  (itemId: number, payload: Record<string, unknown>): Promise<unknown>
}

export function baseUpdatePayload(item: TripItem): Record<string, unknown> {
  return {
    itemType: item.itemType,
    poiName: item.poiName,
    poiId: item.poiId,
    address: item.address,
    latitude: item.latitude,
    longitude: item.longitude,
    startTime: item.startTime || undefined,
    endTime: item.endTime,
    durationMin: item.durationMin ?? undefined,
    cost: item.cost ?? undefined,
    tag: item.tag || undefined,
    remark: item.remark || undefined,
  }
}

export function useQuickEdit(actions: { updateItem: UpdateItemFn }) {
  const quickEdit = ref<QuickEditState>(null)
  const timeDraft = ref('')
  const durDraft = ref<number | null>(null)
  const costDraft = ref<number | null>(null)

  /** popover 开关回调：open=false 且是当前编辑器时关闭；open=true 时切到本条并预填 */
  function syncQuick(item: TripItem, field: QuickEditField, open: boolean) {
    if (!open) {
      const current = quickEdit.value
      if (current && current.id === item.id && current.field === field) quickEdit.value = null
      return
    }
    quickEdit.value = { id: item.id!, field }
    if (field === 'time') {
      timeDraft.value = item.startTime ? item.startTime.slice(0, 5) : ''
      durDraft.value = item.durationMin ?? null
    } else {
      costDraft.value = item.cost ?? null
    }
  }

  async function saveTime(item: TripItem) {
    // 原生 time 输入为 HH:mm；后端契约为 HH:mm:ss
    const normalized = timeDraft.value
      ? timeDraft.value.length === 5
        ? `${timeDraft.value}:00`
        : timeDraft.value
      : undefined
    await actions.updateItem(item.id!, {
      ...baseUpdatePayload(item),
      startTime: normalized,
      durationMin: durDraft.value ?? undefined,
    })
    quickEdit.value = null
  }

  async function saveCost(item: TripItem) {
    await actions.updateItem(item.id!, {
      ...baseUpdatePayload(item),
      cost: costDraft.value ?? undefined,
    })
    quickEdit.value = null
    toast.success('费用已更新')
  }

  return { quickEdit, timeDraft, durDraft, costDraft, syncQuick, saveTime, saveCost }
}

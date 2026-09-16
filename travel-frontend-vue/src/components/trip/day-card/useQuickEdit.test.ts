import { describe, expect, it, vi } from 'vitest'

import { baseUpdatePayload, useQuickEdit } from './useQuickEdit'
import type { TripItem } from '../../../types/itinerary'

function item(overrides: Partial<TripItem> = {}): TripItem {
  return {
    id: 7,
    itemType: 'attraction',
    poiName: '西湖',
    startTime: '09:30:00',
    durationMin: 90,
    cost: 40,
    latitude: 30.25,
    longitude: 120.15,
    ...overrides,
  }
}

describe('baseUpdatePayload', () => {
  it('与 ItemEditDialog 同口径：全量字段，缺省值转 undefined（防 PUT 部分更新丢坐标）', () => {
    const payload = baseUpdatePayload(item())
    expect(payload).toMatchObject({
      itemType: 'attraction',
      poiName: '西湖',
      poiId: undefined,
      address: undefined,
      latitude: 30.25,
      longitude: 120.15,
      startTime: '09:30:00',
      endTime: undefined,
      durationMin: 90,
      cost: 40,
      tag: undefined,
      remark: undefined,
    })
  })
})

describe('useQuickEdit', () => {
  function setup() {
    const updateItem = vi.fn().mockResolvedValue(undefined)
    const qe = useQuickEdit({ updateItem })
    return { updateItem, qe }
  }

  it('syncQuick(time, open=true)：定位到本条并预填草稿（HH:mm 截取）', () => {
    const { qe } = setup()
    qe.syncQuick(item(), 'time', true)
    expect(qe.quickEdit.value).toEqual({ id: 7, field: 'time' })
    expect(qe.timeDraft.value).toBe('09:30')
    expect(qe.durDraft.value).toBe(90)
  })

  it('syncQuick(cost, open=true)：预填费用', () => {
    const { qe } = setup()
    qe.syncQuick(item(), 'cost', true)
    expect(qe.quickEdit.value).toEqual({ id: 7, field: 'cost' })
    expect(qe.costDraft.value).toBe(40)
  })

  it('syncQuick(close)：仅当关闭的是当前编辑器时清空（开 A 关 B 不误伤）', () => {
    const { qe } = setup()
    qe.syncQuick(item(), 'time', true)
    // 关的是别的条目 → 不清
    qe.syncQuick(item({ id: 8 }), 'time', false)
    expect(qe.quickEdit.value).not.toBeNull()
    // 关的是同一条 → 清
    qe.syncQuick(item(), 'time', false)
    expect(qe.quickEdit.value).toBeNull()
  })

  it('saveTime：HH:mm → HH:mm:ss 归一 + 全量载荷 + 关闭编辑器', async () => {
    const { updateItem, qe } = setup()
    qe.syncQuick(item(), 'time', true)
    await qe.saveTime(item())
    expect(updateItem).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ startTime: '09:30:00', durationMin: 90, latitude: 30.25 }),
    )
    expect(qe.quickEdit.value).toBeNull()
  })

  it('saveTime：草稿为空 → startTime undefined（清空时间）', async () => {
    const { updateItem, qe } = setup()
    qe.syncQuick(item({ startTime: null, durationMin: null }), 'time', true)
    await qe.saveTime(item())
    expect(updateItem).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ startTime: undefined, durationMin: undefined }),
    )
  })

  it('saveCost：全量载荷 + 只带 cost 增量 + 关闭', async () => {
    const { updateItem, qe } = setup()
    qe.syncQuick(item(), 'cost', true)
    qe.costDraft.value = 55
    await qe.saveCost(item())
    expect(updateItem).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ cost: 55, poiName: '西湖', latitude: 30.25 }),
    )
    expect(qe.quickEdit.value).toBeNull()
  })
})

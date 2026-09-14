/**
 * 行程 store 的 SSE reducer 与乐观写快照用例（P1-4）：
 * - applyStreamEvent：day_start/day_done/complete/error/degraded 的状态机映射，
 *   以及 day_done 只更新摘要、不覆盖点位（点位以详情对账为准）；
 * - beginOp/rollbackOp/commitOp：失败回滚恢复快照并推进 revision。
 */

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// store → api → request 链路会引入 router（import 图含 views/element-plus，单测无需）
vi.mock('../router', () => ({
  default: {
    currentRoute: { value: { path: '/', name: 'home' } },
    push: vi.fn(),
  },
}))

import type { ItineraryDetail } from '../types/itinerary'
import type { ItineraryStreamEvent } from '../types/stream'
import { useItineraryStore } from './itinerary'

function event(type: string, data: Record<string, unknown> = {}, seq = 1): ItineraryStreamEvent {
  return { type, itineraryId: 1, seq, ts: '2026-09-13T00:00:00Z', data }
}

/** reducer 只触达 dayNo/theme/note/items，fixture 用最小形状 + 类型断言。 */
function detailFixture(): ItineraryDetail {
  return {
    id: 1,
    title: '杭州两日',
    city: '杭州',
    days: 2,
    stayNights: 1,
    persons: 1,
    status: 2,
    dayList: [
      { dayNo: 1, theme: '旧主题', note: '旧备注', items: [{ poiName: '西湖' }] },
      { dayNo: 2, theme: '次日主题', note: '次日备注', items: [] },
    ],
    budgetList: [],
  } as unknown as ItineraryDetail
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('applyStreamEvent（生成进度 reducer）', () => {
  it('research_start / day_start 推进相位', () => {
    const store = useItineraryStore()
    store.applyStreamEvent(event('research_start'))
    expect(store.streamState.phase).toBe('researching')
    store.applyStreamEvent(event('day_start', { dayNo: 2 }, 2))
    expect(store.streamState.phase).toBe('day')
    expect(store.streamState.dayNo).toBe(2)
  })

  it('research_done 记录证据条数（非法值置为 undefined，不写成 NaN）', () => {
    const store = useItineraryStore()
    store.applyStreamEvent(event('research_done', { evidenceCount: 12 }))
    expect(store.streamState.evidenceCount).toBe(12)
    store.applyStreamEvent(event('research_done', { evidenceCount: 'oops' }, 2))
    expect(store.streamState.evidenceCount).toBeUndefined()
  })

  it('day_done 只更新已有天的摘要，不覆盖点位，并推进到下一天', () => {
    const store = useItineraryStore()
    store.setDetail(detailFixture())
    store.applyStreamEvent(event('day_done', { dayNo: 1, theme: '新主题', note: '新备注' }))
    const day = store.detail!.dayList[0]
    expect(day.theme).toBe('新主题')
    expect(day.note).toBe('新备注')
    expect(day.items).toHaveLength(1) // 点位以详情对账为准，SSE 不覆盖
    expect(store.streamState.dayNo).toBe(2)
  })

  it('complete 收束相位并记录未成功天', () => {
    const store = useItineraryStore()
    store.applyStreamEvent(event('complete', { degradedDays: [3, '4'] }))
    expect(store.streamState.phase).toBe('complete')
    expect(store.streamState.dayNo).toBeUndefined()
    expect(store.streamState.degradedDays).toEqual([3, 4])
  })

  it('error 置 failed 并透传 retryable/message', () => {
    const store = useItineraryStore()
    store.applyStreamEvent(event('error', { retryable: true, message: '上游超时' }))
    expect(store.streamState.phase).toBe('failed')
    expect(store.streamState.retryable).toBe(true)
    expect(store.streamState.errorMessage).toBe('上游超时')
  })

  it('degraded 追加标记；未知事件类型不改变状态机', () => {
    const store = useItineraryStore()
    store.applyStreamEvent(event('degraded', { scope: 'research', reason: '部分域降级' }))
    expect(store.streamState.degraded).toEqual([{ scope: 'research', reason: '部分域降级' }])
    const snapshot = JSON.stringify(store.streamState)
    store.applyStreamEvent(event('chat_token', { delta: 'x' }, 2))
    expect(JSON.stringify(store.streamState)).toBe(snapshot)
  })
})

describe('乐观写快照（beginOp / rollbackOp / commitOp）', () => {
  it('失败回滚恢复操作前 detail 并推进 revision（不可变更新风格）', () => {
    const store = useItineraryStore()
    store.setDetail(detailFixture())
    const before = store.detail
    const revisionBefore = store.revision
    const opId = store.beginOp('删除点位')
    // 不可变更新：替换对象/数组，而非就地改嵌套字段（快照保存的是 detail 引用）
    store.detail = {
      ...store.detail!,
      dayList: [{ ...store.detail!.dayList[0], items: [] }, store.detail!.dayList[1]],
    }
    expect(store.detail!.dayList[0].items).toHaveLength(0)

    store.rollbackOp(opId)
    expect(store.detail).toBe(before) // 回滚 = 恢复操作前引用
    expect(store.detail!.dayList[0].items).toHaveLength(1)
    expect(store.revision).toBe(revisionBefore + 1)
    expect(store.pendingOps).toHaveLength(0)
  })

  it('成功后出队且保留当前状态', () => {
    const store = useItineraryStore()
    store.setDetail(detailFixture())
    const opId = store.beginOp('改主题')
    store.detail = {
      ...store.detail!,
      dayList: [{ ...store.detail!.dayList[0], theme: '乐观新主题' }, store.detail!.dayList[1]],
    }
    store.commitOp(opId)
    expect(store.pendingOps).toHaveLength(0)
    expect(store.detail!.dayList[0].theme).toBe('乐观新主题')
  })
})

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import ItemFeedbackPanel from './ItemFeedbackPanel.vue'
import { useItineraryStore } from '../../store/itinerary'
import type { ItineraryDetail, TripItem } from '../../types/itinerary'
import type { FeedbackVO } from '../../types/generated/contracts'

const api = vi.hoisted(() => ({ fetchMyFeedback: vi.fn(), submitFeedback: vi.fn(), revokeFeedback: vi.fn() }))
vi.mock('../../api/feedback', () => api)

const item: TripItem = { id: 11, itemType: 'attraction', poiName: '浅草寺', latitude: 35.7148, longitude: 139.7967 }

function mountPanel(itemId: number | null = 11) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useItineraryStore()
  store.setDetail({ id: 1, city: '东京', dayList: [], budgetList: [] } as unknown as ItineraryDetail)
  return mount(ItemFeedbackPanel, { props: { item: itemId ? { ...item, id: itemId } : null } })
}

const wrongRow: FeedbackVO = {
  itemId: 11,
  value: 'wrong',
  reason: 'wrong_location',
  note: '地图上位置不对',
  createdAt: '2026-09-18T10:00:00',
  updatedAt: '2026-09-18T10:00:00',
}

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchMyFeedback.mockResolvedValue({ data: { feedbacks: [] } })
  api.submitFeedback.mockImplementation((_id: number, body: { itemId: number; value: string }) =>
    Promise.resolve({
      data: {
        itemId: body.itemId,
        value: body.value,
        reason: body.value === 'wrong' ? 'wrong_location' : null,
        note: null,
        createdAt: '2026-09-18T10:00:00',
        updatedAt: '2026-09-18T10:00:00',
      },
    }),
  )
  api.revokeFeedback.mockResolvedValue({ data: null })
})

describe('ItemFeedbackPanel（条目对/错反馈入口）', () => {
  it('回显本人已评状态，可改可撤', async () => {
    api.fetchMyFeedback.mockResolvedValue({ data: { feedbacks: [wrongRow] } })
    const w = mountPanel()
    await flushPromises()
    expect(w.find('.fb-state').text()).toBe('已标：错·坐标/位置错')

    await w.findAll('.fb-btn').find((b) => b.text() === '撤销')!.trigger('click')
    await flushPromises()
    expect(api.revokeFeedback).toHaveBeenCalledWith(1, 11)
    // 撤销后回到未评态
    expect(w.find('.fb-state').exists()).toBe(false)

    await w.findAll('.fb-btn').find((b) => b.text() === '错')!.trigger('click')
    expect(w.find('.fb-form').exists()).toBe(true)
  })

  it('标错必选原因：value=wrong 携带 reason/note 提交', async () => {
    const w = mountPanel()
    await flushPromises()
    await w.findAll('.fb-btn').find((b) => b.text() === '错')!.trigger('click')
    // 未选原因禁止提交
    expect(w.find('form .is-primary').attributes('disabled')).toBeDefined()

    await w.findAll('.fb-chip').find((c) => c.text() === '坐标/位置错')!.trigger('click')
    await w.get('.fb-note').setValue('深链搜不到')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(api.submitFeedback).toHaveBeenCalledWith(1, {
      itemId: 11,
      value: 'wrong',
      reason: 'wrong_location',
      note: '深链搜不到',
    })
    expect(w.find('.fb-state').text()).toBe('已标：错·坐标/位置错')
    expect(w.find('.fb-form').exists()).toBe(false)
  })

  it('标对一键直提：value=right 不携带原因', async () => {
    const w = mountPanel()
    await flushPromises()
    await w.findAll('.fb-btn').find((b) => b.text() === '对')!.trigger('click')
    await flushPromises()
    expect(api.submitFeedback).toHaveBeenCalledWith(1, { itemId: 11, value: 'right', reason: null, note: null })
    expect(w.find('.fb-state').text()).toBe('已标：对')
  })

  it('addon 关（404/失败）静默隐藏入口，不弹错不打断', async () => {
    api.fetchMyFeedback.mockRejectedValue(new Error('404'))
    const w = mountPanel()
    await flushPromises()
    expect(w.find('.fb').exists()).toBe(false)
  })

  it('提交失败保持现状可重试；item 为空不渲染', async () => {
    const w = mountPanel()
    await flushPromises()
    api.submitFeedback.mockRejectedValueOnce(new Error('offline'))
    await w.findAll('.fb-btn').find((b) => b.text() === '对')!.trigger('click')
    await flushPromises()
    expect(w.find('.fb-state').exists()).toBe(false)

    const none = mountPanel(null)
    await flushPromises()
    expect(none.find('.fb').exists()).toBe(false)
  })
})

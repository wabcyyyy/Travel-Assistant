import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import PlaceDetailSheet from './PlaceDetailSheet.vue'
import { useItineraryStore } from '../../store/itinerary'
import type { ItineraryDetail, TripItem } from '../../types/itinerary'

// 详情卡挂了条目反馈面板（C3.5）：mock 掉 api，避免单测打真实 HTTP
vi.mock('../../api/feedback', () => ({
  fetchMyFeedback: vi.fn().mockResolvedValue({ data: { feedbacks: [] } }),
  submitFeedback: vi.fn(),
  revokeFeedback: vi.fn(),
}))

function makeItem(overrides: Partial<TripItem> = {}): TripItem {
  return {
    id: 11,
    itemType: 'attraction',
    poiName: '浅草寺',
    address: '2 Chome-3-1 Asakusa, Taito City',
    latitude: 35.7148,
    longitude: 139.7967,
    startTime: '08:00:00',
    endTime: '09:30:00',
    durationMin: 90,
    cost: 0,
    intro: '东京最古老的寺庙',
    whyThis: '清晨人少',
    remark: '带现金买御守',
    ...overrides,
  } as unknown as TripItem
}

function mountSheet(item: TripItem | null, city = '东京') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useItineraryStore()
  store.setDetail({ id: 1, city, dayList: [], budgetList: [] } as unknown as ItineraryDetail)
  return mount(PlaceDetailSheet, { props: { item }, global: { plugins: [pinia] } })
}

describe('PlaceDetailSheet（贴底浮层详情卡）', () => {
  it('渲染名称/类别/地址/坐标/时间/费用与简介', () => {
    const wrapper = mountSheet(makeItem())
    const text = wrapper.text()
    expect(text).toContain('浅草寺')
    expect(text).toContain('景点')
    expect(text).toContain('2 Chome-3-1 Asakusa')
    expect(text).toContain('35.7148, 139.7967')
    expect(text).toContain('时间 08:00 - 09:30')
    expect(text).toContain('约 90 分钟')
    expect(text).toContain('￥0/人')
    expect(text).toContain('东京最古老的寺庙')
  })

  it('item 为空不渲染；无坐标/无费用时如实标注', () => {
    expect(mountSheet(null).find('.place-sheet').exists()).toBe(false)

    const bare = mountSheet(makeItem({ latitude: null, longitude: null, cost: null, startTime: null }))
    expect(bare.find('.coords').exists()).toBe(false)
    expect(bare.text()).toContain('费用 未填')
    expect(bare.text()).toContain('2 Chome-3-1 Asakusa')
    const noAddr = mountSheet(makeItem({ address: null, latitude: null, longitude: null }))
    expect(noAddr.text()).toContain('暂无地址')
  })

  it('操作行抛出 edit/move/delete；外链为高德搜索口径（国内）', async () => {
    const wrapper = mountSheet(makeItem(), '杭州')
    const buttons = wrapper.findAll('.act')
    await buttons[0].trigger('click') // 编辑
    await buttons[1].trigger('click') // 加入其他天
    await buttons[2].trigger('click') // 删除
    expect(wrapper.emitted('edit')).toBeTruthy()
    expect(wrapper.emitted('move')).toBeTruthy()
    expect(wrapper.emitted('delete')).toBeTruthy()

    const link = wrapper.find('a.act')
    expect(link.attributes('href')).toContain('uri.amap.com')
    expect(link.attributes('href')).toContain(encodeURIComponent('杭州 浅草寺'))
  })

  it('Esc 关闭（仅打开时挂监听，卸载后不再响应）', async () => {
    const wrapper = mountSheet(makeItem())
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()
    expect(wrapper.emitted('close')).toHaveLength(1)

    wrapper.unmount()
    expect(() =>
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })),
    ).not.toThrow()
  })
})

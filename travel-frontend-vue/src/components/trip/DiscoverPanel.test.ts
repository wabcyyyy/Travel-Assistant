import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DiscoverPanel from './DiscoverPanel.vue'
import { useItineraryStore } from '../../store/itinerary'
import type { ItineraryDetail } from '../../types/itinerary'

// 本地检索 API 边界替身：断言发现面板发出的检索参数
const pois = vi.hoisted(() => ({ searchLocalPois: vi.fn() }))
vi.mock('../../api/pois', () => ({ searchLocalPois: pois.searchLocalPois }))

// 写操作在 API 边界替换：store 与 useItineraryActions 走真实实现，payload 才可信
const api = vi.hoisted(() => ({
  addItem: vi.fn(),
  updateItem: vi.fn(),
  deleteItem: vi.fn(),
  reorderItems: vi.fn(),
  applyPlans: vi.fn(),
  applyHotelOption: vi.fn(),
}))
vi.mock('../../api/itinerary', () => api)

const DETAIL = {
  id: 97,
  title: '杭州2日游',
  city: '杭州',
  days: 2,
  stayNights: 1,
  persons: 1,
  status: 2,
  totalAmount: 0,
  dayList: [
    { dayId: 101, dayNo: 1, items: [{ id: 11, itemType: 'food', poiName: '楼外楼', address: '孤山路 30 号' }] },
    { dayId: 102, dayNo: 2, items: [] },
  ],
  budgetList: [],
  suggestions: [
    { name: '龙井村', category: 'attraction', intro: '茶山漫步', latitude: 30.22, longitude: 120.12 },
    { name: '楼外楼', category: 'food' }, // 与已排同名 → 未排应剔除
    { name: '某某酒店', category: 'hotel', used: true }, // used → 剔除
  ],
} as unknown as ItineraryDetail

function q<T extends HTMLElement = HTMLElement>(selector: string): T {
  return document.querySelector(selector) as T
}

function qa<T extends HTMLElement = HTMLElement>(selector: string): T[] {
  return Array.from(document.querySelectorAll(selector)) as T[]
}

function buttonByText(text: string): HTMLButtonElement {
  const found = qa<HTMLButtonElement>('button').find((btn) => btn.textContent?.trim().includes(text))
  if (!found) throw new Error(`button not found: ${text}`)
  return found
}

async function mountPanel() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useItineraryStore()
  store.setDetail(DETAIL)
  const wrapper = mount(DiscoverPanel, {
    global: { plugins: [pinia] },
    attachTo: document.body,
  })
  await flushPromises()
  return { wrapper, store }
}

beforeEach(() => {
  pois.searchLocalPois.mockReset()
  Object.values(api).forEach((fn) => fn.mockReset())
  api.addItem.mockResolvedValue({ code: 200, message: 'ok', data: DETAIL })
  document.body.innerHTML = ''
})

describe('DiscoverPanel 计数与过滤', () => {
  it('范围计数：全部 = 已排 + 未排（used/同名被剔除）', async () => {
    await mountPanel()
    const segs = qa('.seg-item').map((el) => el.textContent ?? '')
    expect(segs[0]).toContain('全部')
    expect(segs[0]).toContain('2')
    expect(segs[1]).toContain('未排')
    expect(segs[1]).toContain('1')
    expect(segs[2]).toContain('已排')
    expect(segs[2]).toContain('1')
  })

  it('默认全部：已排卡带 D01 徽、未排卡带 ＋；切「未排」只剩备选', async () => {
    await mountPanel()
    expect(qa('.poi-card')).toHaveLength(2)
    expect(qa('.poi-day')[0].textContent?.trim()).toBe('D01')
    expect(qa('.poi-add')).toHaveLength(1)

    buttonByText('未排').click()
    await nextTick()
    expect(qa('.poi-card')).toHaveLength(1)
    expect(q('.poi-name').textContent).toContain('龙井村')
    expect(qa('.poi-add')).toHaveLength(1)

    buttonByText('已排').click()
    await nextTick()
    expect(qa('.poi-card')).toHaveLength(1)
    expect(qa('.poi-day')).toHaveLength(1)
  })

  it('分类筛选与范围叠加', async () => {
    await mountPanel()
    buttonByText('美食').click()
    await nextTick()
    expect(qa('.poi-card')).toHaveLength(1)
    expect(q('.poi-name').textContent).toContain('楼外楼')
  })

  it('已排卡点击抛出 select（供壳滚动定位）', async () => {
    const { wrapper } = await mountPanel()
    qa<HTMLButtonElement>('.poi-day')[0].click()
    await nextTick()
    const events = wrapper.emitted('select')
    expect(events).toBeTruthy()
    expect((events![0][0] as { id: number }).id).toBe(11)
  })
})

describe('DiscoverPanel 排入', () => {
  it('未排卡「＋」→ 选天 → addItem 带上坐标与 itemType', async () => {
    await mountPanel()
    q<HTMLButtonElement>('.poi-add').click()
    await flushPromises()

    expect(document.body.textContent).toContain('排入某天')
    buttonByText('第 2 天').click()
    await flushPromises()

    expect(api.addItem).toHaveBeenCalledWith(
      97,
      expect.objectContaining({
        dayId: 102,
        itemType: 'attraction',
        poiName: '龙井村',
        latitude: 30.22,
        longitude: 120.12,
      }),
    )
  })
})

describe('DiscoverPanel 检索', () => {
  it('回车触发本地检索，空结果显示覆盖城市；清除恢复浏览', async () => {
    pois.searchLocalPois.mockResolvedValue({
      code: 200,
      message: 'ok',
      data: { items: [], coveredCities: [{ city: '杭州', count: 5 }, { city: '北京', count: 25 }] },
    })
    await mountPanel()

    // AppInput 将透传属性绑到内部 input 上（inheritAttrs:false），class 即落在 input
    const input = q<HTMLInputElement>('.panel-search')
    input.value = '千恋万花'
    input.dispatchEvent(new Event('input'))
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await flushPromises()

    expect(pois.searchLocalPois).toHaveBeenCalledWith('杭州', '千恋万花')
    const text = document.body.textContent ?? ''
    expect(text).toContain('没有匹配的地点')
    expect(text).toContain('杭州')
    expect(text).toContain('北京')

    buttonByText('清除').click()
    await nextTick()
    expect(qa('.poi-card')).toHaveLength(2)
  })
})

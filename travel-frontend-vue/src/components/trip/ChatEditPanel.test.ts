import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ChatEditPanel from './ChatEditPanel.vue'
import { useItineraryStore } from '../../store/itinerary'
import type { ItineraryDetail } from '../../types/itinerary'

/**
 * 编辑链"无钉子天"提示（审查 P2-1 最小实现）。
 *
 * 编辑链新增项直接落库、不过接地链（`chat_draft/document.py` 的字段白名单不接收
 * latitude/source/verification），草稿卡必须把这件事说出来——否则用户点完才发现
 * 地图上没点、事实没标签。本测钉两条：新增的无坐标项 → 出提示；只改既有项 → 不出。
 */

const api = vi.hoisted(() => ({
  generateChatEdit: vi.fn(),
  getItineraryChatHistory: vi.fn(),
  applyPlans: vi.fn(),
  applyHotelOption: vi.fn(),
}))
vi.mock('../../api/itinerary', () => api)

const DETAIL = {
  id: 42,
  title: '杭州2日游',
  city: '杭州',
  days: 2,
  dayList: [
    {
      dayId: 1,
      dayNo: 1,
      theme: '西湖线',
      items: [{ id: 11, itemType: 'attraction', poiName: '西湖', latitude: 30.24, longitude: 120.15 }],
    },
    { dayId: 2, dayNo: 2, theme: '灵隐线', items: [] },
  ],
} as unknown as ItineraryDetail

/** 一条 ai 消息带 plans 草稿：`items` 用编辑链契约的 snake_case。 */
function draftMessage(items: Array<Record<string, unknown>>) {
  return {
    id: 1,
    role: 'ai',
    content: '已按你的要求调整',
    plans: [{ day_no: 1, items }],
  }
}

async function mountPanel(message: Record<string, unknown>) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useItineraryStore()
  store.setDetail(DETAIL)
  // 组件挂载即拉历史（watch.immediate）并**用历史覆盖 chatMsgs**：消息必须从
  // API 边界喂进去，直接写 store 会被这次拉取冲掉。
  api.getItineraryChatHistory.mockResolvedValue({ data: [message] })
  const wrapper = mount(ChatEditPanel, {
    props: { itineraryId: 42 },
    global: { plugins: [pinia], stubs: { HotelOptionsDialog: true, ElButton: true } },
  })
  await flushPromises()
  await wrapper.vm.$nextTick()
  return wrapper
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset())
  api.getItineraryChatHistory.mockResolvedValue({ data: [] })
})

describe('ChatEditPanel 草稿卡的新增项提示', () => {
  it('新增的无坐标点位 → 提示"尚未核实、可能没有坐标"', async () => {
    const wrapper = await mountPanel(
      draftMessage([
        { poi_name: '西湖' }, // 既有项（有坐标）
        { poi_name: '某家新咖啡店', cost: 45 }, // 新增且无坐标
      ]),
    )
    const note = wrapper.find('.draft-unverified-note')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('尚未核实')
    expect(note.text()).toContain('坐标')
  })

  it('只改既有项（无新增）→ 不出提示', async () => {
    const wrapper = await mountPanel(draftMessage([{ poi_name: '西湖' }]))
    expect(wrapper.find('.draft-unverified-note').exists()).toBe(false)
  })

  it('新增项自带坐标（如酒店候选卡）→ 不出提示', async () => {
    const wrapper = await mountPanel(
      draftMessage([
        { poi_name: '西湖' },
        { poi_name: '杭州西子湖四季酒店', latitude: 30.25, longitude: 120.13 },
      ]),
    )
    expect(wrapper.find('.draft-unverified-note').exists()).toBe(false)
  })
})
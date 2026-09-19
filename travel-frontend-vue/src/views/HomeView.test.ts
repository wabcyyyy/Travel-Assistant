import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import HomeView from './HomeView.vue'
import type { ItinerarySummary } from '../types/itinerary'

// HomeView 行操作/加载依赖的 API：listItineraries（过滤视图端点，R5-5）。
const api = vi.hoisted(() => ({
  listItineraries: vi.fn(),
  getItineraryDetail: vi.fn(),
}))
vi.mock('../api', async () => {
  // vi.importActual 带类型；ESM 命名空间没有 default，不能靠 `.default` 取真身
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, listItineraries: api.listItineraries, getItineraryDetail: api.getItineraryDetail }
})

// 图鉴统计走 mock（返回 null → tile 占位），避免真实 getAtlas 打网络。
vi.mock('../store/atlas', () => ({
  useAtlasStore: () => ({ ensureLoaded: () => Promise.resolve(null) }),
}))

function summary(over: Partial<ItinerarySummary> & { id: number; title: string }): ItinerarySummary {
  return {
    city: '杭州',
    days: 2,
    persons: 2,
    totalAmount: 0,
    status: 2,
    createdAt: '2026-09-01T00:00:00Z',
    ...over,
  }
}

function stubListApi(items: ItinerarySummary[]): void {
  api.listItineraries.mockResolvedValue({ data: items })
  api.getItineraryDetail.mockResolvedValue({ data: null })
}

async function mountHome() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', name: 'home', component: { template: '<div />' } }],
  })
  const wrapper = mount(HomeView, {
    global: {
      plugins: [router, createPinia()],
      stubs: { CoverDialog: true, ShareDialog: true },
    },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  api.listItineraries.mockReset()
  api.getItineraryDetail.mockReset()
})

describe('HomeView 工作台数据口径', () => {
  it('用过滤视图端点 listItineraries 加载（不再打无过滤的 getItineraryList）', async () => {
    stubListApi([summary({ id: 1, title: '活着的行程', endDate: '2099-01-02' })])
    await mountHome()
    expect(api.listItineraries).toHaveBeenCalled()
  })

  it('归档行程被排除出首页：不渲染、不进「即将出发」/统计/最近编辑', async () => {
    stubListApi([
      summary({ id: 10, title: '已归档的坑', endDate: '2099-03-03', archived: true }),
      summary({ id: 11, title: '即将出发·正常', endDate: '2099-04-04', archived: false }),
    ])
    const wrapper = await mountHome()
    const text = wrapper.text()
    // 服务端若（错误地）回传了归档项，工作台也必须把它挡在外面（R5-5 用户可见缺陷回归闸门）
    expect(text).toContain('即将出发·正常')
    expect(text).not.toContain('已归档的坑')
  })
})

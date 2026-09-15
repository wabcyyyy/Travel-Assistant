import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AtlasResponse } from '../types/atlas'
import AtlasView from './AtlasView.vue'

// maplibre 在 happy-dom 里不可用：以最小替身断言「谁在什么时候碰了 map 对象」。
// fire(event) 手动触发 on('style.load') 注册的回调（初始 load 与换肤 setStyle 后同一入口），
// 用来钉住 styleReady 闸门。
const hoisted = vi.hoisted(() => {
  const handlers: Record<string, Array<() => void>> = {}
  const mapApi = {
    addSource: vi.fn(),
    addLayer: vi.fn(),
    getSource: vi.fn(() => undefined),
    getLayer: vi.fn(() => undefined),
    setPaintProperty: vi.fn(),
    setFilter: vi.fn(),
    jumpTo: vi.fn(),
    flyTo: vi.fn(),
    fitBounds: vi.fn(),
    addControl: vi.fn(),
    remove: vi.fn(),
    off: vi.fn(),
    getZoom: () => 3,
    getCanvas: () => ({ style: {} }),
    on: (event: string, cb: () => void) => {
      ;(handlers[event] ??= []).push(cb)
    },
    once: (event: string, cb: () => void) => {
      ;(handlers[event] ??= []).push(cb)
    },
  }
  const fire = (event: string) => {
    const queued = handlers[event] ?? []
    handlers[event] = []
    queued.forEach((cb) => cb())
  }
  return { handlers, mapApi, fire }
})

vi.mock('maplibre-gl', () => ({
  Map: class {
    constructor() {
      return hoisted.mapApi
    }
  },
  LngLatBounds: class {
    extend() {}
  },
  ScaleControl: class {},
  AttributionControl: class {},
  setWorkerUrl: vi.fn(),
}))

const api = vi.hoisted(() => ({ getAtlas: vi.fn() }))
vi.mock('../api/atlas', () => ({ getAtlas: api.getAtlas }))

const ATLAS: AtlasResponse = {
  scope: 'all',
  stats: { cityCount: 1, countryCount: 1, tripCount: 1, plannedTripCount: 1, visitedTripCount: 0 },
  coverage: { tripsTotal: 1, pinsRendered: 1, itemsWithoutCoord: 0, dictMiss: 0 },
  highlightCountryCodes: ['CN'],
  unknownCities: [],
  pins: [
    {
      city: '杭州',
      country: '中国',
      countryCode: 'CN',
      lat: 30.25,
      lng: 120.16,
      coordSource: 'items',
      tripCount: 1,
      trips: [
        {
          id: 97,
          title: '杭州1日游',
          startDate: null,
          endDate: null,
          status: 2,
          scope: 'planned',
          coverUrl: null,
          city: '杭州',
        },
      ],
    },
  ],
}

const EMPTY: AtlasResponse = {
  ...ATLAS,
  scope: 'visited',
  stats: { cityCount: 0, countryCount: 0, tripCount: 0, plannedTripCount: 0, visitedTripCount: 0 },
  coverage: { tripsTotal: 0, pinsRendered: 0, itemsWithoutCoord: 0, dictMiss: 0 },
  highlightCountryCodes: [],
  pins: [],
}

const EMPTY_ALL: AtlasResponse = { ...EMPTY, scope: 'all' }

function stubMatchMedia(narrow: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: query.includes('max-width: 767px') ? narrow : false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    onchange: null,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

async function mountAtlas(narrow: boolean, payload: AtlasResponse = ATLAS) {
  stubMatchMedia(narrow)
  api.getAtlas.mockResolvedValue({ data: payload })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
  const wrapper = mount(AtlasView, { global: { plugins: [router] } })
  await flushPromises()
  await nextTick()
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  hoisted.handlers && Object.keys(hoisted.handlers).forEach((key) => delete hoisted.handlers[key])
  Object.values(hoisted.mapApi).forEach((fn) => {
    if (typeof fn === 'function' && 'mockClear' in fn) (fn as unknown as { mockClear: () => void }).mockClear()
  })
  api.getAtlas.mockReset()
  // ensureCountries 的本地 geojson：不真发请求
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve({ json: () => Promise.resolve({ type: 'FeatureCollection', features: [] }) }),
    ),
  )
})

describe('AtlasView 布局分支', () => {
  it('≥768px：常驻侧栏直接渲染，不出现城市列表按钮', async () => {
    const wrapper = await mountAtlas(false)
    expect(wrapper.find('.sidebar').exists()).toBe(true)
    expect(wrapper.find('.sidebar').text()).toContain('杭州')
    expect(wrapper.find('.sheet-btn').exists()).toBe(false)
  })

  it('<768px：侧栏转底部面板入口，不渲染常驻侧栏', async () => {
    const wrapper = await mountAtlas(true)
    expect(wrapper.find('.sidebar').exists()).toBe(false)
    expect(wrapper.find('.sheet-btn').text()).toContain('城市列表（1）')
  })

  it('空范围：渲染口径专属空态，不出图不出侧栏', async () => {
    const wrapper = await mountAtlas(false, EMPTY_ALL)
    expect(wrapper.text()).toContain('还没有旅程记录')
    expect(wrapper.find('.sidebar').exists()).toBe(false)
    expect(hoisted.mapApi.addSource).not.toHaveBeenCalled()
  })

  it('切到「去过」为空：换成口径专属文案（不是「从零开始」那套）', async () => {
    const wrapper = await mountAtlas(false, ATLAS)
    api.getAtlas.mockResolvedValue({ data: EMPTY })
    const visited = wrapper.findAll('.scope-pill').find((pill) => pill.text() === '去过')
    await visited?.trigger('click')
    await flushPromises()
    expect(api.getAtlas).toHaveBeenLastCalledWith('visited')
    expect(wrapper.text()).toContain('没有「去过」的行程')
  })
})

describe('AtlasView 地图时序', () => {
  it('样式 load 之前不碰图层源（"Style is not done loading" 回归闸门）', async () => {
    await mountAtlas(false)
    // 数据 watcher 与 immediate watcher 都已跑过，但样式未就绪 → 一次 addSource 都不许有
    expect(hoisted.mapApi.addSource).not.toHaveBeenCalled()

    hoisted.fire('style.load')
    await flushPromises()

    const sources = hoisted.mapApi.addSource.mock.calls.map((call) => call[0])
    expect(sources).toContain('countries')
    expect(sources).toContain('cities')
    expect(hoisted.mapApi.addLayer).toHaveBeenCalled()
  })
})

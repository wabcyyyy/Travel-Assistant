import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import ButlerStrip from './ButlerStrip.vue'
import type { StreamState } from '../../store/itinerary'
import type { ItineraryDetail } from '../../types/itinerary'
import type { WeatherVO } from '../../types/generated/contracts'

// 天气展示（C3.1/Y5）：ButlerStrip chip + HeadStatusPanel 逐日。天气属增强信息：
// 成功渲染、daily=null 静默隐藏、请求失败同样静默且不出现任何错误 UI。
const api = vi.hoisted(() => ({ fetchItineraryWeather: vi.fn() }))
vi.mock('../../api/weather', () => api)

const detail = { id: 7, city: '杭州', status: 2, days: 2, dayList: [], budgetList: [], planNote: '' } as unknown as ItineraryDetail
const streamState: StreamState = { phase: 'complete', degraded: [], degradedDays: [], fallbackMode: false }

const dailyRow = { code: 0, text: '晴', precipProb: 10 }
const weatherData: WeatherVO = {
  city: '杭州',
  source: 'open-meteo',
  daily: [
    { date: '2026-09-18', ...dailyRow, tMax: 30.6, tMin: 22.4 },
    { date: '2026-09-19', code: 3, text: '阴', tMax: 28, tMin: 21, precipProb: 40 },
  ],
}

function mountStrip() {
  return mount(ButlerStrip, { props: { detail, doneDays: 0, streamState } })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ButlerStrip 天气', () => {
  it('取数成功：chip 显示日期/天气/温度区间，展开体渲染逐日', async () => {
    api.fetchItineraryWeather.mockResolvedValue({ data: weatherData })
    const w = mountStrip()
    await flushPromises()
    expect(api.fetchItineraryWeather).toHaveBeenCalledWith(7)
    const chip = w.get('.weather-chip')
    expect(chip.text()).toContain('9/18 晴')
    expect(chip.text()).toContain('22~31°C')
    await w.findAll('button').find((b) => b.text() === '展开')!.trigger('click')
    const days = w.findAll('.weather-day')
    expect(days).toHaveLength(2)
    expect(days[1]!.text()).toContain('9/19 阴')
    expect(days[1]!.text()).toContain('21~28°C')
  })

  it('daily=null：不渲染 chip 与逐日（静默隐藏）', async () => {
    api.fetchItineraryWeather.mockResolvedValue({ data: { city: '杭州', source: 'open-meteo', daily: null } })
    const w = mountStrip()
    await flushPromises()
    expect(w.find('.weather-chip').exists()).toBe(false)
    await w.findAll('button').find((b) => b.text() === '展开')!.trigger('click')
    expect(w.find('.weather-days').exists()).toBe(false)
  })

  it('取数失败：同 null 静默，不出现任何错误 UI', async () => {
    api.fetchItineraryWeather.mockRejectedValueOnce(new Error('offline'))
    const w = mountStrip()
    await flushPromises()
    expect(w.find('.weather-chip').exists()).toBe(false)
    await w.findAll('button').find((b) => b.text() === '展开')!.trigger('click')
    expect(w.find('.weather-days').exists()).toBe(false)
    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(w.text()).not.toContain('失败')
    expect(w.text()).not.toContain('错误')
  })
})

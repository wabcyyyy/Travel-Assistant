import { describe, expect, it, vi, beforeEach } from 'vitest'

// 天气接口口径（Y5）：skipErrorMessage 必须透传给 request 层（静默承诺的落地），
// URL 为 /itinerary/{id}/weather。
const { requestGet } = vi.hoisted(() => ({ requestGet: vi.fn() }))
vi.mock('./request', () => ({ requestGet }))

import { fetchItineraryWeather } from './weather'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('fetchItineraryWeather', () => {
  it('URL 与 skipErrorMessage 透传', async () => {
    const payload = { data: { city: '杭州', source: 'open-meteo', daily: null } }
    requestGet.mockResolvedValue(payload)
    const res = await fetchItineraryWeather(9)
    expect(requestGet).toHaveBeenCalledWith('/itinerary/9/weather', { skipErrorMessage: true })
    expect(res).toBe(payload)
  })
})

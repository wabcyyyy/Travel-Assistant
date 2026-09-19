import { getSupportedCities } from '../api/itinerary'

/**
 * 受支持目的地城市清单（R5-6）：单一来源是后端 `GET /api/itinerary/supported-cities`
 * （city_geo 字典全量），进程内拉一次即缓存，不再各处硬编码。
 *
 * `POPULAR_CITIES_FALLBACK` 只在**离线/接口失败**时兜底展示（非权威、可能过时），
 * 与 utils/geo.ts 的国内判定表同属「显式离线兜底」——网络恢复后即以接口为准。
 */
export const POPULAR_CITIES_FALLBACK: readonly string[] = ['成都', '杭州', '西安', '重庆', '北京', '上海']

let cached: string[] | null = null

/** 拉取并缓存受支持城市；失败返回兜底且不写缓存（下次调用可重试）。 */
export async function fetchSupportedCities(): Promise<string[]> {
  if (cached) return cached
  try {
    const res = await getSupportedCities()
    const list = Array.isArray(res.data) ? res.data.filter(Boolean) : []
    if (list.length) {
      cached = list
      return cached
    }
  } catch {
    /* 离线：落到兜底，不缓存，允许下次重试 */
  }
  return [...POPULAR_CITIES_FALLBACK]
}

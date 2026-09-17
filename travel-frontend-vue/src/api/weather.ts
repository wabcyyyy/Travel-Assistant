import type { WeatherVO } from '../types/generated/contracts'
import { requestGet } from './request'

/**
 * 行程天气（C3.1）：Open-Meteo 免 key 逐日预报，出发前核实用。
 * 行程窗取不到预报（超出 16 天能力窗/城市无坐标/上游失败）时 daily=null，
 * 调用方应静默隐藏天气区，不打断页面（skipErrorMessage + 空值双保险）。
 */
export function fetchItineraryWeather(itineraryId: number) {
  return requestGet<WeatherVO>(`/itinerary/${itineraryId}/weather`, { skipErrorMessage: true })
}

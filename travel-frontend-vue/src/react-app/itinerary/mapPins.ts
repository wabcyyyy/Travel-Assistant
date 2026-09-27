/** 地图点位的纯派生逻辑（React 详情页地图卡）：建点、估算计数、外链构造。
 * 深链一律先过 shared/map-link 的白名单再进 href——前端只构造两类查询 URL，
 * 与后端 map_link.py 的出口域同一集合。 */
import { safeMapLink } from '../../shared/map-link'
import type { DayPlan } from '../../types/itinerary'

export interface MapPin {
  /** 组件内点位标识：dayNo:items 序号（TripItem 契约无 id 字段） */
  key: string
  dayNo: number
  poiName: string
  latitude: number
  longitude: number
  /** valueKind=estimated：位置是估算的，pin 要带徽章（L6 精神：地图上看得出"这个位置是估的"） */
  estimated: boolean
  startTime: string | null
}

const DAY_PIN_COLORS = ['#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed', '#0d9488', '#db2777']

export function dayPinColor(dayNo: number): string {
  return DAY_PIN_COLORS[(dayNo - 1) % DAY_PIN_COLORS.length]
}

export function buildPins(days: DayPlan[]): MapPin[] {
  const pins: MapPin[] = []
  for (const day of days) {
    day.items.forEach((item, index) => {
      if (item.latitude == null || item.longitude == null) return
      pins.push({
        key: `${day.dayNo}:${index}`,
        dayNo: day.dayNo,
        poiName: item.poiName || '未命名地点',
        latitude: item.latitude,
        longitude: item.longitude,
        estimated: item.valueKind === 'estimated',
        startTime: item.startTime,
      })
    })
  }
  return pins
}

/** 无坐标被隐藏的点位数（地图画不出来，脚注要如实交代）。 */
export function missingCoordCount(days: DayPlan[]): number {
  return days.reduce(
    (sum, day) => sum + day.items.filter((item) => item.latitude == null || item.longitude == null).length,
    0,
  )
}

/** 估算点位数（有坐标的范围内计，与图上徽章口径一致）。 */
export function estimatedPinCount(pins: MapPin[]): number {
  return pins.filter((pin) => pin.estimated).length
}

/** 谷歌 Maps 查询深链（构造后仍过白名单出口，防手滑拼出域外 URL）。 */
export function googleMapsLink(pin: Pick<MapPin, 'latitude' | 'longitude' | 'poiName'>): string {
  return safeMapLink(
    `https://www.google.com/maps/search/?api=1&query=${pin.latitude},${pin.longitude}`,
  )
}

/** 高德标记深链（国内核实主路径）。 */
export function amapLink(pin: Pick<MapPin, 'latitude' | 'longitude' | 'poiName'>): string {
  return safeMapLink(
    `https://uri.amap.com/marker?position=${pin.longitude},${pin.latitude}&name=${encodeURIComponent(pin.poiName)}`,
  )
}

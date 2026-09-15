// 目的地国内/国外判定：用于地图外链选择（国内 uri.amap.com / 海外 Google Maps）、
// 点位图降级（staticmap 仅国内可用）与加点检索（海外城市暂禁用高德）。
// 判定基于内置中国城市/省份集合；未命中且不含中国省份名的城市视为国外。
// 城市/省份表维护入口见 constants/geo.ts（本文件仅保留判定函数导出，调用方 import 路径不变）。

import { DOMESTIC_CITIES, DOMESTIC_PROVINCES } from '../constants/geo'

const CITY_SET = new Set(DOMESTIC_CITIES)
const PROVINCE_SET = new Set(DOMESTIC_PROVINCES)

export function isForeignCity(city: string | null | undefined): boolean {
  const name = (city || '').trim()
  if (!name) return false
  if (CITY_SET.has(name) || PROVINCE_SET.has(name)) return false
  // 形如"云南丽江"：含中国省份名 → 国内
  for (const province of PROVINCE_SET) {
    if (name.includes(province)) return false
  }
  return true
}

/**
 * 点位地图外链（v2.6 W2 统一口径，日卡/详情卡/发现面板共用）：
 * 国内 = 高德搜索（城市+名称关键词）；海外 = Google Maps（有真实坐标优先按坐标打开）。
 */
export function externalMapLink(
  target: { name: string; latitude?: number | null; longitude?: number | null },
  city: string | null | undefined,
): string {
  if (isForeignCity(city)) {
    if (target.latitude != null && target.longitude != null) {
      return `https://www.google.com/maps/search/?api=1&query=${target.latitude},${target.longitude}`
    }
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${city ?? ''}${target.name}`)}`
  }
  return `https://uri.amap.com/search?keyword=${encodeURIComponent(`${city ?? ''}${target.name}`)}`
}

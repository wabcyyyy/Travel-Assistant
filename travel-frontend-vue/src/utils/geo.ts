// 目的地国内/国外判定：国外城市走 Leaflet+OSM 免 key 地图，国内走高德 JSAPI。
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

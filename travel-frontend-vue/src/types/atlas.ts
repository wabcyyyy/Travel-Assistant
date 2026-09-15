/** Atlas 聚合响应（SPEC v2.3 §6.7）：一行程 = 一个 city，不是「逐城足迹」。 */

export interface AtlasTrip {
  id: number
  title: string
  startDate: string | null
  endDate: string | null
  status: number
  scope: 'planned' | 'visited'
  coverUrl: string | null
  city: string
}

export interface AtlasPin {
  city: string
  /** 未归国（字典未命中）时为 null——绝不默认 CN */
  country: string | null
  countryCode: string | null
  lat: number
  lng: number
  coordSource: 'items' | 'geo_fallback'
  tripCount: number
  trips: AtlasTrip[]
}

export interface AtlasStats {
  cityCount: number
  countryCount: number
  tripCount: number
  plannedTripCount: number
  visitedTripCount: number
}

/** 覆盖度是契约字段：UI 必显（海外 0% 坐标是已知事实，不藏） */
export interface AtlasCoverage {
  tripsTotal: number
  pinsRendered: number
  itemsWithoutCoord: number
  dictMiss: number
}

export interface AtlasUnknownCity {
  city: string
  reason: 'no_coordinates' | 'dict_miss'
}

export interface AtlasResponse {
  scope: 'all' | 'planned' | 'visited'
  stats: AtlasStats
  coverage: AtlasCoverage
  highlightCountryCodes: string[]
  unknownCities: AtlasUnknownCity[]
  pins: AtlasPin[]
}

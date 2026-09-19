import { requestGet } from './request'

/** 加点工作台检索：服务端 `services/poi_search.search_local` → OTM 分类池 + 联网补池
 * （AI-NATIVE 数据面）。本地知识库表 `poi_knowledge` 已随 V4 退役，也无外部图商 API。 */

export interface LocalPoi {
  id: number
  name: string
  /** attraction | food | hotel */
  category: string
  address: string | null
  latitude: number | null
  longitude: number | null
  rating: number | null
  tags: string | null
  /** ticket_price 优先，餐饮/住宿回落 avg_cost */
  cost: number | null
  source: string | null
}

export interface LocalPoiCoverage {
  city: string
  count: number
}

export interface LocalPoiResult {
  city: string
  category: string | null
  items: LocalPoi[]
  /** 知识库当前覆盖的城市与点位数：空态如实说明「哪些城有数据」 */
  coveredCities: LocalPoiCoverage[]
}

export function searchLocalPois(city: string, keywords?: string, category?: string) {
  return requestGet<LocalPoiResult>('/pois', {
    params: { city, keywords: keywords || undefined, category: category || undefined },
  })
}

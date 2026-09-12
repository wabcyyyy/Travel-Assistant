import { requestGet } from './request'

/** 高德地图域：POI 检索（图片代理/静态图等直接走 URL 拼接，无需函数封装）。 */

export interface AmapPoi {
  id: string
  name: string
  address: string | null
  latitude: number | null
  longitude: number | null
  type: string | null
  rating: string | null
  cost: string | null
}

export function searchPoi(keywords: string, city?: string, types?: string) {
  return requestGet<AmapPoi[]>('/amap/poi', {
    params: { keywords: keywords || undefined, city: city || undefined, types: types || undefined },
  })
}

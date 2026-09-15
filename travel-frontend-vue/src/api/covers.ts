import { requestGet, requestPost } from './request'
import type { ItineraryDetail } from '../types/itinerary'

export interface CoverSearchItem {
  unsplashId: string
  thumb: string | null
  regular: string | null
  width: number | null
  height: number | null
  author: string | null
  authorUrl: string | null
  license: string
  downloadTrackUrl: string | null
}

export interface CoverSearchResult {
  total: number
  items: CoverSearchItem[]
}

/** 图库检索（服务端持 key 代理；未配置 key 时 400「封面图库未配置」）。 */
export function searchCovers(q: string, page = 1, perPage = 12) {
  return requestGet<CoverSearchResult>('/covers/search', { params: { q, page, perPage } })
}

/** 设定封面：unsplash 走服务端 snapshot 落盘；default 恢复（四列置 NULL，文件不回收）。 */
export function setCover(
  id: number,
  body: { source: 'unsplash'; unsplashId: string } | { source: 'default' },
) {
  return requestPost<ItineraryDetail>(`/itinerary/${id}/cover`, body)
}

/** 上传封面（jpeg/png ≤5MB）：客户端只做预检，服务端仍会校验并流式截断。 */
export function uploadCover(id: number, file: File) {
  const form = new FormData()
  form.append('file', file)
  return requestPost<ItineraryDetail>(`/itinerary/${id}/cover/upload`, form)
}

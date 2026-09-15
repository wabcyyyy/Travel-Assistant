import { requestDelete, requestGet, requestPost } from './request'
import type { SharedItinerary } from '../types/share'

export interface ShareStatus {
  shared: boolean
  shareToken?: string
  shareUrl?: string
  shareExpiresAt?: string | null
}

export interface ShareCreated {
  shareToken: string
  shareUrl: string
  shareExpiresAt: string | null
}

/** 创建/轮换分享链接（重复创建会让旧链接立即失效）。 */
export function createShare(id: number, expireDays: 7 | 30 | null) {
  return requestPost<ShareCreated>(`/itinerary/${id}/share`, { expireDays })
}

export function getShareStatus(id: number) {
  return requestGet<ShareStatus>(`/itinerary/${id}/share`)
}

export function removeShare(id: number) {
  return requestDelete<void>(`/itinerary/${id}/share`)
}

/** 匿名只读分享：失败由页面自渲染（404/网络都走统一失效态），不弹全局 toast。 */
export function getSharedItinerary(token: string) {
  return requestGet<SharedItinerary>(`/share/${token}`, { skipErrorMessage: true })
}

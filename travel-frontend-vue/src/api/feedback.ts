/**
 * 条目对/错反馈（C3.5）：一人一条可改可撤，私域质量信号（不进 share/模板/MCP 投影）。
 */
import { requestDelete, requestGet, requestPost } from './request'
import type * as Contracts from '../types/generated/contracts'

export type FeedbackCreate = Contracts.FeedbackCreate
export type FeedbackVO = Contracts.FeedbackVO
export type FeedbackReason = NonNullable<Contracts.FeedbackVO['reason']>

/**
 * 回显读取用 skipErrorMessage：item_feedback addon 关闭时端点 404、断网时也不该
 * 打断行程页——调用方按失败静默隐藏反馈入口（与 weather 同一取舍）。
 * 提交/撤销不加 skipErrorMessage：用户主动操作失败必须弹 toast，不能装作成功。
 */
export function fetchMyFeedback(itineraryId: number | string) {
  return requestGet<Contracts.FeedbackListVO>(`/itinerary/${itineraryId}/feedback`, { skipErrorMessage: true })
}

export function submitFeedback(itineraryId: number | string, body: FeedbackCreate) {
  return requestPost<FeedbackVO>(`/itinerary/${itineraryId}/feedback`, body)
}

/** 撤销自己的反馈（一人一条语义下按 itemId 定位本人行）。 */
export function revokeFeedback(itineraryId: number | string, itemId: number) {
  return requestDelete(`/itinerary/${itineraryId}/feedback/${itemId}`)
}

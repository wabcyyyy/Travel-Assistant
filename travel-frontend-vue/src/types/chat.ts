import type { HotelOption } from './itinerary'

/**
 * NL 编辑 / chat 域类型。
 * 后端草稿 plans 为 snake_case 开放结构，这里声明前端实际消费的最小字段
 * （day_no / items[].poi_name / start_time），替代此前的 any[] 逃逸。
 */

/** chat 草稿中的单个点位（后端返回 snake_case 草稿结构）。 */
export interface ChatPlanItem {
  poi_name?: string | null
  start_time?: string | null
  end_time?: string | null
}

/** chat 草稿中的单日方案。 */
export interface ChatDayPlan {
  day_no: number
  items?: ChatPlanItem[]
}

/** 一条对话消息（AI 消息可携带结构化草稿与住宿备选）。 */
export interface ItineraryChatMessage {
  id?: number
  role: 'user' | 'ai'
  content: string
  plans?: ChatDayPlan[]
  hotelOptions?: HotelOption[]
  changed?: boolean
  baseRevision?: string
  createdAt?: string
}

/** chat 草稿推送载荷：除 reply 外与 /chat-edit 响应字段一致。 */
export interface ChatDraftPayload {
  plans?: ChatDayPlan[]
  hotelOptions?: HotelOption[]
  changed?: boolean
  baseRevision?: string
  messageId?: number
}

export interface ChatStreamHandlers {
  /** 回复分段（打字机渲染）。 */
  onToken?: (delta: string) => void
  /** 草稿推送：除 reply 外与 /chat-edit 响应字段一致（plans/hotelOptions/changed/baseRevision/messageId）。 */
  onDraft?: (payload: ChatDraftPayload) => void
}

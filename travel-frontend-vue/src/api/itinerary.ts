import { requestDelete, requestGet, requestPost, requestPut } from './request'
import type {
  ChatDayPlan,
  ChatDraftPayload,
  ChatStreamHandlers,
  ItineraryChatMessage,
} from '../types/chat'
import type {
  HotelOption,
  ItineraryDetail,
  ItinerarySummary,
  TripItem,
} from '../types/itinerary'

/** 行程域：生成/查询/逐项编辑/NL 编辑与 chat 流式/酒店方案/备选采纳。 */

// 酒店方案类型本体在 types/itinerary.ts（types/chat 依赖它，放本文件会造成 types↔api 循环依赖）；
// 这里 re-export 保持既有 `from '.../api'` 导入路径可用。
export type { HotelOption } from '../types/itinerary'

export function getSupportedCities() {
  return requestGet<string[]>('/itinerary/supported-cities')
}

export function generateItinerary(data: {
  city: string
  days: number
  persons: number
  stayNights: number
  budget?: number
  startDate?: string
  endDate?: string
  /** 旅行意图（最高优先级生成信号，≤800 字；完整交互见重构方案 §5.2） */
  intent?: string
  preferences: string[]
  hotelTier?: string
  regionHint?: string
  requirements?: string
}) {
  return requestPost<ItineraryDetail>('/itinerary/generate', data)
}

export function getItineraryList() {
  return requestGet<ItinerarySummary[]>('/itinerary')
}

export function getItineraryDetail(id: number | string) {
  return requestGet<ItineraryDetail>(`/itinerary/${id}`)
}

export function deleteItinerary(id: number) {
  return requestDelete<void>(`/itinerary/${id}`)
}

export function addItem(id: number | string, data: Partial<TripItem> & { dayId: number }) {
  return requestPost<ItineraryDetail>(`/itinerary/${id}/items`, data)
}

export function updateItem(itemId: number, data: Partial<TripItem>) {
  return requestPut<ItineraryDetail>(`/itinerary/items/${itemId}`, data)
}

export function deleteItem(itemId: number) {
  return requestDelete<ItineraryDetail>(`/itinerary/items/${itemId}`)
}

export function reorderItems(id: number | string, dayId: number, itemIds: number[]) {
  return requestPut<ItineraryDetail>(`/itinerary/${id}/days/${dayId}/order`, itemIds)
}

export function nlEditItinerary(id: number | string, instruction: string) {
  return requestPost<{ applied: string[] }>('/itinerary/' + id + '/nl-edit', { instruction })
}

export function chatEditItinerary(
  id: number | string,
  message: string,
  history: { role: string; content: string }[],
  signal?: AbortSignal,
) {
  return requestPost<{
    reply: string
    changed: boolean
    plans: ChatDayPlan[]
    hotelOptions: HotelOption[]
    requiresConfirmation: boolean
    planDocument?: Record<string, unknown> | null
    operations?: Record<string, unknown>[]
    pendingAction?: Record<string, unknown> | null
    messageId?: number
    baseRevision?: string
  }>(
    '/itinerary/' + id + '/chat-edit',
    { message, history },
    { signal },
  )
}

/** SSE 帧解析结果：empty=无 data 行（心跳/注释帧）；dirty=JSON 解析失败；envelope=正常事件。 */
export type SseFrameParse =
  | { kind: 'empty' }
  | { kind: 'dirty' }
  | { kind: 'envelope'; envelope: { type: string; data?: Record<string, unknown> } }

/**
 * 解析单个 SSE 帧（`data:` 行合并后 JSON.parse）。
 * 脏帧不抛异常：调用方跳过并计数——一帧协议异常不能中断整条编辑流。
 */
export function parseSseFrame(raw: string): SseFrameParse {
  const data = raw
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())
    .join('\n')
  if (!data) return { kind: 'empty' }
  try {
    return { kind: 'envelope', envelope: JSON.parse(data) }
  } catch {
    return { kind: 'dirty' }
  }
}

/**
 * NL 编辑 SSE 流式变体（POST /itinerary/{id}/chat-edit/stream，M2-③）。
 * 手动解析 text/event-stream（主凭据 HttpOnly Cookie，credentials include 即可）；
 * 网络/HTTP/协议异常与 error 事件都向上抛，由调用方回退阻塞端点 chatEditItinerary。
 */
export async function chatEditStreamItinerary(
  id: number | string,
  body: { message: string; history: { role: string; content: string }[] },
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/itinerary/${id}/chat-edit/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    throw new Error(`流式连接不可用（HTTP ${res.status}）`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let dirtyFrames = 0
  const handleFrame = (raw: string) => {
    const parsed = parseSseFrame(raw)
    if (parsed.kind === 'empty') return
    if (parsed.kind === 'dirty') {
      dirtyFrames += 1
      return
    }
    const envelope = parsed.envelope
    if (envelope.type === 'chat_token') {
      handlers.onToken?.(String(envelope.data?.delta ?? ''))
    } else if (envelope.type === 'chat_draft') {
      handlers.onDraft?.((envelope.data ?? {}) as ChatDraftPayload)
    } else if (envelope.type === 'error') {
      throw new Error(String(envelope.data?.message ?? '流式处理失败'))
    }
    // chat_done 无需处理：流自然结束
  }
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        handleFrame(frame)
        boundary = buffer.indexOf('\n\n')
      }
    }
  } finally {
    if (dirtyFrames > 0) {
      console.warn(`[chat-edit] 跳过 ${dirtyFrames} 个无法解析的 SSE 帧（已忽略，流未中断）`)
    }
  }
}

export function getItineraryChatHistory(id: number | string) {
  return requestGet<ItineraryChatMessage[]>(`/itinerary/${id}/chat-history`)
}

export function clearItineraryChatHistory(id: number | string) {
  return requestDelete<void>(`/itinerary/${id}/chat-history`)
}

export function cityGuide(input: string, history: { role: string; content: string }[]) {
  return requestPost<{
    kind: 'province' | 'city' | 'unclear'
    city: string | null
    message: string
    suggestions: { name: string; reason: string }[]
  }>('/itinerary/city-guide', { input, history })
}

export interface NearbyPoi {
  name: string
  category: string
  rating: number | null
  address: string | null
  distanceM: number | null
}

/** 附近推荐：行程项所在城市的权威知识库真实近邻（轻量 GraphRAG）。 */
export function getNearbyPois(data: {
  city: string
  name?: string
  latitude?: number
  longitude?: number
  limit?: number
  category?: string
}) {
  return requestPost<{ items: NearbyPoi[] }>('/itinerary/poi-nearby', data)
}

/** 采纳 chat 草稿（「应用到行程」入口），返回应用后的行程全量。 */
export function applyPlans(
  id: number | string,
  plans: ChatDayPlan[],
  actionMessageId?: number,
  baseRevision?: string,
) {
  return requestPost<ItineraryDetail>('/itinerary/' + id + '/apply-plans', {
    plans,
    actionMessageId,
    baseRevision,
  })
}

/** 替换酒店方案（HotelOptionsDialog 选择入口），返回应用后的行程全量。 */
export function applyHotelOption(
  id: number | string,
  option: Pick<HotelOption, 'hotelName' | 'tier'>,
  roomType: string,
  dayNos: number[],
  actionMessageId?: number,
  baseRevision?: string,
) {
  return requestPost<ItineraryDetail>('/itinerary/' + id + '/hotel-option', {
    hotelName: option.hotelName,
    tier: option.tier,
    roomType,
    dayNos,
    actionMessageId,
    baseRevision,
  })
}

import type * as Contracts from '../types/generated/contracts'
import type { ChatDraftPayload, ItineraryChatMessage } from '../types/chat'
import type { HotelOption, ItineraryDetail, ItinerarySummary, TripItem } from '../types/itinerary'

export class ReactApiError extends Error {
  status?: number
  code?: number

  constructor(message: string, status?: number, code?: number) {
    super(message)
    this.name = 'ReactApiError'
    this.status = status
    this.code = code
  }
}

type Envelope<T> = { code: number; message: string; data: T }

// 前缀单独成常量：apiRequest 是透传管道，具体路径由各调用点声明
// （后端 cutover 契约测试逐点扫描 apiRequest 调用，见 test_cutover_contract.py）。
const API_BASE = '/api'

async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init.headers ?? {}),
    },
  })

  const raw = await response.text()
  let payload: Envelope<T> | null = null
  if (raw) {
    try {
      payload = JSON.parse(raw) as Envelope<T>
    } catch {
      throw new ReactApiError('服务器返回了无法识别的内容', response.status)
    }
  }
  if (!response.ok) {
    throw new ReactApiError(payload?.message || `请求失败（${response.status}）`, response.status, payload?.code)
  }
  if (payload && typeof payload.code === 'number' && payload.code !== 200) {
    throw new ReactApiError(payload.message || '请求失败', response.status, payload.code)
  }
  return (payload?.data ?? payload) as T
}

function waitFor(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('请求已取消', 'AbortError'))
      return
    }
    let timer = 0
    const cleanup = () => signal?.removeEventListener('abort', onAbort)
    const onAbort = () => {
      window.clearTimeout(timer)
      cleanup()
      reject(new DOMException('请求已取消', 'AbortError'))
    }
    timer = window.setTimeout(() => { cleanup(); resolve() }, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

export function isOfflineError(error: unknown): boolean {
  return error instanceof TypeError || (error instanceof ReactApiError && (!error.status || error.status >= 500))
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ReactApiError && error.status === 401
}

export function getSupportedCities() {
  return apiRequest<string[]>('/itinerary/supported-cities')
}

export function login(data: Contracts.LoginBody) {
  return apiRequest<Contracts.LoginData>('/auth/login', { method: 'POST', body: JSON.stringify(data) })
}

export function register(data: Contracts.RegisterBody) {
  return apiRequest<void>('/auth/register', { method: 'POST', body: JSON.stringify(data) })
}

export function logout() {
  return apiRequest<void>('/auth/logout', { method: 'POST' })
}

export function getUserInfo() {
  return apiRequest<Contracts.UserInfoVO>('/user/info')
}

export interface GenerateInput {
  city: string
  days: number
  persons: number
  stayNights: number
  budget?: number
  startDate?: string
  endDate?: string
  originCity?: string
  intent?: string
  preferences: string[]
  hotelTier?: string
  regionHint?: string
  requirements?: string
}

export function clarifyItinerary(message: string, slots: Record<string, unknown>, signal?: AbortSignal) {
  return apiRequest<Contracts.ClarifyResponse>('/itinerary/clarify', {
    method: 'POST',
    signal,
    body: JSON.stringify({ message, slots }),
  })
}

export function generateItinerary(data: GenerateInput, idempotencyKey: string, signal?: AbortSignal) {
  return apiRequest<ItineraryDetail>('/itinerary/generate', {
    method: 'POST',
    signal,
    headers: { 'X-Idempotency-Key': idempotencyKey },
    body: JSON.stringify(data),
  })
}

export function listItineraries(view?: string, query?: string) {
  const params = new URLSearchParams()
  if (view && view !== 'all') params.set('view', view)
  if (query) params.set('q', query)
  return apiRequest<ItinerarySummary[]>(`/itinerary?${params.toString()}`)
}

export function getItineraryDetail(id: number | string) {
  return apiRequest<ItineraryDetail>(`/itinerary/${id}`)
}

export function getItineraryWeather(id: number | string) {
  return apiRequest<Contracts.WeatherVO>(`/itinerary/${id}/weather`)
}

export interface WaitForItineraryOptions {
  signal?: AbortSignal
  intervalMs?: number
  timeoutMs?: number
  onUpdate?: (detail: ItineraryDetail) => void
}

/**
 * The generate endpoint creates a persisted shell before the background agent
 * fills each day. SSE is the preferred progress channel, but a page refresh or
 * a proxy can interrupt that stream. This bounded poll keeps the already
 * persisted draft recoverable without creating another itinerary.
 */
export async function waitForItinerary(id: number | string, options: WaitForItineraryOptions = {}) {
  const startedAt = Date.now()
  const intervalMs = Math.max(500, options.intervalMs ?? 2000)
  const timeoutMs = Math.max(intervalMs, options.timeoutMs ?? 120000)

  for (;;) {
    const detail = await apiRequest<ItineraryDetail>(`/itinerary/${id}`, { signal: options.signal })
    options.onUpdate?.(detail)
    if (detail.status === 2) return detail
    if (detail.status === 3) {
      throw new ReactApiError(detail.planNote || '行程生成失败，请稍后重试')
    }
    if (Date.now() - startedAt >= timeoutMs) {
      throw new ReactApiError('行程仍在后台整理，可以稍后从我的行程继续查看')
    }
    await waitFor(intervalMs, options.signal)
  }
}

export function getSharedItinerary(token: string) {
  return apiRequest<{
    city: string
    title: string
    days: number
    persons: number
    startDate: string | null
    endDate: string | null
    budget: number | null
    tripTheme: string | null
    totalAmount: number
    dayList: Array<{ dayNo: number; travelDate: string | null; theme: string | null; note: string | null; dayTotalAmount: number; items: Array<{ poiName: string; itemType: string; address: string | null; startTime: string | null; endTime: string | null; cost: number | null }> }>
    budgetList: Array<{ category: string; amount: number | null; itemCount: number }>
    planNote: string | null
  }>(`/share/${encodeURIComponent(token)}`)
}

export function optimizeDay(id: number | string, dayId: number) {
  return apiRequest<ItineraryDetail>(`/itinerary/${id}/optimize`, {
    method: 'POST',
    body: JSON.stringify({ dayId }),
  })
}

export function updateDay(id: number | string, dayId: number, theme: string) {
  return apiRequest<ItineraryDetail>(`/itinerary/${id}/days/${dayId}`, {
    method: 'PATCH',
    body: JSON.stringify({ theme }),
  })
}

export function setFavorite(id: number, favorite: boolean) {
  return apiRequest<ItineraryDetail>(`/itinerary/${id}/favorite`, {
    method: 'POST',
    body: JSON.stringify({ favorite }),
  })
}

export function createShare(id: number, expireDays: 7 | 30 | null = 7) {
  return apiRequest<{ shareToken: string; shareUrl: string; shareExpiresAt: string | null }>(`/itinerary/${id}/share`, {
    method: 'POST',
    body: JSON.stringify({ expireDays }),
  })
}

export function createPdfExport(id: number) {
  return apiRequest<{ id: number; status: 'RUNNING' | 'DONE' | 'FAILED'; downloadUrl: string | null }>(`/export/pdf/${id}`, {
    method: 'POST',
  })
}

export function getExportTask(taskId: number) {
  return apiRequest<{ id: number; status: 'RUNNING' | 'DONE' | 'FAILED'; downloadUrl: string | null; errorMsg: string | null }>(`/export/tasks/${taskId}`)
}

export function exportDownloadUrl(taskId: number) {
  return `/api/export/download/${taskId}`
}

export interface WaitForExportOptions {
  signal?: AbortSignal
  intervalMs?: number
  timeoutMs?: number
  onUpdate?: (task: Awaited<ReturnType<typeof getExportTask>>) => void
}

export async function waitForExport(taskId: number, options: WaitForExportOptions = {}) {
  const startedAt = Date.now()
  const intervalMs = Math.max(500, options.intervalMs ?? 1500)
  const timeoutMs = Math.max(intervalMs, options.timeoutMs ?? 60000)
  for (;;) {
    const task = await getExportTask(taskId)
    options.onUpdate?.(task)
    if (task.status === 'DONE') return task
    if (task.status === 'FAILED') throw new ReactApiError(task.errorMsg || 'PDF 导出失败')
    if (Date.now() - startedAt >= timeoutMs) throw new ReactApiError('PDF 仍在生成，请稍后再试')
    await waitFor(intervalMs, options.signal)
  }
}

export type ItineraryStreamEvent = {
  type: string
  itineraryId?: number
  seq?: number
  ts?: string
  data?: Record<string, unknown>
  plan?: Contracts.DailyPlan
  message?: string
}

export interface StreamHandlers {
  onEvent: (event: ItineraryStreamEvent) => void
  onError: (error: Error) => void
}

/**
 * Subscribe to the existing itinerary SSE endpoint. The caller owns the
 * AbortController so a route change never leaves a stream running.
 */
export async function streamItineraryEvents(id: number | string, signal: AbortSignal, handlers: StreamHandlers) {
  const response = await fetch(`/api/itinerary/${id}/events`, {
    credentials: 'include',
    headers: { Accept: 'text/event-stream' },
    signal,
  })
  if (!response.ok || !response.body) {
    throw new ReactApiError(`实时进度暂不可用（${response.status}）`, response.status)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const data = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trim())
          .join('\n')
        if (data) {
          try {
            handlers.onEvent(JSON.parse(data) as ItineraryStreamEvent)
          } catch {
            // One malformed frame should not discard later progress.
          }
        }
        boundary = buffer.indexOf('\n\n')
      }
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    const normalized = error instanceof Error ? error : new Error('实时进度连接中断')
    handlers.onError(normalized)
    throw normalized
  } finally {
    reader.releaseLock()
  }
}

export function toItemLabel(item: Pick<TripItem, 'poiName' | 'itemType'>) {
  return item.poiName || item.itemType || '未命名地点'
}

// ===== 行程对话（chat-edit，CH3/L2）=====

export type ChatHistory = Array<{ role: 'user' | 'ai'; content: string }>

export interface ChatReply extends ChatDraftPayload {
  reply?: string
}

export function getItineraryChatHistory(id: number | string) {
  return apiRequest<ItineraryChatMessage[]>(`/itinerary/${id}/chat-history`)
}

export function clearItineraryChatHistory(id: number | string) {
  return apiRequest<void>(`/itinerary/${id}/chat-history`, { method: 'DELETE' })
}

/** 阻塞版对话回合：流式失败时的回退通道。 */
export function chatEditItinerary(id: number | string, message: string, history: ChatHistory, signal?: AbortSignal) {
  return apiRequest<ChatReply>(`/itinerary/${id}/chat-edit`, {
    method: 'POST',
    signal,
    body: JSON.stringify({ message, history }),
  })
}

/**
 * 流式对话回合：POST SSE，帧形 {type, itineraryId, seq, ts, data}。
 * chat_token → onToken(delta)；chat_draft → onDraft(草稿九键，plans 为 snake_case)；
 * error 帧 → throw Error(message)；chat_done 忽略。
 */
export async function chatEditStream(
  id: number | string,
  message: string,
  history: ChatHistory,
  handlers: { onToken: (delta: string) => void; onDraft: (payload: ChatDraftPayload) => void },
  signal?: AbortSignal,
) {
  const response = await fetch(`/api/itinerary/${id}/chat-edit/stream`, {
    method: 'POST',
    credentials: 'include',
    headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new ReactApiError(`流式连接不可用（${response.status}）`, response.status)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const data = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trim())
          .join('\n')
        if (data) {
          let parsed: { type?: string; data?: Record<string, unknown>; message?: string } | null = null
          try {
            parsed = JSON.parse(data)
          } catch {
            // 脏帧不抛：一帧坏不该断掉整条流
          }
          if (!parsed) continue
          if (parsed.type === 'chat_token') handlers.onToken(String(parsed.data?.delta ?? ''))
          else if (parsed.type === 'chat_draft') handlers.onDraft((parsed.data ?? {}) as ChatDraftPayload)
          else if (parsed.type === 'error') {
            throw new Error(String(parsed.message || parsed.data?.message || '行程助手暂时不可用'))
          }
          // chat_done / heartbeat：无需处理
        }
        boundary = buffer.indexOf('\n\n')
      }
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    throw error instanceof Error ? error : new Error('实时连接中断')
  } finally {
    reader.releaseLock()
  }
}

/** 应用对话草稿：服务端有意忽略 plans，只认 actionMessageId 对应的持久化草稿。 */
export function applyPlans(id: number | string, actionMessageId: number | null, baseRevision: string | null) {
  return apiRequest<ItineraryDetail>(`/itinerary/${id}/apply-plans`, {
    method: 'POST',
    body: JSON.stringify({ plans: [], actionMessageId, baseRevision }),
  })
}

export interface HotelApplyInput {
  hotelName: string
  tier: string
  roomType: string
  dayNos: number[]
}

/** 应用酒店候选：HITL 确认（replace_hotel）经此端点 resume。 */
export function applyHotelOption(
  id: number | string,
  input: HotelApplyInput,
  actionMessageId: number | null,
  baseRevision: string | null,
) {
  return apiRequest<ItineraryDetail>(`/itinerary/${id}/hotel-option`, {
    method: 'POST',
    body: JSON.stringify({ ...input, actionMessageId, baseRevision }),
  })
}

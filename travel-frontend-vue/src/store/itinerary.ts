import { defineStore } from 'pinia'
import { getItineraryDetail } from '../api/itinerary'
import type { ChatDraftPayload } from '../types/chat'
import type { ItineraryDetail } from '../types/itinerary'
import type { ItineraryStreamEvent } from '../types/stream'

/**
 * 行程 store（M4-① AD7，全量重构方案 §5.4）：
 * detail 为行程全量单一数据源；SSE 事件经 applyStreamEvent reducer 落状态机；
 * 乐观写操作走 beginOp/commitOp/rollbackOp 快照队列；酒店选择的 localStorage
 * 读写收敛于本 store 单点（key 与拆分前一致，零迁移成本）。
 */

/** 生成进度状态机相位（§5.3.5 事件→状态映射）。 */
export type StreamPhase = 'idle' | 'researching' | 'day' | 'butler' | 'complete' | 'failed'

/** 单条降级标记：如实可见，不静默（原则 4）。 */
export interface DegradedMark {
  scope: string
  reason: string
}

/** SSE 生成进度状态机。 */
export interface StreamState {
  phase: StreamPhase
  /** day 相位：正在生成/刚完成的天号（day_done 后推进到下一待生成天） */
  dayNo?: number
  /** 研究阶段证据条数（research_done 携带 evidenceCount） */
  evidenceCount?: number
  /** 生成过程中累计的降级标记 */
  degraded: DegradedMark[]
  /** 终态收束：未成功生成的天号列表（complete 事件携带 degradedDays） */
  degradedDays: number[]
  /** SSE 链路不可用（3 连败）：调用方需切轮询兜底 */
  fallbackMode: boolean
  /** error 事件是否标注可重试 */
  retryable?: boolean
  /** 最近一次 error 事件的消息 */
  errorMessage?: string
}

/** 酒店选择：房型 + 入住晚次（与 HotelOptionsDialog 的 Selection 结构一致）。 */
export interface HotelSelection {
  roomTypeId: string
  dayNos: number[]
}

/** 乐观写操作队列条目：beginOp 时保存 detail 快照，失败时回滚。 */
export interface PendingOp {
  id: number
  label: string
  snapshot: ItineraryDetail | null
  startedAt: number
}

function initialStreamState(): StreamState {
  return { phase: 'idle', degraded: [], degradedDays: [], fallbackMode: false }
}

/** 酒店选择 localStorage key：与既有 TripDetailView 逻辑保持一致。 */
function selectionStorageKey(id: number | string): string {
  return `trip-hotel-selections:${String(id)}`
}

interface ItineraryState {
  /** 行程全量单一数据源 */
  detail: ItineraryDetail | null
  /** 乐观锁修订计数：每次 setDetail/回滚自增 */
  revision: number
  streamState: StreamState
  /** NL 编辑草稿（plans/hotelOptions/changed/baseRevision/messageId） */
  chatDraft: ChatDraftPayload
  /** 进行中的乐观写操作（快照队列） */
  pendingOps: PendingOp[]
  /** 酒店选择（localStorage 持久化，读写收敛于本 store） */
  hotelSelections: Record<string, HotelSelection>
}

let opSeq = 0

export const useItineraryStore = defineStore('itinerary', {
  state: (): ItineraryState => ({
    detail: null,
    revision: 0,
    streamState: initialStreamState(),
    chatDraft: {},
    pendingOps: [],
    hotelSelections: {},
  }),
  actions: {
    /** 直接覆盖行程全量数据（API 返回详情时回填），并推进修订计数。 */
    setDetail(next: ItineraryDetail) {
      this.detail = next
      this.revision += 1
    },

    /** 对账刷新：全量 GET 详情并落 store（轮询/SSE 重连/409 冲突后共用）。 */
    async detail$(id: number | string) {
      const res = await getItineraryDetail(id)
      this.setDetail(res.data)
    },

    /** 以当前 detail.id 对账；无 detail 时静默跳过。 */
    async reconcile() {
      const id = this.detail?.id
      if (id != null) await this.detail$(id)
    },

    /** 打开新事件流前重置生成进度状态机。 */
    resetStream() {
      this.streamState = initialStreamState()
    },

    /**
     * SSE 事件 reducer（§5.3.5 事件→状态映射逐条落地）：
     * research_start→researching、research_done→记录证据数、day_start→day+dayNo、
     * day_done→推进到下一天（detail 已有该天仅更新摘要，点位以详情对账为准）、
     * butler_note→butler、degraded→追加标记、complete→收束+degradedDays、
     * error→failed+retryable。heartbeat/export_done/chat_* 不在生成状态机内。
     */
    applyStreamEvent(event: ItineraryStreamEvent) {
      const s = this.streamState
      const data = (event.data ?? {}) as Record<string, unknown>
      switch (event.type) {
        case 'research_start':
          s.phase = 'researching'
          break
        case 'research_done': {
          const count = Number(data.evidenceCount)
          s.evidenceCount = Number.isFinite(count) ? count : undefined
          break
        }
        case 'day_start':
          s.phase = 'day'
          s.dayNo = Number(data.dayNo) || undefined
          break
        case 'day_done': {
          const dayNo = Number(data.dayNo)
          s.phase = 'day'
          s.dayNo = Number.isFinite(dayNo) ? dayNo + 1 : s.dayNo
          // detail 已有该天时仅更新摘要字段（theme/note），不覆盖 items
          if (this.detail && Number.isFinite(dayNo)) {
            const day = this.detail.dayList.find((d) => d.dayNo === dayNo)
            if (day) {
              if (data.theme != null) day.theme = String(data.theme)
              if (data.note != null) day.note = String(data.note)
            }
          }
          break
        }
        case 'butler_note':
          s.phase = 'butler'
          break
        case 'degraded':
          s.degraded.push({
            scope: String(data.scope ?? '未知环节'),
            reason: String(data.reason ?? '将简化交付'),
          })
          break
        case 'complete':
          s.phase = 'complete'
          s.dayNo = undefined
          s.degradedDays = Array.isArray(data.degradedDays) ? data.degradedDays.map(Number) : []
          break
        case 'error':
          s.phase = 'failed'
          s.retryable = data.retryable === true
          s.errorMessage = typeof data.message === 'string' ? data.message : undefined
          break
        default:
          // 其余事件类型不驱动生成状态机
          break
      }
    },

    /** 开始乐观写操作：保存当前 detail 快照入队，返回操作 id。 */
    beginOp(label: string): number {
      const id = ++opSeq
      this.pendingOps.push({ id, label, snapshot: this.detail, startedAt: Date.now() })
      return id
    },

    /** 写操作成功：丢弃快照出队。 */
    commitOp(opId: number) {
      const idx = this.pendingOps.findIndex((op) => op.id === opId)
      if (idx >= 0) this.pendingOps.splice(idx, 1)
    },

    /** 写操作失败：恢复快照并出队（detail 回到操作前状态）。 */
    rollbackOp(opId: number) {
      const idx = this.pendingOps.findIndex((op) => op.id === opId)
      if (idx < 0) return
      const [op] = this.pendingOps.splice(idx, 1)
      if (op.snapshot) {
        this.detail = op.snapshot
        this.revision += 1
      }
    },

    /** 合并更新 NL 编辑草稿。 */
    setChatDraft(partial: Partial<ChatDraftPayload>) {
      this.chatDraft = { ...this.chatDraft, ...partial }
    },

    /** 清空草稿。 */
    clearChatDraft() {
      this.chatDraft = {}
    },

    /** 从 localStorage 恢复酒店选择（解析失败按空处理，与既有行为一致）。 */
    loadHotelSelections(id: number | string) {
      try {
        const raw = localStorage.getItem(selectionStorageKey(id))
        this.hotelSelections = raw ? (JSON.parse(raw) as Record<string, HotelSelection>) : {}
      } catch {
        this.hotelSelections = {}
      }
    },

    /** 持久化酒店选择：localStorage 写入单点出口。 */
    persistHotelSelections(id: number | string, value: Record<string, HotelSelection>) {
      if (this.hotelSelections !== value) this.hotelSelections = value
      localStorage.setItem(selectionStorageKey(id), JSON.stringify(value))
    },

    /** 清空酒店选择（本地 + localStorage）。 */
    clearHotelSelections(id: number | string) {
      this.hotelSelections = {}
      localStorage.removeItem(selectionStorageKey(id))
    },
  },
})

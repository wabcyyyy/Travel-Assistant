/**
 * SSE 事件流类型（全量重构方案 §4.3.2 统一信封）。
 * 独立成文件供 store（applyStreamEvent）与 composable（useItineraryStream）共用，避免二者互相依赖。
 */

/** 与后端约定一致的 SSE 统一信封：{type, itineraryId, seq, ts, data} */
export interface ItineraryStreamEvent<T = Record<string, unknown>> {
  type: string
  itineraryId: number
  seq: number
  ts: string
  data: T
}

export interface StreamLifecycleHooks {
  /** 链路不可用（连续失败）：调用方接手降级路径（既有轮询）。 */
  onFallback: () => void
  /** 断线重连成功：调用方需全量 GET /{id} 对账（协议 §4.3.4，不回放 missed 事件）。 */
  onReconcile: () => void
}

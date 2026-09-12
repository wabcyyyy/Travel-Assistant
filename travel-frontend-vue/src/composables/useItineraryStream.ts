import { ref } from 'vue'
import { useItineraryStore } from '../store/itinerary'
import type { ItineraryStreamEvent, StreamLifecycleHooks } from '../types/stream'

// 类型改由 types/stream 承载（store 与 composable 共用）；此处 re-export 保持既有导入路径兼容。
export type { ItineraryStreamEvent, StreamLifecycleHooks } from '../types/stream'

type StreamHandler = (event: ItineraryStreamEvent) => void

/**
 * 生成进度事件流订阅（M2-③ AD2 最小接入版 → M4-① AD7 升级）。
 *
 * - 主凭据是 HttpOnly Cookie 且同源，原生 EventSource 自动携带，无需引入
 *   fetch-event-source（该依赖价值在 POST + 自定义头，本页 chat 流式走 fetch 自解析）；
 * - 事件先经 itinerary store 的 applyStreamEvent reducer 落全局状态机，再分发给
 *   本页注册的 handler（§5.3.5）；
 * - seq 单调递增：乱序/重复帧记 warn 并忽略，避免旧事件覆盖新状态；
 *   断线重连成功后重开序号窗口（跨断线的 seq 连续性不作保证，一致性由全量对账兜底）；
 * - EventSource 自带断线重连（内建退避）：连续 3 次 onerror 视为链路不可用 →
 *   close + store.streamState.fallbackMode=true + onFallback 降级回轮询；
 *   重连成功（onopen 且此前断开过）→ onReconcile 全量对账，用户无感恢复；
 * - 事件按信封 type 分发；注册 '*' 可观察全部事件。
 */
export function useItineraryStream() {
  const connected = ref(false)
  let source: EventSource | null = null
  let errorCount = 0
  let everOpened = false
  let lastSeq: number | null = null
  let hooks: StreamLifecycleHooks | null = null
  const handlers = new Map<string, Set<StreamHandler>>()
  const store = useItineraryStore()

  function dispatch(event: ItineraryStreamEvent) {
    handlers.get(event.type)?.forEach((handler) => handler(event))
    handlers.get('*')?.forEach((handler) => handler(event))
  }

  /** 帧入口：乱序过滤 → store reducer → 业务分发。 */
  function accept(event: ItineraryStreamEvent) {
    if (lastSeq != null && event.seq <= lastSeq) {
      console.warn(
        `[itinerary-stream] 忽略乱序事件 seq=${event.seq}（last=${lastSeq}）type=${event.type}`,
      )
      return
    }
    lastSeq = event.seq
    store.applyStreamEvent(event)
    dispatch(event)
  }

  /** 注册某类型事件处理器，返回取消函数。需在 open 之前注册。 */
  function on(type: string, handler: StreamHandler): () => void {
    let set = handlers.get(type)
    if (!set) {
      set = new Set()
      handlers.set(type, set)
    }
    set.add(handler)
    return () => set!.delete(handler)
  }

  /** 建立 SSE 连接；重复调用会先关闭旧连接（路由切换/重建场景）。 */
  function open(itineraryId: number | string, lifecycle: StreamLifecycleHooks): void {
    close()
    hooks = lifecycle
    errorCount = 0
    everOpened = false
    lastSeq = null
    store.resetStream()
    source = new EventSource(`/api/itinerary/${itineraryId}/events`)
    source.onopen = () => {
      connected.value = true
      errorCount = 0
      // 重连后重开序号窗口，避免服务端计数器边缘重置被误判乱序吞帧
      lastSeq = null
      if (everOpened) {
        // 断线重连成功：不回放 missed 事件，立即全量对账恢复一致
        hooks?.onReconcile()
      } else {
        everOpened = true
      }
    }
    source.onmessage = (e: MessageEvent<string>) => {
      try {
        accept(JSON.parse(e.data) as ItineraryStreamEvent)
      } catch {
        // 非法帧（代理注入/脏数据）直接忽略，不影响后续事件
      }
    }
    source.onerror = () => {
      connected.value = false
      errorCount += 1
      // 3 次连续失败≈15s+ 不可用（EventSource 默认 ~3s 重连间隔），降级回轮询
      if (errorCount >= 3) {
        close()
        store.streamState.fallbackMode = true
        hooks?.onFallback()
      }
    }
  }

  function close(): void {
    if (source) {
      source.close()
      source = null
    }
    connected.value = false
  }

  return { connected, on, open, close }
}

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  generateItinerary,
  getItineraryDetail,
  isOfflineError,
  isUnauthorized,
  streamItineraryEvents,
  waitForItinerary,
} from '../../api/sinan'
import type { GenerateInput } from '../../api/sinan'
import type { ItineraryStreamEvent } from '../../api/sinan'
import type { ItineraryDetail } from '../../types/itinerary'

export type PlanningStatus = 'idle' | 'creating' | 'planning' | 'ready' | 'pending' | 'error' | 'login'

// 生成中的行程 id 暂存：刷新/断流后重挂载时据此续上监控（行程本身在服务端继续生成）
const GENERATION_KEY = 'sinan-intake-generation'

function readGenerationId(): number | null {
  try {
    const id = Number(sessionStorage.getItem(GENERATION_KEY))
    return Number.isInteger(id) && id > 0 ? id : null
  } catch {
    return null
  }
}

function saveGenerationId(id: number) {
  try {
    sessionStorage.setItem(GENERATION_KEY, String(id))
  } catch {
    // 存储不可用：只损失刷新续看，不影响本次生成
  }
}

function clearGenerationId() {
  try {
    sessionStorage.removeItem(GENERATION_KEY)
  } catch {
    // ignore
  }
}

export function useHomePlanning() {
  const [status, setStatus] = useState<PlanningStatus>('idle')
  const [message, setMessage] = useState('')
  const [progress, setProgress] = useState(0)
  const [draft, setDraft] = useState<ItineraryDetail | null>(null)
  const request = useRef<AbortController | null>(null)
  const busy = status === 'creating' || status === 'planning'

  useEffect(() => () => request.current?.abort(), [])

  const monitor = useCallback(async (created: ItineraryDetail, controller: AbortController) => {
    const onEvent = (event: ItineraryStreamEvent) => {
      if (controller.signal.aborted) return
      const data = event.data || {}
      if (event.type === 'research_start') { setProgress(1); setMessage('正在查找目的地信息') }
      if (event.type === 'research_done') { setProgress(2); setMessage('正在安排每天的路线') }
      if (event.type === 'day_start') { setProgress(2); setMessage(`正在安排第 ${String(data.dayNo || '')} 天`) }
      if (event.type === 'day_done') setMessage(`第 ${String(data.dayNo || '')} 天已安排好`)
      if (event.type === 'butler_note') { setProgress(3); setMessage('正在补充出行提醒') }
    }
    // SSE 与轮询并行：SSE 管进度文案，轮询 2s 对账管预览数据——串行的话，
    // 流没关之前 day_done 已落库但 setDraft 不更新，预览天卡会一直停在「安排中」。
    // 轮询超时须覆盖整个生成时长（默认 120s 是串行时代的余量），超限转 pending 兜底。
    const sse = streamItineraryEvents(created.id, controller.signal, { onEvent, onError: () => {} }).catch(() => {})
    try {
      const result = await waitForItinerary(created.id, {
        signal: controller.signal,
        timeoutMs: 30 * 60 * 1000,
        onUpdate: (detail) => { if (!controller.signal.aborted) setDraft(detail) },
      })
      if (controller.signal.aborted) return
      clearGenerationId()
      setDraft(result); setProgress(4); setStatus('ready'); setMessage('你的行程已准备好')
    } catch (error) {
      if (controller.signal.aborted) return
      clearGenerationId()
      setStatus('pending')
      setMessage(error instanceof Error ? error.message : '进度暂时不可用，已保留当前行程。')
    }
    await sse
  }, [])

  async function submit(input: GenerateInput) {
    if (request.current) return
    const controller = new AbortController()
    request.current = controller
    setStatus('creating'); setMessage('正在创建你的行程'); setProgress(0); setDraft(null)
    let created: ItineraryDetail | null = null
    try {
      created = await generateItinerary(input, crypto.randomUUID(), controller.signal)
      if (controller.signal.aborted) return
      saveGenerationId(created.id)
      setDraft(created); setStatus('planning')
      await monitor(created, controller)
    } catch (error) {
      if (controller.signal.aborted) return
      if (isUnauthorized(error)) {
        setStatus('login'); setMessage('登录后即可开始规划，你填写的想法会保留。')
      } else if (created) {
        setStatus('pending'); setMessage('进度暂时不可用，已保留当前行程，可从我的行程继续查看。')
      } else {
        setStatus('error'); setMessage(isOfflineError(error) ? '暂时无法连接规划服务。你的想法已保留，请稍后重试。' : error instanceof Error ? error.message : '这次规划没有完成，请重试。')
      }
    } finally {
      if (request.current === controller) request.current = null
    }
  }

  /** 刷新/重挂载后续看生成中的行程：SSE 不可达也能靠轮询对账。
   * 刻意不走 request.current 与卸载中止：StrictMode 双挂载的模拟卸载会把它误杀，
   * 用 resumedRef 保证只续一次；页面真卸载时浏览器自己回收连接。 */
  const resumedRef = useRef(false)
  const resumePending = useCallback(async () => {
    if (resumedRef.current) return
    resumedRef.current = true
    const id = readGenerationId()
    if (!id) return
    const controller = new AbortController()
    try {
      const shell = await getItineraryDetail(id)
      if (shell.status === 3) {
        clearGenerationId()
        return
      }
      setDraft(shell)
      if (shell.status === 2) {
        clearGenerationId()
        setProgress(4); setStatus('ready'); setMessage('你的行程已准备好')
        return
      }
      saveGenerationId(id)
      setStatus('planning'); setMessage('上次的规划还在进行，接着看'); setProgress(2)
      await monitor(shell, controller)
    } catch {
      // 只有无 abort 的真失败才清标记；abort（导航离开）保留续看入口
      if (!controller.signal.aborted) clearGenerationId()
    }
  }, [monitor])

  useEffect(() => { void resumePending() }, [resumePending])

  return { status, message, progress, draft, busy, submit }
}

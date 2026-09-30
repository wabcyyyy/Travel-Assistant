import { useCallback, useEffect, useRef, useState } from 'react'
import { clarifyItinerary, isOfflineError, isUnauthorized } from '../../api/sinan'
import {
  assistantReply,
  clearIntake,
  GREETING,
  loadIntake,
  mergeSlots,
  saveIntake,
  slotsReady,
} from './intakeSlots'
import type { IntakeMessage, IntakeSlots, IntakeState } from './intakeSlots'

let messageSeq = 0
function nextMessageId() {
  messageSeq += 1
  return `msg-${Date.now().toString(36)}-${messageSeq}`
}

/** 对话式创建的会话状态机：每轮 POST /clarify 累积槽位，ready 后交确认条。
 * 就绪与否不落存储——恢复时从槽位重新推导，blocked 天数会自然跌回对话态。 */
export function useIntakeChat() {
  const [restored] = useState<IntakeState | null>(() => loadIntake())
  const [messages, setMessages] = useState<IntakeMessage[]>(() => restored?.messages ?? [GREETING])
  const [slots, setSlots] = useState<IntakeSlots>(() => restored?.slots ?? {})
  const [firstMessage, setFirstMessage] = useState(() => restored?.firstMessage ?? '')
  const [ready, setReady] = useState(() => slotsReady(restored?.slots ?? {}))
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  // 未登录撞上 clarify 的 401：生成跳有「登录后即可开始规划」的引导，clarify 这
  // 一跳此前只会弹「请求失败（401）」——未登录用户收集到一半就卡死（2026-09-30
  // 漏斗实测）。needsLogin 让确认区就地给出登录入口；会话已落 localStorage，
  // 登录回来恢复后接着聊。
  const [needsLogin, setNeedsLogin] = useState(false)
  const controller = useRef<AbortController | null>(null)

  useEffect(() => () => controller.current?.abort(), [])

  useEffect(() => {
    const isFresh = messages.length === 1 && messages[0].id === GREETING.id && !firstMessage
    if (isFresh) clearIntake()
    else saveIntake({ messages, slots, firstMessage })
  }, [messages, slots, firstMessage])

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || sending) return
      setError('')
      setNeedsLogin(false)
      setSending(true)
      const ask = (controller.current = new AbortController())
      setMessages((list) => [...list, { id: nextMessageId(), role: 'user', text: trimmed }])
      if (!firstMessage) setFirstMessage(trimmed)
      try {
        const res = await clarifyItinerary(trimmed, slots, ask.signal)
        const merged = mergeSlots(slots, res.slots)
        setSlots(merged)
        setReady(slotsReady(merged))
        const reply = assistantReply(res.ready, res.question ?? null, res.options)
        if (reply) setMessages((list) => [...list, { ...reply, id: nextMessageId() }])
      } catch (err) {
        if (ask.signal.aborted) return
        if (isUnauthorized(err)) {
          setNeedsLogin(true)
          setError('登录后继续规划，你已填的想法会保留。')
          return
        }
        setError(
          isOfflineError(err)
            ? '暂时连不上规划服务，稍后再说一句试试。'
            : err instanceof Error
              ? err.message
              : '没听清，再说一次试试。',
        )
      } finally {
        if (controller.current === ask) controller.current = null
        setSending(false)
      }
    },
    [slots, sending, firstMessage],
  )

  const updateSlots = useCallback(
    (patch: Partial<IntakeSlots>) => {
      const merged = { ...slots, ...patch }
      setSlots(merged)
      setReady(slotsReady(merged))
    },
    [slots],
  )

  const reset = useCallback(() => {
    controller.current?.abort()
    controller.current = null
    clearIntake()
    setMessages([GREETING])
    setSlots({})
    setFirstMessage('')
    setReady(false)
    setError('')
    setNeedsLogin(false)
    setSending(false)
  }, [])

  return { messages, slots, firstMessage, ready, sending, error, needsLogin, send, updateSlots, reset }
}

export type IntakeChat = ReturnType<typeof useIntakeChat>

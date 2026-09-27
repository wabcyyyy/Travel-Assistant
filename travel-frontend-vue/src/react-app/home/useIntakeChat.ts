import { useCallback, useEffect, useRef, useState } from 'react'
import { clarifyItinerary, isOfflineError } from '../../api/sinan'
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
    setSending(false)
  }, [])

  return { messages, slots, firstMessage, ready, sending, error, send, updateSlots, reset }
}

export type IntakeChat = ReturnType<typeof useIntakeChat>

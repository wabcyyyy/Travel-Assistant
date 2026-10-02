import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { interpretImageIntent, isUnauthorized } from '../../api/sinan'
import type { GenerateInput } from '../../api/sinan'
import { fallbackCities } from '../data'
import { loginRedirect, navigate } from '../router'
import { ChatComposer, composeDraft, imageFeedbackText } from '../shared/ChatComposer'
import { Icon } from '../shared/Icon'
import { INTAKE_PREFERENCES, seedFromQuery, slotsReady, toGenerateInput } from './intakeSlots'
import type { IntakeSlots } from './intakeSlots'
import { useIntakeChat } from './useIntakeChat'

/** 对话式创建壳：clarify 多轮收集（chips 点选即答），ready 后就地确认再开工。
 * 集齐 city/days/persons 前不出「开始规划」——不猜测、不零追问直出。 */
export function ChatIntake({
  query,
  disabled,
  onStart,
}: {
  query: URLSearchParams
  disabled?: boolean
  onStart: (input: GenerateInput) => void
}) {
  const chat = useIntakeChat()
  const [draft, setDraft] = useState(() => seedFromQuery(query))
  const [imageBusy, setImageBusy] = useState(false)
  const [imageNotice, setImageNotice] = useState('')
  const [imageNeedsLogin, setImageNeedsLogin] = useState(false)
  const logRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [chat.messages.length, chat.sending])

  const locked = disabled || chat.sending
  const last = chat.messages[chat.messages.length - 1]
  const chips = !chat.ready && !locked && last?.role === 'assistant' && last.options?.length ? last.options : null

  const submit = () => {
    const text = draft
    setImageNotice('')
    setImageNeedsLogin(false)
    setDraft('')
    void chat.send(text)
  }

  // 图片→一句话：识别结果回填草稿交用户编辑后照常 send（不自动发送）；
  // 401 沿用 needsLogin 通道给登录入口，其余错误走 intake 既有提示位
  const handleImage = async (file: File) => {
    setImageNotice('')
    setImageNeedsLogin(false)
    setImageBusy(true)
    try {
      const res = await interpretImageIntent(file)
      setDraft((current) => composeDraft(current, res.suggestedMessage, 800))
    } catch (err) {
      if (isUnauthorized(err)) {
        setImageNeedsLogin(true)
        setImageNotice('登录后就能识别图片，你已填的想法会保留。')
        return
      }
      setImageNotice(imageFeedbackText(err))
    } finally {
      setImageBusy(false)
    }
  }

  return <div className="intake" aria-label="对话式行程创建">
    <div className="intake-head">
      <span className="intake-symbol"><Icon name="compass" size={22} /></span>
      <div><h2>说一句话，行程就有了</h2><p>信息不够司南会问你，不会瞎猜。</p></div>
    </div>
    <div className="intake-log" role="log" aria-live="polite" ref={logRef}>
      {chat.messages.map((msg) => (
        <div key={msg.id} className={`intake-msg is-${msg.role}`}>{msg.text}</div>
      ))}
      {chat.sending && <div className="intake-msg is-assistant is-typing"><span className="chat-thinking" aria-label="司南正在想"><i /><i /><i /></span></div>}
      {chips && <div className="intake-chips">
        {chips.map((option) => <button key={option} type="button" onClick={() => void chat.send(option)}>{option}</button>)}
      </div>}
    </div>
    {chat.error && <p className="planning-retry-hint" role="alert">{chat.error}</p>}
    {imageNotice && <p className="planning-retry-hint" role="alert">{imageNotice}</p>}
    {(chat.needsLogin || imageNeedsLogin) && (
      <button className="button button-primary" type="button" onClick={() => navigate(loginRedirect())}>
        登录并继续<Icon name="arrow" size={16} />
      </button>
    )}
    {chat.ready && !disabled
      ? <IntakeConfirm
          slots={chat.slots}
          busy={chat.sending}
          onSlots={chat.updateSlots}
          onReset={chat.reset}
          onStart={() => onStart(toGenerateInput(chat.slots, chat.firstMessage))}
        />
      : <ChatComposer
          className="intake-composer"
          value={draft}
          onChange={setDraft}
          onSend={submit}
          placeholder="例如：国庆想去成都玩 4 天，两个人，预算 3000"
          ariaLabel="说说你的旅行想法"
          maxLength={800}
          disabled={locked}
          onImage={handleImage}
          imageBusy={imageBusy}
          onNotice={setImageNotice}
        />}
  </div>
}

function IntakeConfirm({
  slots,
  busy,
  onSlots,
  onReset,
  onStart,
}: {
  slots: IntakeSlots
  busy: boolean
  onSlots: (patch: Partial<IntakeSlots>) => void
  onReset: () => void
  onStart: () => void
}) {
  const preferences = slots.preferences || []
  const custom = preferences.filter((item) => !INTAKE_PREFERENCES.includes(item))
  const toggle = (item: string) => {
    onSlots({
      preferences: preferences.includes(item) ? preferences.filter((value) => value !== item) : [...preferences, item],
    })
  }
  const number = (key: 'days' | 'persons' | 'budget') => (event: ChangeEvent<HTMLInputElement>) => {
    const raw = event.target.value
    const parsed = Number(raw)
    onSlots({ [key]: raw !== '' && Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : undefined })
  }

  return <div className="intake-confirm">
    <div className="intake-confirm-head">
      <h3>出发前确认</h3>
      <button className="text-action" type="button" onClick={onReset}>重新说</button>
    </div>
    <div className="intake-grid">
      <label>目的地<input value={slots.city || ''} maxLength={80} list="intake-cities" onChange={(event) => onSlots({ city: event.target.value })} /></label>
      <label>天数<input type="number" min={1} max={7} value={slots.days ?? ''} onChange={number('days')} /></label>
      <label>人数<input type="number" min={1} max={20} value={slots.persons ?? ''} onChange={number('persons')} /></label>
      <label>出发日期（可选）<input type="date" value={slots.start_date || ''} onChange={(event) => onSlots({ start_date: event.target.value || undefined })} /></label>
      <label>出发城市（可选）<input value={slots.origin_city || ''} maxLength={80} placeholder="查航班用" onChange={(event) => onSlots({ origin_city: event.target.value || undefined })} /></label>
      <label>全程预算（可选）<input type="number" min={1} placeholder="例如 3000" value={slots.budget ?? ''} onChange={number('budget')} /></label>
    </div>
    <datalist id="intake-cities">{fallbackCities.map((city) => <option key={city} value={city} />)}</datalist>
    <div className="intake-prefs" aria-label="旅行偏好">
      {INTAKE_PREFERENCES.map((item) => (
        <button key={item} type="button" aria-pressed={preferences.includes(item)} onClick={() => toggle(item)}>{item}</button>
      ))}
      {custom.map((item) => (
        <button key={item} type="button" className="is-custom" aria-pressed="true" title="点选移除" onClick={() => toggle(item)}>{item}</button>
      ))}
    </div>
    <button className="button button-primary intake-start" type="button" disabled={busy || !slotsReady(slots)} onClick={onStart}>
      就这样，开始规划<Icon name="arrow" size={16} />
    </button>
  </div>
}

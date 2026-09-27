import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import type { ItineraryChatMessage } from '../../types/chat'
import type { DayPlan, HotelOption, ItineraryDetail } from '../../types/itinerary'
import { Icon } from '../shared/Icon'
import { activeActionIndex, draftChanges, hotelDefaultSelection, pendingActionSummary, unverifiedNames } from './chatDraft'
import { useTripChat } from './useTripChat'

/** 对话编排主面（CH3）：对话在左、行程保持可见；草稿卡/确认卡长在对话流内。
 * 选择型 UI（酒店候选）保留结构化点选，不做全屏对话。 */
export function ChatPanel({
  itineraryId,
  dayList,
  onApplied,
  onReconcile,
}: {
  itineraryId: number
  dayList: DayPlan[]
  onApplied: (detail: ItineraryDetail) => void
  onReconcile: () => void
}) {
  const chat = useTripChat(itineraryId, onApplied, onReconcile)
  const [draft, setDraft] = useState('')
  const logRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [chat.msgs.length, chat.sending])

  const submit = () => {
    const text = draft
    setDraft('')
    void chat.send(text)
  }
  const activeIdx = activeActionIndex(chat.msgs)

  return <section className="chat-panel" aria-label="行程对话编排">
    <div className="chat-panel-head">
      <span className="chat-symbol"><Icon name="compass" size={20} /></span>
      <div><h2>对话编排</h2><p>想改什么直接说，确认后才会落图。</p></div>
    </div>
    <div className="chat-log" role="log" aria-live="polite" ref={logRef}>
      {!chat.loaded && <div className="chat-empty">正在载入对话…</div>}
      {chat.loaded && !chat.msgs.length && (
        <div className="chat-empty">还没有对话。试试「第二天加个博物馆」或「换个舒服点的酒店」。</div>
      )}
      {chat.msgs.map((msg, index) => {
        const isUser = msg.role === 'user'
        const isDraft = index === activeIdx
        return (
          <div key={msg.id ?? `idx-${index}`} className={isUser ? 'chat-msg is-user' : 'chat-msg is-ai'}>
            <div className="chat-bubble">{msg.content || (chat.sending ? '司南正在想…' : '')}</div>
            {isDraft && (
              <DraftCard
                msg={msg}
                dayList={dayList}
                applying={chat.applying}
                onApply={() => void chat.applyDraft()}
                onApplyHotel={(option, roomType, dayNos) => void chat.applyHotel(option, roomType, dayNos)}
              />
            )}
          </div>
        )
      })}
    </div>
    {chat.notice && (
      <p className="chat-notice" role="alert">
        {chat.notice}
        <button type="button" aria-label="关闭提示" onClick={() => chat.setNotice('')}><Icon name="close" size={13} /></button>
      </p>
    )}
    <form className="chat-composer" onSubmit={(event: ChangeEvent<HTMLFormElement> | undefined) => { event?.preventDefault(); submit() }}>
      <input
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder="例如：第二天加个博物馆"
        aria-label="对行程说话"
        maxLength={2000}
        disabled={chat.sending}
      />
      <button type="submit" className="button button-primary" disabled={chat.sending || !draft.trim()}>
        发送<Icon name="arrow" size={15} />
      </button>
    </form>
  </section>
}

/** 草稿卡/确认卡：挂在带草稿的 AI 消息下方（导出仅供单测静态渲染）。 */
export function DraftCard({
  msg,
  dayList,
  applying,
  onApply,
  onApplyHotel,
}: {
  msg: ItineraryChatMessage
  dayList: DayPlan[]
  applying: boolean
  onApply: () => void
  onApplyHotel: (option: HotelOption, roomType: string, dayNos: number[]) => void
}) {
  const changes = msg.plans?.length ? draftChanges(dayList, msg.plans) : []
  const unverified = msg.plans?.length ? unverifiedNames(dayList, msg.plans) : []
  return <div className="chat-draft">
    {msg.requiresConfirmation && msg.pendingAction && (
      <div className="chat-confirm" role="status">
        <strong>需要你确认</strong>
        <span>{pendingActionSummary(msg.pendingAction)}——从下方候选中点选即确认生效。</span>
      </div>
    )}
    {changes.length > 0 && <ul className="chat-diff">{changes.map((line) => <li key={line}>{line}</li>)}</ul>}
    {unverified.length > 0 && <p className="chat-unverified">这些点位 AI 没拿到坐标，出发前请自行核实：{unverified.join('、')}</p>}
    {msg.hotelOptions?.length ? (
      <HotelChooser options={msg.hotelOptions} tripDays={dayList.length} applying={applying} onApply={onApplyHotel} />
    ) : null}
    {msg.plans?.length ? (
      <button className="button button-primary chat-apply" type="button" disabled={applying} onClick={onApply}>
        {applying ? '正在应用…' : '应用到行程'}
      </button>
    ) : null}
  </div>
}

function HotelChooser({
  options,
  tripDays,
  applying,
  onApply,
}: {
  options: HotelOption[]
  tripDays: number
  applying: boolean
  onApply: (option: HotelOption, roomType: string, dayNos: number[]) => void
}) {
  const [idx, setIdx] = useState(0)
  const option = options[Math.min(idx, options.length - 1)]
  const [selection, setSelection] = useState(() => hotelDefaultSelection(option, tripDays))
  useEffect(() => {
    setSelection(hotelDefaultSelection(option, tripDays))
  }, [option, tripDays])

  return <div className="chat-hotels">
    {options.length > 1 && (
      <div className="chat-hotel-tabs" role="tablist" aria-label="酒店候选">
        {options.map((item, index) => (
          <button key={item.id ?? index} type="button" role="tab" aria-selected={index === idx} className={index === idx ? 'active' : ''} onClick={() => setIdx(index)}>
            {item.hotelName || `候选 ${index + 1}`}
          </button>
        ))}
      </div>
    )}
    <div className="chat-hotel-body">
      <div className="chat-hotel-line"><strong>{option.hotelName}</strong><span>{option.tier} · ￥{option.totalPrice ?? '--'}{option.nights ? ` / ${option.nights} 晚` : ''}{option.withinBudget === false ? ' · 超预算' : ''}</span></div>
      {option.roomTypes?.length ? (
        <label className="chat-hotel-room">房型
          <select value={selection.roomType} onChange={(event) => setSelection((current) => ({ ...current, roomType: event.target.value }))}>
            {option.roomTypes.map((room) => (
              <option key={room.roomName} value={room.roomName}>
                {room.roomName}{room.breakfast ? ' · 含早' : ''}（￥{room.totalPrice ?? room.nightlyPrice ?? '--'}）
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <div className="chat-hotel-foot">
        <span>入住晚次：第 {selection.dayNos.join('、第 ') || '--'} 晚</span>
        <button className="button button-primary" type="button" disabled={applying || !selection.roomType} onClick={() => onApply(option, selection.roomType, selection.dayNos)}>
          {applying ? '正在应用…' : '确认入住'}
        </button>
      </div>
    </div>
  </div>
}

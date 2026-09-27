import { loginRedirect, navigate } from '../router'
import { Icon } from '../shared/Icon'
import type { useHomePlanning } from './useHomePlanning'

const steps = ['理解想法', '查找信息', '安排路线', '核对行程']

/** 生成期实时预览：天数从壳里长出来，已排好的天亮内容、没排的显示占位。
 * 数据来自 SSE + 轮询对账的 draft（useHomePlanning），无需独立请求。 */
export function TripPreview({ planning }: { planning: ReturnType<typeof useHomePlanning> }) {
  const { status, message, progress, draft, busy } = planning
  if (status === 'idle') {
    return <aside className="trip-preview is-empty" aria-label="行程预览">
      <Icon name="compass" size={26} />
      <p>开聊之后，<br />每天的安排会在这里实时长出来。</p>
    </aside>
  }
  return <aside className="trip-preview" aria-label="行程实时预览" aria-busy={busy}>
    <div className="planning-result-heading">
      <span aria-hidden="true" className={busy ? 'loading-orbit' : 'planning-result-icon'}>
        {!busy && <Icon name={status === 'ready' ? 'check' : 'alert'} size={19} />}
      </span>
      <p role={status === 'error' || status === 'login' ? 'alert' : 'status'}>{message}</p>
    </div>
    {status === 'login' && <button className="button button-primary" type="button" onClick={() => navigate(loginRedirect())}>登录并继续<Icon name="arrow" size={16} /></button>}
    {busy && <ol className="planning-stages">
      {steps.map((step, index) => (
        <li key={step} className={index <= progress ? 'is-active' : ''} aria-current={index === progress ? 'step' : undefined}>
          {index < progress ? <Icon name="check" size={14} /> : <span className="planning-stage-mark" />}{step}
        </li>
      ))}
    </ol>}
    {draft && draft.days > 0 && <ol className="trip-preview-days">
      {Array.from({ length: draft.days }, (_, index) => index + 1).map((dayNo) => {
        const day = draft.dayList.find((item) => item.dayNo === dayNo)
        const done = Boolean(day && day.items.length > 0)
        return <li key={dayNo} className={done ? 'is-done' : 'is-pending'}>
          <span className="trip-preview-dayno">第 {dayNo} 天</span>
          {done
            ? <div className="trip-preview-daybody">
                <strong>{day.theme || '当天安排'}</strong>
                <small>{day.items.slice(0, 4).map((item) => item.poiName).join(' · ')}</small>
              </div>
            : <div className="trip-preview-daybody">
                <strong>安排中…</strong>
                <small>{day?.generationStatus === 'RUNNING' ? '司南正在排这一天的路线' : '排在队列里，马上就好'}</small>
              </div>}
        </li>
      })}
    </ol>}
    {status === 'error' && <p className="planning-retry-hint">对话里的信息还在，回到左边再点一次「开始规划」即可。</p>}
    {status === 'ready' && draft && (
      <button className="button button-primary" type="button" onClick={() => navigate(`/trips/${draft.id}`)}>
        查看完整行程<Icon name="arrow" size={16} />
      </button>
    )}
  </aside>
}

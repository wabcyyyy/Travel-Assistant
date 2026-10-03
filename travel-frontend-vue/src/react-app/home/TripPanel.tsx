import type { GenerateInput } from '../../api/sinan'
import { loginRedirect, navigate } from '../router'
import { Icon } from '../shared/Icon'
import { SLOT_DEFS, slotDisplayValue, slotIsFilled, toGenerateInput } from './intakeSlots'
import { SlotChecklist } from './SlotChecklist'
import { TripBoard } from './TripBoard'
import type { useHomePlanning } from './useHomePlanning'
import type { IntakeChat } from './useIntakeChat'

const STEPS = ['补信息', '确认', '生成中', '完成'] as const

/** 生成期四段阶段进度：SSE 推进 planning.progress 0→4（消费侧在
 * useHomePlanning.monitor，本组件只读展示）。 */
const PLANNING_STAGES = ['理解想法', '查找信息', '安排路线', '核对行程']

/** active 右栏的面板态：collecting/confirm、generating 与 pending/error/login
 * 兜底态在本组件落位（生成态+兜底态原 home/TripPreview.tsx 已就地迁入）；done 态
 * （ready）接线 TripBoard 预览板（卡5，拍板①：留在首页看预览）。 */
type TripPanelState = 'collecting' | 'confirm' | 'generating' | 'ready' | 'pending' | 'error' | 'login'

/** 四步 stepper（PLAN §3.1）的当前步：error/login 回到「确认」等重开，
 * pending 卡在「生成中」，ready 才算「完成」。 */
const STEP_INDEX: Record<TripPanelState, number> = {
  collecting: 0,
  confirm: 1,
  generating: 2,
  pending: 2,
  ready: 3,
  error: 1,
  login: 1,
}

/** active 态右栏容器：常驻四步 stepper + 当态内容区。生成压过对话态
 * （planning.busy 优先），status idle 时由对话就绪度分流收集/确认。 */
export function TripPanel({ planning, chat, onStart }: {
  planning: ReturnType<typeof useHomePlanning>
  chat: IntakeChat
  onStart: (input: GenerateInput) => void
}) {
  // creating/planning 用 status 判（语义同 planning.busy，但能让 TS 收窄到兜底态）
  const state: TripPanelState =
    planning.status === 'creating' || planning.status === 'planning'
      ? 'generating'
      : planning.status === 'idle'
        ? (chat.ready ? 'confirm' : 'collecting')
        : planning.status
  const step = STEP_INDEX[state]
  return <section className="trip-panel" aria-label="行程工作面板" aria-busy={planning.busy}>
    <ol className="trip-steps" aria-label="规划进度">
      {STEPS.map((label, index) => (
        <li key={label} className={index < step ? 'is-done' : index === step ? 'is-current' : ''} aria-current={index === step ? 'step' : undefined}>
          {index < step ? <Icon name="check" size={13} /> : <span className="trip-step-dot" aria-hidden="true" />}
          {label}
        </li>
      ))}
    </ol>
    {state === 'collecting' && <SlotChecklist slots={chat.slots} />}
    {state === 'confirm' && <ConfirmSummary chat={chat} onStart={onStart} />}
    {/* done 态（ready 且 draft 可用）上预览板；ready 但 draft 异常缺失的退化情形
        留在 PlanningPreview 露出结果文案，不白屏 */}
    {state === 'ready' && planning.draft && planning.draft.days > 0
      ? <TripBoard draft={planning.draft} />
      : (state === 'generating' || state === 'ready' || state === 'pending' || state === 'error' || state === 'login')
        && <PlanningPreview planning={planning} />}
  </section>
}

/** 生成/兜底态内容区（PLAN §3.4/§3.6，原 home/TripPreview.tsx 卡4 就地迁入）：
 * 四段阶段进度（ol.planning-stages 是金路径 E2E 契约类，不许改名）+ 逐日生长卡
 * （已排好的天亮 theme+前 4 个 POI，未排的天骨架占位），generating/pending/error/login
 * 同容器落位；ready+draft 已由上面的 TripBoard 接走，此处仅剩 draft 异常缺失的
 * 退化兜底（只露结果文案，不再有「查看完整行程」CTA——那条进预览板了）。
 * 数据来自 SSE + 轮询对账的 draft（useHomePlanning），无需独立请求。 */
function PlanningPreview({ planning }: { planning: ReturnType<typeof useHomePlanning> }) {
  const { status, message, progress, draft, busy } = planning
  return <aside className="trip-preview" aria-label="行程实时预览" aria-busy={busy}>
    <div className="planning-result-heading">
      <span aria-hidden="true" className={busy ? 'loading-orbit' : 'planning-result-icon'}>
        {!busy && <Icon name={status === 'ready' ? 'check' : 'alert'} size={19} />}
      </span>
      <p role={status === 'error' || status === 'login' ? 'alert' : 'status'}>{message}</p>
    </div>
    {status === 'login' && <button className="button button-primary" type="button" onClick={() => navigate(loginRedirect())}>登录并继续<Icon name="arrow" size={16} /></button>}
    {busy && <ol className="planning-stages">
      {PLANNING_STAGES.map((stage, index) => (
        <li key={stage} className={index <= progress ? 'is-active' : ''} aria-current={index === progress ? 'step' : undefined}>
          {index < progress ? <Icon name="check" size={14} /> : <span className="planning-stage-mark" />}{stage}
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
  </aside>
}

/** confirm 态摘要卡（PLAN §3.3）：全部槽位 chips 汇总 + 同义快捷开工。
 * 确认表单仍在左侧对话卡内（IntakeConfirm 现状不动）；按钮 class 特意不叫
 * .intake-start——那是金路径 E2E 指向左卡确认钮的选择器契约，不能出第二个。 */
function ConfirmSummary({ chat, onStart }: { chat: IntakeChat; onStart: (input: GenerateInput) => void }) {
  return <div className="trip-confirm">
    <div className="trip-confirm-chips" aria-label="已收集的信息">
      {SLOT_DEFS.filter((def) => slotIsFilled(chat.slots, def.key)).map((def) => (
        <span key={def.key}>{def.label} · {slotDisplayValue(chat.slots, def.key)}</span>
      ))}
    </div>
    <p className="trip-confirm-hint">信息齐了，回左侧确认或直接开工。</p>
    <button className="button button-primary panel-start" type="button" onClick={() => onStart(toGenerateInput(chat.slots, chat.firstMessage))}>
      就这样，开始规划<Icon name="arrow" size={16} />
    </button>
  </div>
}

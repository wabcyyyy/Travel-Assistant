import { Icon } from '../shared/Icon'
import { SLOT_DEFS, slotDisplayValue, slotIsFilled, slotProgress } from './intakeSlots'
import type { IntakeSlots } from './intakeSlots'

/** collecting 态右栏：信息收集进度（PLAN 2026-10-02 §3.2）。必填三项随对话
 * 「长出来」——未填=空态圆点、已填=✓+当前值；可选项小字排列、已填亮值；
 * nextRequiredKey 高亮提示接下来聊什么；进度条 + 「还差 N 项就能开工」。
 * 整块 role="status"，槽位变化对读屏可感知。 */
export function SlotChecklist({ slots }: { slots: IntakeSlots }) {
  const { requiredFilled, requiredTotal, nextRequiredKey } = slotProgress(slots)
  const remaining = requiredTotal - requiredFilled
  return <div className="slot-checklist" role="status" aria-label="信息收集进度">
    <div className="slot-progress">
      <div className="slot-progress-track" aria-hidden="true">
        <div className="slot-progress-fill" style={{ width: `${Math.round((requiredFilled / requiredTotal) * 100)}%` }} />
      </div>
      <p className="slot-progress-text">
        {remaining > 0
          ? <><strong>{requiredFilled}/{requiredTotal}</strong> 还差 {remaining} 项就能开工</>
          : '必填信息齐了，回左侧确认就能开工'}
      </p>
    </div>
    <ul className="slot-required" aria-label="必填信息">
      {SLOT_DEFS.filter((def) => def.required).map((def) => {
        const filled = slotIsFilled(slots, def.key)
        return <li key={def.key} className={filled ? 'is-filled' : def.key === nextRequiredKey ? 'is-next' : ''}>
          {filled ? <Icon name="check" size={14} /> : <span className="slot-dot" aria-hidden="true" />}
          <span>{def.label}</span>
          {filled && <span className="slot-value">{slotDisplayValue(slots, def.key)}</span>}
        </li>
      })}
    </ul>
    <div className="slot-optional" aria-label="可选信息，想到就补充">
      {SLOT_DEFS.filter((def) => !def.required).map((def) => (
        <span key={def.key} className={slotIsFilled(slots, def.key) ? 'is-filled' : ''}>
          {def.label}
          {slotIsFilled(slots, def.key) && <> · {slotDisplayValue(slots, def.key)}</>}
        </span>
      ))}
    </div>
  </div>
}

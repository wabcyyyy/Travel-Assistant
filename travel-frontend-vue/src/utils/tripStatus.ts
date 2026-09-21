import type { ItinerarySummary } from '../types/itinerary'

/** 行程状态 → 中文标签（列表/首页/详情头部共用同一口径，避免多处漂移）。 */
export function tripStatusLabel(row: Pick<ItinerarySummary, 'archived' | 'status'>): string {
  if (row.archived) return '已归档'
  return row.status === 2 ? '已生成' : row.status === 1 ? '生成中' : '生成失败'
}

export type TripStatusTone = 'success' | 'warning' | 'danger' | 'neutral'

export function tripStatusTone(row: Pick<ItinerarySummary, 'archived' | 'status'>): TripStatusTone {
  if (row.archived) return 'neutral'
  return row.status === 2 ? 'success' : row.status === 1 ? 'warning' : 'danger'
}

/** 本地日历日 `YYYY-MM-DD`（不是 UTC 日）。
 *
 * 与后端日期字符串同形，可直接做字典序比较；刻意不用
 * `new Date().toISOString().slice(0,10)` —— 那个在 UTC+8 的每天 00:00–07:59
 * 还是"昨天"，会让今天出发的行程显示成"1 天后"、并把昨天结束的行程
 * 留在"即将出发"里。
 */
export function localTodayISO(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** 距出发还有几天；无日期返回 null，已出发返回 0。 */
export function daysUntil(startDate?: string | null, today = new Date()): number | null {
  if (!startDate) return null
  const start = new Date(`${startDate}T00:00:00`)
  if (Number.isNaN(start.getTime())) return null
  // 两端都取本地零点：start 用的是无时区后缀的 `T00:00:00`（=本地），
  // base 若走 ISO 就成了 UTC 日，两者不同源就会差一天。
  const base = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  return Math.max(0, Math.round((start.getTime() - base.getTime()) / 86_400_000))
}

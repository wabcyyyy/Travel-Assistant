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

/** 距出发还有几天；无日期返回 null，已出发返回 0。 */
export function daysUntil(startDate?: string | null, today = new Date()): number | null {
  if (!startDate) return null
  const start = new Date(`${startDate}T00:00:00`)
  if (Number.isNaN(start.getTime())) return null
  const base = new Date(today.toISOString().slice(0, 10) + 'T00:00:00')
  return Math.max(0, Math.round((start.getTime() - base.getTime()) / 86_400_000))
}

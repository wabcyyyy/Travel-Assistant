/**
 * DayListCard 的纯逻辑（G-2.6 前端长尾：自巨头组件提取，可独立单测）。
 *
 * 只放无副作用的映射 / 清洗 / 计算函数：不碰 store、不发请求、不操作 DOM。
 * 行为以单测锁定（day-card/shared.test.ts）——拆分或重构时先看测试。
 */

import { BedDouble, Camera, MapPin, TrainFront, UtensilsCrossed } from 'lucide-vue-next'
import type { BackupPlanEntry, DayPlan, PhotoSpotEntry, TripItem } from '../../../types/itinerary'

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

/** 日头副行：M月D日 · 周X（travelDate 缺省/非法时回落「第 N 天」） */
export function dayMetaText(day: DayPlan): string {
  if (day.travelDate) {
    const date = new Date(day.travelDate)
    if (!Number.isNaN(date.getTime())) {
      return `${date.getMonth() + 1}月${date.getDate()}日 · ${WEEKDAYS[date.getDay()]}`
    }
  }
  return `第 ${day.dayNo} 天`
}

/** 天标题：主题优先；无主题用「首 → 尾」点位串；空行程「暂无安排」 */
export function dayTitle(d: DayPlan): string {
  if (d.theme) return d.theme
  const items = d.items || []
  if (!items.length) return '暂无安排'
  const first = items[0]?.poiName || ''
  const last = items.length > 1 ? items[items.length - 1]?.poiName || '' : ''
  return last && last !== first ? `${first} → ${last}` : first
}

/** 时间展示统一 HH:mm（数据侧为 HH:mm:ss） */
export function formatTime(value?: string | null): string {
  return typeof value === 'string' ? value.slice(0, 5) : ''
}

/** day-tint 消费（v2.6 §19.4）：D1–D8 循环取色变量名 */
export function dayTintVar(dayNo: number): string {
  return `var(--lp-day-${((dayNo - 1) % 8) + 1})`
}

// ---------- 条目类型 ----------

const TYPE_LABEL: Record<string, string> = {
  attraction: '景点',
  food: '美食',
  hotel: '酒店',
  transport: '交通',
}

export function typeLabel(type: string): string {
  return TYPE_LABEL[type] || type
}

/** 行内分类小图标（TREK 行解剖：名称前 10px 分类图标）；未知类型回退地图钉 */
export function typeIcon(type: string): unknown {
  const TYPE_ICON: Record<string, unknown> = { attraction: Camera, food: UtensilsCrossed, hotel: BedDouble, transport: TrainFront }
  return TYPE_ICON[type] || MapPin
}

/** 可优化活动项计数口径（与后端 optimize 的 400 门槛一致：attraction / food） */
export function isOptimizableItem(item: TripItem): boolean {
  return item.itemType === 'attraction' || item.itemType === 'food'
}

/** 天级小计：餐饮/景点按人数，酒店按房间数（每房 2 人，至少 1 间） */
export function dayTotalAmountOf(items: TripItem[] | undefined, persons: number): number {
  const headcount = persons < 1 ? 1 : persons
  const roomCount = Math.max(Math.ceil(headcount / 2), 1)
  return (items || []).reduce((sum, item) => {
    if (item.cost == null) return sum
    return sum + item.cost * (item.itemType === 'hotel' ? roomCount : headcount)
  }, 0)
}

// ---------- 叙事块清洗（内联提示卡数据，源自 DayNarrativePanel 拆出） ----------

export function cleanPracticalNotes(notes: string[] | undefined): string[] {
  return (notes || []).map((n) => n.trim()).filter(Boolean)
}

export function cleanPhotoSpots(spots: PhotoSpotEntry[] | undefined): PhotoSpotEntry[] {
  return (spots || []).filter((s) => (s.name || s.title || '').trim())
}

export function cleanBackupRules(rules: BackupPlanEntry[] | undefined): BackupPlanEntry[] {
  return (rules || []).filter(
    (r) => (r.if || r.name || r.title || '').trim() || (r.action || '').trim(),
  )
}

export function hasAnyTips(
  notes: string[],
  spots: PhotoSpotEntry[],
  rules: BackupPlanEntry[],
): boolean {
  return notes.length > 0 || spots.length > 0 || rules.length > 0
}

/** 机位点名：name / title 兼容历史数据（旧版仅名称） */
export function spotName(s: PhotoSpotEntry): string {
  return (s.name || s.title || '').trim()
}

/** 备用方案触发条件：if 优先，name/title 兼容历史数据 */
export function ruleIf(r: BackupPlanEntry): string {
  return (r.if || '').trim()
}

/** 建议方案的点位名列表（去空） */
export function optionNames(items: { poiName?: string }[] | undefined): string[] {
  return (items || [])
    .map((item) => item.poiName)
    .filter((name): name is string => Boolean(name))
}

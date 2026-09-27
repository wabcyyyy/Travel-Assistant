/** 对话式创建的槽位模型与派生逻辑（纯函数，零依赖可单测）。
 *
 * 创建会话是短生命周期客户端状态：槽位由前端持有（sessionStorage），服务端
 * /clarify 纯解析不落库。键名与后端抽取口径一致（snake_case）。刷新可续，
 * 关闭标签页即弃——不做无壳草稿（itinerary_chat_message 外键指向 itinerary）。
 */
import type { GenerateInput } from '../../api/sinan'
import { inspirationTemplates } from '../data'

export const INTAKE_STORAGE_KEY = 'sinan-intake-v1'

export const INTAKE_PREFERENCES = ['美食', '自然风光', '人文历史', '慢节奏', '少走路', '亲子友好']

export const READY_TEXT = '信息齐了！下面确认一下，要改哪项直接点。'

export interface IntakeSlots {
  city?: string
  days?: number
  persons?: number
  start_date?: string
  origin_city?: string
  budget?: number
  hotel_tier?: string
  preferences?: string[]
}

export interface IntakeMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  options?: string[]
}

export interface IntakeState {
  messages: IntakeMessage[]
  slots: IntakeSlots
  firstMessage: string
}

export const GREETING: IntakeMessage = {
  id: 'greeting',
  role: 'assistant',
  text: '想去哪儿玩？大致天数、人数，一并说给司南听～',
}

/** 就绪门：与后端 _REQUIRED 三件套同口径，days 上限 7 不在前端放宽。 */
export function slotsReady(slots: IntakeSlots): boolean {
  return Boolean(slots.city?.trim()) && isDayCount(slots.days) && isPersonCount(slots.persons)
}

function isDayCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 7
}

function isPersonCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 20
}

/** 合并后端抽取结果：只认得动的键，形状不对的一律丢弃（槽位结构由前端决定）。 */
export function mergeSlots(current: IntakeSlots, incoming: Record<string, unknown> | undefined | null): IntakeSlots {
  const next: IntakeSlots = { ...current }
  if (!incoming) return next
  if (typeof incoming.city === 'string' && incoming.city.trim()) next.city = incoming.city.trim().slice(0, 80)
  if (typeof incoming.origin_city === 'string' && incoming.origin_city.trim()) {
    next.origin_city = incoming.origin_city.trim().slice(0, 80)
  }
  if (typeof incoming.start_date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(incoming.start_date)) {
    next.start_date = incoming.start_date
  }
  if (typeof incoming.hotel_tier === 'string' && incoming.hotel_tier.trim()) next.hotel_tier = incoming.hotel_tier
  const days = toInt(incoming.days)
  if (days !== null) next.days = days
  const persons = toInt(incoming.persons)
  if (persons !== null) next.persons = persons
  const budget = toInt(incoming.budget)
  if (budget !== null && budget > 0) next.budget = budget
  if (Array.isArray(incoming.preferences)) {
    const items = incoming.preferences.filter((item): item is string => typeof item === 'string' && item.trim() !== '')
    if (items.length) next.preferences = items.slice(0, 8)
  }
  return next
}

function toInt(value: unknown): number | null {
  const n = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : Number.NaN
  return Number.isFinite(n) ? Math.trunc(n) : null
}

/** 槽位 → 生成请求（调用前已过 slotsReady 门，此处数值兜底）。
 * stayNights=天数-1、endDate 随天数推导，与旧表单口径一致；
 * intent 带首句原话——建壳随 V10 落库，恢复续跑时读得回。 */
export function toGenerateInput(slots: IntakeSlots, firstMessage: string): GenerateInput {
  const days = Math.min(Math.max(Math.trunc(slots.days || 0), 1), 7)
  const start = slots.start_date
  return {
    city: (slots.city || '').trim().slice(0, 80),
    days,
    persons: Math.min(Math.max(Math.trunc(slots.persons || 0), 1), 20),
    stayNights: Math.max(days - 1, 0),
    startDate: start || undefined,
    endDate: start ? addDays(start, days - 1) : undefined,
    originCity: slots.origin_city?.trim().slice(0, 80) || undefined,
    budget: slots.budget && slots.budget > 0 ? slots.budget : undefined,
    intent: firstMessage.trim().slice(0, 800) || undefined,
    preferences: (slots.preferences || []).filter((item) => item.trim() !== ''),
    hotelTier: slots.hotel_tier || undefined,
  }
}

function addDays(isoDate: string, offset: number): string {
  const [y, m, d] = isoDate.split('-').map(Number)
  const date = new Date(y, (m || 1) - 1, (d || 1) + offset)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** clarify 响应 → 下一句助手话术（id 由 hook 赋）：就绪出确认引导，缺槽出追问+chips。 */
export function assistantReply(ready: boolean, question: string | null, options: string[] | undefined): IntakeMessage | null {
  if (ready) return { id: '', role: 'assistant', text: READY_TEXT }
  if (question) return { id: '', role: 'assistant', text: question, options: options?.length ? [...options] : undefined }
  return null
}

export function loadIntake(): IntakeState | null {
  try {
    const raw = sessionStorage.getItem(INTAKE_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<IntakeState>
    if (!Array.isArray(parsed.messages)) return null
    const messages = parsed.messages.filter(
      (item): item is IntakeMessage =>
        Boolean(item) && (item.role === 'user' || item.role === 'assistant') && typeof item.text === 'string',
    )
    if (!messages.length) return null
    return {
      messages: messages.map((item, index) => ({
        id: item.id || `restored-${index}`,
        role: item.role,
        text: item.text,
        options: Array.isArray(item.options) ? item.options.filter((opt) => typeof opt === 'string') : undefined,
      })),
      slots: mergeSlots({}, parsed.slots),
      firstMessage: typeof parsed.firstMessage === 'string' ? parsed.firstMessage : '',
    }
  } catch {
    return null
  }
}

export function saveIntake(state: IntakeState): void {
  try {
    sessionStorage.setItem(INTAKE_STORAGE_KEY, JSON.stringify(state))
  } catch {
    // 存储不可用（隐私模式等）：对话退化为页内存态，刷新重来可接受
  }
}

export function clearIntake(): void {
  try {
    sessionStorage.removeItem(INTAKE_STORAGE_KEY)
  } catch {
    // ignore
  }
}

/** 入口预填首句草稿：攻略页「按这座城市规划」（/?city=）、灵感模板（/?template=）
 * 与直链 ?intent= 都汇到这里；只预填不自动发送（StrictMode 双挂载不双发）。 */
export function seedFromQuery(query: URLSearchParams): string {
  const intent = (query.get('intent') || '').trim()
  if (intent) return intent.slice(0, 800)
  const template = inspirationTemplates.find((item) => item.id === query.get('template'))
  if (template) return template.intent.slice(0, 800)
  const city = (query.get('city') || '').trim()
  if (!city) return ''
  const days = Number(query.get('days'))
  const dayText = Number.isInteger(days) && days >= 1 && days <= 7 ? `玩 ${days} 天` : ''
  return `想去${city.slice(0, 40)}${dayText}，帮我安排一下`
}

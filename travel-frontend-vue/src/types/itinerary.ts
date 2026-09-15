export type VerificationStatus = 'verified' | 'partially_verified' | 'unverified'
export type ValueKind = 'observed' | 'estimated' | 'generated'
export type FreshnessStatus = 'fresh' | 'stale' | 'unknown'
export type ReviewRequirement = 'none' | 'before_departure'

export interface FactEvidence {
  sourceRef?: string | null
  sourceUrl?: string | null
  provider?: string | null
  retrievedAt?: string | null
  expiresAt?: string | null
  verificationStatus: VerificationStatus
  valueKind: ValueKind
  freshnessStatus: FreshnessStatus
  reviewRequirement: ReviewRequirement
}

export interface QualityIssue {
  code: string
  path?: string | null
  message: string
}

export interface QualityReport {
  qualityStatus: 'DRAFT' | 'READY_WITH_WARNINGS' | 'READY' | 'BLOCKED' | 'STALE'
  qualityRuleVersion: string
  validatedAt?: string | null
  blockingIssues: QualityIssue[]
  warnings: QualityIssue[]
  metrics: Record<string, number>
}

export interface SourceRecord {
  sourceId: string
  storageSource?: string | null
  provider?: string | null
  publisher?: string | null
  sourceUrl?: string | null
  retrievedAt?: string | null
  publishedAt?: string | null
  expiresAt?: string | null
}

/** 封面署名（S1）：随图落库，详情/分享页展示用 */
export interface CoverCredit {
  author?: string | null
  authorUrl?: string | null
  license?: string | null
  source?: string | null
}

export interface TripItem {
  id?: number
  itemType: string
  poiName: string
  poiId?: string | null
  address?: string | null
  latitude?: number | null
  longitude?: number | null
  startTime?: string | null
  endTime?: string | null
  durationMin?: number | null
  cost?: number | null
  tag?: string | null
  remark?: string | null
  description?: string | null
  intro?: string | null
  image?: string | null
  openTime?: string | null
  imageUrl?: string | null
  /** 叙事字段（M3 生成契约补齐后生效）：该点与本趟意图的关系，value_kind=generated */
  whyThis?: string | null
  source?: string | null
  sourceUpdatedAt?: string | null
  verificationStatus?: VerificationStatus
  valueKind?: ValueKind
  freshnessStatus?: FreshnessStatus
  reviewRequirement?: ReviewRequirement
  factEvidence?: Record<string, FactEvidence>
  sortNo?: number
}

/** 逐日备选分支（M3 生成契约补齐后生效）：跨城 / 取舍时的方案分叉 */
export interface DayOption {
  label: string
  summary: string
  tradeoff: string
  items?: TripItem[]
}

/** 拍照点位条目（DayVO.photoSpots 为 Map 透传）：§4.1.2 PhotoSpot{name, tip, best_time}；
 * name/title 兼容历史数据（旧版仅名称）。 */
export interface PhotoSpotEntry {
  name?: string | null
  title?: string | null
  /** 拍摄角度 / 构图建议 */
  tip?: string | null
  /** 最佳时段（如 09:00-10:00，data mono 渲染） */
  bestTime?: string | null
}

/** 备选安排条目（DayVO.backupPlan 为 Map 透传）：§4.1.2 BackupRule{if, action}；
 * name/title 兼容历史数据（旧版仅名称）。 */
export interface BackupPlanEntry {
  name?: string | null
  title?: string | null
  /** 触发条件（如「雨天或体力不足」，斜体衬线渲染） */
  if?: string | null
  /** 替换动作正文 */
  action?: string | null
}

export interface DayPlan {
  dayId: number
  dayNo: number
  travelDate?: string | null
  note?: string | null
  items: TripItem[]
  theme?: string | null
  miniRoute?: Record<string, unknown>
  backupPlan?: BackupPlanEntry[]
  photoSpots?: PhotoSpotEntry[]
  practicalNotes?: string[]
  dayOptions?: DayOption[]
}

export interface BudgetRow {
  category: string
  amount: number
  itemCount: number
}

/** 备选池条目（发现更多）：生成时候选池中未排入行程的优质点位 */
export interface TripSuggestion {
  poiId?: string | null
  name: string
  category: 'attraction' | 'activity' | 'food' | 'hotel' | 'shopping' | 'souvenir'
  address?: string | null
  latitude?: number | null
  longitude?: number | null
  intro?: string | null
  needReservation?: boolean
  estimatedCost?: number | null
  used?: boolean
}

export interface ItineraryDetail {
  schemaVersion?: string
  id: number
  title: string
  city: string
  startDate?: string | null
  endDate?: string | null
  days: number
  stayNights: number
  persons: number
  budget?: number | null
  preferences?: string | null
  hotelTier?: string | null
  planNote?: string | null
  /** 叙事字段（M3 生成契约补齐后生效）：整趟主题标题 */
  tripTheme?: string | null
  /** 封面快照 / 收藏 / 归档 / 分享（S1/S2 后端已回传；详情是本人视角，含 shareToken） */
  coverUrl?: string | null
  coverSource?: string | null
  coverCredit?: CoverCredit | null
  favorite?: boolean
  archived?: boolean
  shareToken?: string | null
  /** 用户旅行意图原文（§5.3.1 意图回显行；后端暂未回传，有值才渲染） */
  intent?: string | null
  status: number
  dayList: DayPlan[]
  budgetList: BudgetRow[]
  totalAmount: number
  destinationStatus?: 'knowledge_backed' | 'researched' | 'draft_only'
  qualityStatus?: QualityReport['qualityStatus']
  qualityRuleVersion?: string
  validatedAt?: string | null
  pendingFactCount?: number
  sources?: SourceRecord[]
  qualityReport?: QualityReport
  suggestions?: TripSuggestion[]
}

export interface ItinerarySummary {
  id: number
  title: string
  city: string
  startDate?: string | null
  endDate?: string | null
  days: number
  persons: number
  budget?: number | null
  totalAmount: number
  status: number
  createdAt: string
  /** 整趟主题标题（§5.5 主题摘要行）：后端列表 VO（ItinerarySummaryVO）暂未携带该字段，
   * 也没有 dayList（首日 theme 不可得）；前端按「字段存在才渲染」防御式实现，
   * 后端补充 tripTheme 后列表卡片自动升级，无需改前端。 */
  tripTheme?: string | null
  /** S1/S2 后端已回传：封面三列 + 收藏/归档/分享态（列表只回 hasShare 布尔） */
  coverUrl?: string | null
  coverSource?: string | null
  coverCredit?: CoverCredit | null
  favorite?: boolean
  archived?: boolean
  hasShare?: boolean
}

export interface UserInfo {
  id: number
  username: string
  nickname: string | null
  phone: string | null
  role?: string | null
}

export interface LoginResponse {
  /** @deprecated 凭据在 HttpOnly Cookie，字段可能为 null */
  token?: string | null
  user: UserInfo
}

/**
 * 酒店备选方案（/chat-edit 草稿与 /hotel-option 应用共用）。
 * 本体放在 types 层：types/chat 依赖它，放 api 域文件会造成 types↔api 循环依赖。
 */
export interface HotelOption {
  id: string
  hotelName: string
  tier: string
  address?: string | null
  rating?: number | null
  basePrice: number
  seasonFactor: number
  seasonLabel: string
  nightlyPrice: number
  nights: number
  rooms: number
  totalPrice: number
  priceDelta?: number | null
  withinBudget: boolean
  budgetCapacity?: number | null
  budgetOverage: number
  isCurrent: boolean
  reason: string
  requestedNights: number
  requestedDayNos: number[]
  availableDayNos: number[]
  roomTypes: HotelRoomOption[]
  baseRevision?: string
}

export interface HotelRoomOption {
  id: string
  roomName: string
  basePrice: number
  nightlyPrice: number
  nights: number
  rooms: number
  totalPrice: number
  priceDelta?: number | null
  projectedHotelTotal?: number | null
  withinBudget: boolean
  budgetOverage: number
  capacity: number
  bedType?: string | null
  breakfast?: string | null
  description?: string | null
  isDefault: boolean
  nightlyBreakdown?: Array<{
    dayNo: number
    stayDate?: string | null
    seasonLabel: string
    seasonFactor: number
    nightlyPrice: number
  }>
}

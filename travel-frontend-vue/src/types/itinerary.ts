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
  source?: string | null
  sourceUpdatedAt?: string | null
  verificationStatus?: VerificationStatus
  valueKind?: ValueKind
  freshnessStatus?: FreshnessStatus
  reviewRequirement?: ReviewRequirement
  factEvidence?: Record<string, FactEvidence>
  sortNo?: number
}

export interface DayPlan {
  dayId: number
  dayNo: number
  travelDate?: string | null
  note?: string | null
  items: TripItem[]
  theme?: string | null
  miniRoute?: Record<string, unknown>
  backupPlan?: Record<string, unknown>[]
  photoSpots?: Record<string, unknown>[]
  practicalNotes?: string[]
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

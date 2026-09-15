import type { CoverCredit } from './itinerary'

/** 分享页只读 VO（SPEC v2.3 §5.3 白名单）：没有 userId / shareToken / 内部主键。 */

export interface SharedDayItem {
  poiName: string
  itemType: string
  address: string | null
  startTime: string | null
  endTime: string | null
  cost: number | null
  image: string | null
  latitude: number | null
  longitude: number | null
  source: string | null
}

export interface SharedDay {
  dayNo: number
  travelDate: string | null
  theme: string | null
  note: string | null
  dayTotalAmount: number
  items: SharedDayItem[]
}

export interface SharedBudgetRow {
  category: string
  amount: number | null
  itemCount: number
}

export interface SharedItinerary {
  city: string
  title: string
  days: number
  persons: number
  startDate: string | null
  endDate: string | null
  budget: number | null
  hotelTier: string | null
  tripTheme: string | null
  coverUrl: string | null
  coverCredit: CoverCredit | null
  totalAmount: number
  dayList: SharedDay[]
  budgetList: SharedBudgetRow[]
  planNote: string | null
}

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
  sortNo?: number
}

export interface DayPlan {
  dayId: number
  dayNo: number
  travelDate?: string | null
  note?: string | null
  items: TripItem[]
}

export interface BudgetRow {
  category: string
  amount: number
  itemCount: number
}

export interface ItineraryDetail {
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
}

export interface LoginResponse {
  token: string
  user: UserInfo
}

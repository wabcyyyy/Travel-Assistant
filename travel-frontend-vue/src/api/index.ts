import { requestDelete, requestGet, requestPost, requestPut } from './request'
import axios from 'axios'
import type {
  ItineraryDetail,
  ItinerarySummary,
  LoginResponse,
  TripItem,
  UserInfo,
} from '../types/itinerary'

export function getHello() {
  return requestGet<string>('/test/hello')
}

export function callAgent() {
  return requestGet<Record<string, unknown>>('/test/call-agent')
}

export function login(data: { username: string; password: string }) {
  return requestPost<LoginResponse>('/auth/login', data)
}

export function register(data: { username: string; password: string; nickname?: string }) {
  return requestPost<void>('/auth/register', data)
}

export function getUserInfo() {
  return requestGet<UserInfo>('/user/info')
}

export function getSupportedCities() {
  return requestGet<string[]>('/itinerary/supported-cities')
}

export function generateItinerary(data: {
  city: string
  days: number
  persons: number
  stayNights: number
  budget?: number
  startDate?: string
  endDate?: string
  preferences: string[]
  hotelTier?: string
}) {
  return requestPost<ItineraryDetail>('/itinerary/generate', data)
}

export function getItineraryList() {
  return requestGet<ItinerarySummary[]>('/itinerary')
}

export function getItineraryDetail(id: number | string) {
  return requestGet<ItineraryDetail>(`/itinerary/${id}`)
}

export function deleteItinerary(id: number) {
  return requestDelete<void>(`/itinerary/${id}`)
}

export interface AmapPoi {
  id: string
  name: string
  address: string | null
  latitude: number | null
  longitude: number | null
  type: string | null
}

export function searchPoi(keywords: string, city?: string) {
  return requestGet<AmapPoi[]>('/amap/poi', {
    params: { keywords, city: city || undefined },
  })
}

export function addItem(id: number | string, data: Partial<TripItem> & { dayId: number }) {
  return requestPost<ItineraryDetail>(`/itinerary/${id}/items`, data)
}

export function updateItem(itemId: number, data: Partial<TripItem>) {
  return requestPut<ItineraryDetail>(`/itinerary/items/${itemId}`, data)
}

export function deleteItem(itemId: number) {
  return requestDelete<ItineraryDetail>(`/itinerary/items/${itemId}`)
}

export function reorderItems(id: number | string, dayId: number, itemIds: number[]) {
  return requestPut<ItineraryDetail>(`/itinerary/${id}/days/${dayId}/order`, itemIds)
}

export interface ExportTaskInfo {
  id: number
  itineraryId: number
  taskType: string
  status: 'RUNNING' | 'DONE' | 'FAILED'
  errorMsg: string | null
  downloadUrl: string | null
  createdAt: string
  finishedAt: string | null
}

export function createPdfExport(itineraryId: number | string) {
  return requestPost<ExportTaskInfo>(`/export/pdf/${itineraryId}`)
}

export function getExportTask(taskId: number) {
  return requestGet<ExportTaskInfo>(`/export/tasks/${taskId}`)
}

export function clarifyTrip(data: { message: string; slots?: Record<string, unknown> }) {
  return requestPost<{ slots: Record<string, unknown>; missing: string[]; question: string | null; ready: boolean }>(
    '/itinerary/clarify',
    data,
  )
}

export function nlEditItinerary(id: number | string, instruction: string) {
  return requestPost<{ applied: string[] }>('/itinerary/' + id + '/nl-edit', { instruction })
}

export function chatEditItinerary(
  id: number | string,
  message: string,
  history: { role: string; content: string }[],
) {
  return requestPost<{
    reply: string
    changed: boolean
    plans: unknown[]
    hotelOptions: HotelOption[]
    requiresConfirmation: boolean
    planDocument?: Record<string, unknown> | null
    operations?: Record<string, unknown>[]
    pendingAction?: Record<string, unknown> | null
    messageId?: number
    baseRevision?: string
  }>(
    '/itinerary/' + id + '/chat-edit',
    { message, history },
  )
}

export interface ItineraryChatMessage {
  id?: number
  role: 'user' | 'ai'
  content: string
  plans?: any[]
  hotelOptions?: HotelOption[]
  changed?: boolean
  baseRevision?: string
  createdAt?: string
}

export function getItineraryChatHistory(id: number | string) {
  return requestGet<ItineraryChatMessage[]>(`/itinerary/${id}/chat-history`)
}

export function clearItineraryChatHistory(id: number | string) {
  return requestDelete<void>(`/itinerary/${id}/chat-history`)
}

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

export function cityGuide(input: string, history: { role: string; content: string }[]) {
  return requestPost<{
    kind: 'province' | 'city' | 'unclear'
    city: string | null
    message: string
    suggestions: { name: string; reason: string }[]
  }>('/itinerary/city-guide', { input, history })
}

export function applyPlans(
  id: number | string,
  plans: unknown[],
  actionMessageId?: number,
  baseRevision?: string,
) {
  return requestPost<ItineraryDetail>('/itinerary/' + id + '/apply-plans', {
    plans,
    actionMessageId,
    baseRevision,
  })
}

export function applyHotelOption(
  id: number | string,
  option: Pick<HotelOption, 'hotelName' | 'tier'>,
  roomType: string,
  dayNos: number[],
  actionMessageId?: number,
  baseRevision?: string,
) {
  return requestPost<ItineraryDetail>('/itinerary/' + id + '/hotel-option', {
    hotelName: option.hotelName,
    tier: option.tier,
    roomType,
    dayNos,
    actionMessageId,
    baseRevision,
  })
}

const downloadClient = axios.create({ baseURL: '/api', timeout: 60000 })

downloadClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export async function downloadExportFile(taskId: number): Promise<Blob> {
  const resp = await downloadClient.get(`/export/download/${taskId}`, { responseType: 'blob' })
  return resp.data as Blob
}

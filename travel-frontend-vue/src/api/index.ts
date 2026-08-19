import { requestDelete, requestGet, requestPost, requestPut } from './request'
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

export function generateItinerary(data: {
  city: string
  days: number
  persons: number
  budget?: number
  startDate?: string
  endDate?: string
  preferences: string[]
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
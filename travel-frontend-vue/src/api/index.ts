import { requestDelete, requestGet, requestPost } from './request'
import type { ItineraryDetail, ItinerarySummary, LoginResponse, UserInfo } from '../types/itinerary'

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
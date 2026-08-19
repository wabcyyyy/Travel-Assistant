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
import { requestDelete, requestGet, requestPost, requestPut, type ApiRequestConfig } from './request'
import axios from 'axios'
import { useUserStore } from '../store/user'
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

/** 服务端吊销 JWT（logout）；本地清理仍由 user store 执行。 */
export function logoutApi() {
  return requestPost<void>('/auth/logout')
}

export function getUserInfo() {
  return requestGet<UserInfo>('/user/info')
}

// ---------------- 后台管理 ----------------

export interface AdminUser {
  id: number
  username: string
  nickname: string | null
  phone: string | null
  status: number
  role: string
  itineraryCount: number
  createdAt: string
}

export interface AdminUserPage {
  records: AdminUser[]
  total: number
  size: number
  current: number
  pages: number
}

export interface AdminStats {
  totalUsers: number
  activeUsers: number
  disabledUsers: number
  totalItineraries: number
  todayNewUsers: number
  todayNewItineraries: number
  generatingItineraries: number
}

export function getAdminStats() {
  return requestGet<AdminStats>('/admin/stats')
}

export function getAdminUsers(params: { page: number; size: number; keyword?: string }) {
  return requestGet<AdminUserPage>('/admin/users', { params })
}

export function updateAdminUserStatus(id: number, status: 0 | 1) {
  return requestPut<void>(`/admin/users/${id}/status/${status}`)
}

export function deleteAdminUser(id: number) {
  return requestDelete<void>(`/admin/users/${id}`)
}

export interface AdminItinerary {
  id: number
  userId: number
  title: string
  city: string
  startDate: string | null
  endDate: string | null
  days: number
  persons: number
  budget: number | null
  status: number
  createdAt: string
}

export interface AdminItineraryPage {
  records: AdminItinerary[]
  total: number
  size: number
  current: number
  pages: number
}

export function getAdminItineraries(params: {
  page: number
  size: number
  keyword?: string
  status?: number
  userId?: number
}) {
  return requestGet<AdminItineraryPage>('/admin/itineraries', { params })
}

export function deleteAdminItinerary(id: number) {
  return requestDelete<void>(`/admin/itineraries/${id}`)
}

export interface AgentMetrics {
  agentAvailable: boolean
  runs: number
  successes: number
  failures: number
  degraded_runs: number
  llm_calls: number
  tool_calls: number
  prompt_tokens: number
  completion_tokens: number
  success_rate: number
  failure_rate: number
  degraded_rate: number
  avg_event_latency_ms: number
  recent_failures: { run_id: string; events: { kind: string; name: string; status: string; error: string }[] }[]
  tokens_by_scene: Record<string, { llm_calls: number; prompt_tokens: number; completion_tokens: number }>
  tokens_timeline: { ts: number; calls: number; prompt_tokens: number; completion_tokens: number }[]
}

export function getAgentMetrics() {
  return requestGet<AgentMetrics>('/admin/agent-metrics')
}

export interface UsageSummary {
  calls: number
  successes: number
  failures: number
  success_rate: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  avg_duration_ms: number
}

export interface UsageGroup {
  scene?: string
  model?: string
  calls: number
  successes: number
  prompt_tokens: number
  completion_tokens: number
  avg_duration_ms: number
}

export interface UsageCall {
  ts: number
  scene: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  duration_ms: number
  success: boolean
  error: string | null
}

export interface LlmUsage {
  agentAvailable: boolean
  range: string
  bucket: number
  summary: UsageSummary
  by_scene: UsageGroup[]
  by_model: UsageGroup[]
  timeline: { ts: number; calls: number; prompt_tokens: number; completion_tokens: number }[]
  calls: { total: number; records: UsageCall[] }
}

export function getLlmUsage(range: string, limit = 200, offset = 0) {
  return requestGet<LlmUsage>('/admin/llm-usage', { params: { range, limit, offset } })
}

/** Token 仪表盘场景中文名 */
export const SCENE_LABELS: Record<string, string> = {
  generate: '行程生成',
  clarify: '澄清提问',
  chat: '对话修改',
  assist: '导览/介绍',
  other: '其他',
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
  regionHint?: string
  requirements?: string
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
  rating: string | null
  cost: string | null
}

export function searchPoi(keywords: string, city?: string, types?: string) {
  return requestGet<AmapPoi[]>('/amap/poi', {
    params: { keywords: keywords || undefined, city: city || undefined, types: types || undefined },
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

export function nlEditItinerary(id: number | string, instruction: string) {
  return requestPost<{ applied: string[] }>('/itinerary/' + id + '/nl-edit', { instruction })
}

export function chatEditItinerary(
  id: number | string,
  message: string,
  history: { role: string; content: string }[],
  signal?: AbortSignal,
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
    { signal },
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

export interface NearbyPoi {
  name: string
  category: string
  rating: number | null
  address: string | null
  distanceM: number | null
}

/** 附近推荐：行程项所在城市的权威知识库真实近邻（轻量 GraphRAG）。 */
export function getNearbyPois(data: {
  city: string
  name?: string
  latitude?: number
  longitude?: number
  limit?: number
  category?: string
}) {
  return requestPost<{ items: NearbyPoi[] }>('/itinerary/poi-nearby', data)
}

export function getTopPreferences(config?: ApiRequestConfig) {
  return requestGet<string[]>('/itinerary/preferences', config)
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

const downloadClient = axios.create({ baseURL: '/api', timeout: 60000, withCredentials: true })

downloadClient.interceptors.request.use((config) => {
  const memToken = useUserStore().token
  if (memToken) {
    config.headers.Authorization = `Bearer ${memToken}`
  }
  return config
})

export async function downloadExportFile(taskId: number): Promise<Blob> {
  const resp = await downloadClient.get(`/export/download/${taskId}`, { responseType: 'blob' })
  return resp.data as Blob
}

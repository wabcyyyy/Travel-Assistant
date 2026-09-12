import { requestDelete, requestGet, requestPut } from './request'

/** 后台管理域：用户/行程管理、Agent 指标与 LLM 用量仪表盘。 */

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

import { requestGet, requestPost } from './request'
import type { ItineraryDetail } from '../types/itinerary'

export interface VersionSummary {
  id: number
  versionNo: number
  parentVersionId: number | null
  operation: string
  summary: string | null
  createdAt: string
}

export interface VersionChange {
  type: 'added' | 'removed' | 'updated'
  key: string
  before: unknown
  after: unknown
}

export interface VersionDiff {
  fromVersionId: number
  toVersionId: number
  changes: VersionChange[]
}

/** 版本快照链（A5 接线）：列 / 结构 diff / 恢复（restore 自身也会再打一条快照）。 */
export function listVersions(id: number | string) {
  return requestGet<VersionSummary[]>(`/itinerary/${id}/versions`)
}

export function diffVersions(id: number | string, fromVersionId: number, toVersionId: number) {
  return requestGet<VersionDiff>(`/itinerary/${id}/versions/diff`, {
    params: { fromVersionId, toVersionId },
  })
}

export function restoreVersion(id: number | string, versionId: number) {
  return requestPost<ItineraryDetail>(`/itinerary/${id}/versions/${versionId}/restore`)
}

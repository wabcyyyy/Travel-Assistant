/**
 * 模板（C2.4）：发布/下架 + 模板广场 + fork。类型走生成契约。
 */
import { requestDelete, requestGet, requestPost } from './request'
import type * as Contracts from '../types/generated/contracts'

export type TemplateSummaryVO = Contracts.TemplateSummaryVO
export type TemplateCardVO = Contracts.TemplateCardVO
export type TemplatePublishVO = Contracts.TemplatePublishVO
export type TemplateDetailVO = Contracts.TemplateDetailVO
export type TemplateForkVO = Contracts.TemplateForkVO

/** 导航可见性探测：addon 关时后端仍 200（enabled=false），不经 404 判断。 */
export function getTemplateCapability() {
  return requestGet<{ enabled: boolean }>('/templates/capability')
}

export function listTemplates() {
  return requestGet<Contracts.TemplateCardVO[]>('/templates')
}

export function getTemplate(templateId: number) {
  return requestGet<TemplateDetailVO>(`/templates/${templateId}`)
}

export function publishTemplate(itineraryId: number | string) {
  return requestPost<TemplatePublishVO>(`/itinerary/${itineraryId}/template`)
}

/** owner 视角：已发布=物化快照；未发布=即时构建的发布前预览（不落库）。 */
export function getTemplateView(itineraryId: number | string) {
  return requestGet<TemplatePublishVO>(`/itinerary/${itineraryId}/template`)
}

export function unpublishTemplate(itineraryId: number | string) {
  return requestDelete(`/itinerary/${itineraryId}/template`)
}

export function forkTemplate(templateId: number) {
  return requestPost<TemplateForkVO>(`/templates/${templateId}/fork`)
}

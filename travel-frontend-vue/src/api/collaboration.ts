/**
 * 协作（C2.3）：成员与邀请管理。类型走生成契约，本模块只做 URL 与信封解包。
 */
import { requestDelete, requestGet, requestPost, requestPut } from './request'
import type * as Contracts from '../types/generated/contracts'

export type InvitationVO = Contracts.InvitationVO
export type InvitationCreatedVO = Contracts.InvitationCreatedVO
export type InvitationListVO = Contracts.InvitationListVO
export type MemberVO = Contracts.MemberVO
export type MemberListVO = Contracts.MemberListVO
export type InvitationAcceptVO = Contracts.InvitationAcceptVO

export function listMembers(itineraryId: number | string) {
  return requestGet<Contracts.MemberVO[]>(`/itinerary/${itineraryId}/members`)
}

export function createInvitation(itineraryId: number | string, role: Contracts.InvitationVO['role']) {
  return requestPost<InvitationCreatedVO>(`/itinerary/${itineraryId}/invitations`, { role })
}

export function listInvitations(itineraryId: number | string) {
  return requestGet<Contracts.InvitationVO[]>(`/itinerary/${itineraryId}/invitations`)
}

export function revokeInvitation(itineraryId: number | string, invitationId: number) {
  return requestDelete(`/itinerary/${itineraryId}/invitations/${invitationId}`)
}

export function updateMemberRole(itineraryId: number | string, memberId: number, role: Contracts.MemberVO['role']) {
  return requestPut<Contracts.MemberVO>(`/itinerary/${itineraryId}/members/${memberId}`, { role })
}

export function removeMember(itineraryId: number | string, memberId: number) {
  return requestDelete(`/itinerary/${itineraryId}/members/${memberId}`)
}

/** 兑换邀请：token 放请求体（不放查询参数，避免进访问日志）。 */
export function acceptInvitation(token: string) {
  return requestPost<InvitationAcceptVO>('/itinerary/invitations/accept', { token })
}

import type { TripItem } from '../types/itinerary'

export function evidenceLabel(item: TripItem): string {
  if (item.freshnessStatus === 'stale') return '来源信息可能过期'
  if (item.verificationStatus === 'unverified') return '待核实'
  if (item.verificationStatus === 'partially_verified') return '部分信息有据'
  const identity = item.factEvidence?.identity
  if (identity?.valueKind === 'observed' && identity.verificationStatus === 'verified') return '地点有来源'
  if (item.valueKind === 'estimated') return '估算信息'
  if (item.valueKind === 'generated') return '生成信息'
  if (item.valueKind === 'observed') return '地点有来源'
  return ''
}

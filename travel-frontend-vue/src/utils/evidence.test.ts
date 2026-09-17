import { describe, expect, it } from 'vitest'
import type { TripItem } from '../types/itinerary'
import { evidenceLabel } from './evidence'

const item = (fields: Partial<TripItem> = {}): TripItem => ({ itemType: 'attraction', poiName: '寺院', ...fields })
describe('证据徽标', () => {
  it('缺失字段或只有来源不冒充已核实', () => {
    expect(evidenceLabel(item())).toBe('')
    expect(evidenceLabel(item({ source: 'opentripmap:xid' }))).toBe('')
  })
  it('未核实与过期优先于 observed', () => {
    expect(evidenceLabel(item({ valueKind: 'observed', verificationStatus: 'unverified' }))).toBe('待核实')
    expect(evidenceLabel(item({ valueKind: 'observed', freshnessStatus: 'stale' }))).toBe('来源信息可能过期')
  })
  it('来源和估算都不声称票价已核实', () => {
    expect(evidenceLabel(item({ valueKind: 'observed' }))).toBe('地点有来源')
    expect(evidenceLabel(item({ verificationStatus: 'partially_verified' }))).toBe('部分信息有据')
    expect(evidenceLabel(item({ valueKind: 'estimated' }))).toBe('估算信息')
    expect(evidenceLabel(item({ valueKind: 'generated' }))).toBe('生成信息')
  })
})

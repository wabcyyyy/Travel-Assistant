import { describe, expect, it } from 'vitest'
import {
  cleanBackupRules,
  cleanPhotoSpots,
  cleanPracticalNotes,
  dayMetaText,
  dayTitle,
  dayTotalAmountOf,
  formatTime,
  hasAnyTips,
  isOptimizableItem,
  optionNames,
  ruleIf,
  spotName,
  typeLabel,
} from './shared'
import type { DayPlan } from '../../../types/itinerary'

function day(overrides: Partial<DayPlan> = {}): DayPlan {
  return { dayId: 1, dayNo: 1, items: [], ...overrides }
}

describe('dayMetaText', () => {
  it('合法 travelDate → M月D日 · 周X', () => {
    // 2026-09-16 是周三（UTC 无关：本地解析）
    expect(dayMetaText(day({ travelDate: '2026-09-16', dayNo: 3 }))).toBe('9月16日 · 周三')
  })

  it('缺省 travelDate → 回落「第 N 天」', () => {
    expect(dayMetaText(day({ dayNo: 2 }))).toBe('第 2 天')
  })

  it('非法 travelDate → 回落「第 N 天」而非 NaN', () => {
    expect(dayMetaText(day({ travelDate: 'not-a-date', dayNo: 5 }))).toBe('第 5 天')
  })
})

describe('dayTitle', () => {
  it('主题优先', () => {
    expect(dayTitle(day({ theme: '园林慢游', items: [] }))).toBe('园林慢游')
  })

  it('无主题：首尾点位串（首尾不同）', () => {
    const d = day({ items: [{ itemType: 'attraction', poiName: '西湖' }, { itemType: 'attraction', poiName: '灵隐寺' }] })
    expect(dayTitle(d)).toBe('西湖 → 灵隐寺')
  })

  it('无主题：单项只显示首点', () => {
    expect(dayTitle(day({ items: [{ itemType: 'attraction', poiName: '西湖' }] }))).toBe('西湖')
  })

  it('空行程 → 暂无安排', () => {
    expect(dayTitle(day())).toBe('暂无安排')
  })
})

describe('formatTime', () => {
  it('HH:mm:ss 截取为 HH:mm', () => {
    expect(formatTime('09:30:00')).toBe('09:30')
  })
  it('非字符串/缺省 → 空串', () => {
    expect(formatTime(null)).toBe('')
    expect(formatTime(undefined)).toBe('')
    expect(formatTime(930 as unknown as string)).toBe('')
  })
})

describe('typeLabel', () => {
  it('白名单映射，未知类型原样透传', () => {
    expect(typeLabel('attraction')).toBe('景点')
    expect(typeLabel('souvenir')).toBe('souvenir')
  })
})

describe('isOptimizableItem', () => {
  it('与后端 optimize 400 门槛同口径：attraction/food', () => {
    expect(isOptimizableItem({ itemType: 'attraction', poiName: 'x' })).toBe(true)
    expect(isOptimizableItem({ itemType: 'food', poiName: 'x' })).toBe(true)
    expect(isOptimizableItem({ itemType: 'hotel', poiName: 'x' })).toBe(false)
    expect(isOptimizableItem({ itemType: 'transport', poiName: 'x' })).toBe(false)
  })
})

describe('dayTotalAmountOf', () => {
  const items = [
    { itemType: 'attraction', cost: 40 },
    { itemType: 'food', cost: 60 },
    { itemType: 'hotel', cost: 300 },
    { itemType: 'attraction', cost: null },
  ] as never

  it('餐饮/景点按人数，酒店按房间数（每房 2 人）', () => {
    // 4 人 → 2 房：40*4 + 60*4 + 300*2 = 1000
    expect(dayTotalAmountOf(items, 4)).toBe(1000)
    // 1 人 → 1 房：40 + 60 + 300 = 400
    expect(dayTotalAmountOf(items, 1)).toBe(400)
  })

  it('persons 非法值回落 1', () => {
    expect(dayTotalAmountOf(items, 0)).toBe(400)
  })

  it('cost 缺省项不计入', () => {
    expect(dayTotalAmountOf([{ itemType: 'attraction', cost: null }] as never, 3)).toBe(0)
  })
})

describe('叙事块清洗', () => {
  it('practicalNotes：trim + 去空', () => {
    expect(cleanPracticalNotes(['  提前预约 ', '', '  '])).toEqual(['提前预约'])
  })

  it('photoSpots：name/title 有其一即保留', () => {
    expect(cleanPhotoSpots([{ name: 'a' }, { title: 'b' }, {}])).toHaveLength(2)
  })

  it('backupRules：条件或动作有内容即保留', () => {
    expect(cleanBackupRules([{ if: '下雨', action: '' }, { action: '改室内' }, {}])).toHaveLength(2)
  })

  it('hasAnyTips：三块全空才为 false', () => {
    expect(hasAnyTips([], [], [])).toBe(false)
    expect(hasAnyTips(['x'], [], [])).toBe(true)
    expect(hasAnyTips([], [{ name: 'a' }], [])).toBe(true)
    expect(hasAnyTips([], [], [{ action: 'x' }])).toBe(true)
  })

  it('spotName / ruleIf 兼容历史键', () => {
    expect(spotName({ name: '', title: '机位' })).toBe('机位')
    expect(ruleIf({ if: ' 雨天 ', name: '旧名' })).toBe('雨天')
  })

  it('optionNames 去空', () => {
    expect(optionNames([{ poiName: 'a' }, { poiName: '' }, {}])).toEqual(['a'])
  })
})

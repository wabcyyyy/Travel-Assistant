import { describe, expect, it } from 'vitest'
import {
  assistantReply,
  clearIntake,
  loadIntake,
  mergeSlots,
  READY_TEXT,
  saveIntake,
  seedFromQuery,
  slotsReady,
  toGenerateInput,
} from './intakeSlots'
import type { IntakeSlots } from './intakeSlots'
import { inspirationTemplates } from '../data'

const fullSlots: IntakeSlots = {
  city: '成都',
  days: 3,
  persons: 2,
  start_date: '2026-10-01',
  origin_city: '北京',
  budget: 3000,
  preferences: ['美食', '慢节奏'],
}

describe('slotsReady（就绪门 = 后端 _REQUIRED 同口径）', () => {
  it('city/days/persons 齐全才算就绪', () => {
    expect(slotsReady(fullSlots)).toBe(true)
    expect(slotsReady({ ...fullSlots, city: ' ' })).toBe(false)
    expect(slotsReady({ ...fullSlots, days: 8 })).toBe(false)
    expect(slotsReady({ ...fullSlots, days: 0 })).toBe(false)
    expect(slotsReady({ ...fullSlots, persons: undefined })).toBe(false)
  })
})

describe('mergeSlots（后端抽取合并，坏形状丢弃）', () => {
  it('合并已知键并做基本清洗', () => {
    const merged = mergeSlots(fullSlots, {
      city: ' 大理 ',
      origin_city: '上海',
      days: '5',
      persons: 4,
      start_date: '2026-11-11',
      budget: '2000',
      preferences: ['自然风光', ''],
      hotel_tier: '舒适型',
    })
    expect(merged.city).toBe('大理')
    expect(merged.origin_city).toBe('上海')
    expect(merged.days).toBe(5)
    expect(merged.persons).toBe(4)
    expect(merged.start_date).toBe('2026-11-11')
    expect(merged.budget).toBe(2000)
    expect(merged.preferences).toEqual(['自然风光'])
    expect(merged.hotel_tier).toBe('舒适型')
  })
  it('词组天数等垃圾值不覆盖已有槽位', () => {
    const merged = mergeSlots({ days: 3 }, { days: '两周', persons: ' couple ' })
    expect(merged.days).toBe(3)
    expect(merged.persons).toBeUndefined()
  })
  it('budget 非正数不收', () => {
    expect(mergeSlots({}, { budget: 0 }).budget).toBeUndefined()
    expect(mergeSlots({}, { budget: -5 }).budget).toBeUndefined()
  })
})

describe('toGenerateInput（槽位 → 生成请求）', () => {
  it('推导 stayNights/endDate，透传 originCity 与首句 intent', () => {
    const input = toGenerateInput(fullSlots, '下周想去成都玩三天，两个人，预算 3000')
    expect(input).toMatchObject({
      city: '成都',
      days: 3,
      persons: 2,
      stayNights: 2,
      startDate: '2026-10-01',
      endDate: '2026-10-03',
      originCity: '北京',
      budget: 3000,
      intent: '下周想去成都玩三天，两个人，预算 3000',
      preferences: ['美食', '慢节奏'],
    })
  })
  it('跨月日期推导不串日', () => {
    const input = toGenerateInput({ ...fullSlots, start_date: '2026-10-31', days: 2 }, '句')
    expect(input.endDate).toBe('2026-11-01')
  })
  it('可选项缺省不送占位值', () => {
    const input = toGenerateInput({ city: '成都', days: 2, persons: 1 }, '')
    expect(input.startDate).toBeUndefined()
    expect(input.endDate).toBeUndefined()
    expect(input.originCity).toBeUndefined()
    expect(input.budget).toBeUndefined()
    expect(input.stayNights).toBe(1)
  })
})

describe('assistantReply（clarify 响应 → 助手话术）', () => {
  it('就绪给确认引导，不带 chips（选择交给确认条）', () => {
    const reply = assistantReply(true, null, ['x'])
    expect(reply?.text).toBe(READY_TEXT)
    expect(reply?.options).toBeUndefined()
  })
  it('缺槽透传追问与 chips', () => {
    const reply = assistantReply(false, '几个人一起出发呀？', ['2 人', '4 人'])
    expect(reply?.text).toBe('几个人一起出发呀？')
    expect(reply?.options).toEqual(['2 人', '4 人'])
  })
  it('没有追问就没有话术', () => {
    expect(assistantReply(false, null, undefined)).toBeNull()
  })
})

describe('seedFromQuery（入口首句预填）', () => {
  it('?city=&days= 合成首句', () => {
    expect(seedFromQuery(new URLSearchParams('city=杭州&days=2'))).toBe('想去杭州玩 2 天，帮我安排一下')
  })
  it('?intent= 与 ?template= 直出原句', () => {
    expect(seedFromQuery(new URLSearchParams('intent=带爸妈去厦门'))).toBe('带爸妈去厦门')
    const template = inspirationTemplates[0]
    expect(seedFromQuery(new URLSearchParams(`template=${template.id}`))).toBe(template.intent)
  })
  it('无参数给空串（不吃掉问候语）', () => {
    expect(seedFromQuery(new URLSearchParams())).toBe('')
  })
})

describe('intake 会话暂存（sessionStorage，刷新可续）', () => {
  it('save → load 原样回来，clear 后为空', () => {
    saveIntake({
      messages: [{ id: 'greeting', role: 'assistant', text: 'hi' }, { id: 'u1', role: 'user', text: '想去成都' }],
      slots: { city: '成都' },
      firstMessage: '想去成都',
    })
    const restored = loadIntake()
    expect(restored?.messages.map((item) => item.text)).toEqual(['hi', '想去成都'])
    expect(restored?.slots.city).toBe('成都')
    expect(restored?.firstMessage).toBe('想去成都')
    clearIntake()
    expect(loadIntake()).toBeNull()
  })
  it('坏形状消息被过滤，有效消息保留', () => {
    saveIntake({
      messages: [{ id: 'a', role: 'assistant', text: 'ok' }],
      slots: { city: '成都' },
      firstMessage: '',
    })
    const raw = sessionStorage.getItem('sinan-intake-v1')
    sessionStorage.setItem(
      'sinan-intake-v1',
      JSON.stringify({ ...JSON.parse(raw!), messages: [{ role: 'user', text: 42 }, 'junk', { id: 'b', role: 'user', text: '想去成都' }] }),
    )
    const restored = loadIntake()
    expect(restored?.messages.map((item) => item.id)).toEqual(['b'])
    expect(restored?.slots.city).toBe('成都')
  })
  it('全部消息无效 = 无可续会话，返回 null', () => {
    saveIntake({ messages: [{ id: 'a', role: 'assistant', text: 'ok' }], slots: {}, firstMessage: '' })
    const raw = sessionStorage.getItem('sinan-intake-v1')
    sessionStorage.setItem('sinan-intake-v1', JSON.stringify({ ...JSON.parse(raw!), messages: ['junk'] }))
    expect(loadIntake()).toBeNull()
  })
})

import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ItineraryDetail } from '../../types/itinerary'
import type { useHomePlanning } from './useHomePlanning'
import { ChatIntake } from './ChatIntake'
import { TripPreview } from './TripPreview'

/**
 * 对话壳与实时预览的静态渲染测试（同 TripBadges.test.ts 纪律：零新依赖、
 * renderToStaticMarkup 断言结构，不跑 effect、不依赖网络/路由）。
 */

type Planning = ReturnType<typeof useHomePlanning>

const planning = (overrides: Partial<Planning>): Planning =>
  ({ status: 'idle', message: '', progress: 0, draft: null, busy: false, submit: async () => undefined, ...overrides }) as Planning

const day = (dayNo: number, pois: string[]) => ({
  dayId: dayNo,
  dayNo,
  generationStatus: pois.length ? 'SUCCEEDED' : 'PENDING',
  items: pois.map((poiName) => ({ itemType: 'attraction', poiName })),
})

describe('TripPreview（生成期实时预览）', () => {
  it('idle 显示引导占位', () => {
    const html = renderToStaticMarkup(createElement(TripPreview, { planning: planning({}) }))
    expect(html).toContain('实时长出来')
  })
  it('生成中：已排天亮内容，未排天显示占位与总天数', () => {
    const draft = {
      id: 7,
      days: 3,
      dayList: [day(1, ['宽窄巷子', '人民公园']), day(2, []), day(3, [])],
    } as unknown as ItineraryDetail
    const html = renderToStaticMarkup(
      createElement(TripPreview, {
        planning: planning({ status: 'planning', message: '正在安排第 2 天', progress: 2, draft, busy: true }),
      }),
    )
    expect(html).toContain('宽窄巷子')
    expect(html).toContain('安排中…')
    expect(html).toContain('第 3 天')
    expect(html).toContain('正在安排第 2 天')
    expect(html).toContain('trip-preview-days')
  })
  it('完成后给「查看完整行程」入口', () => {
    const draft = { id: 7, days: 1, dayList: [day(1, ['西湖'])] } as unknown as ItineraryDetail
    const html = renderToStaticMarkup(
      createElement(TripPreview, { planning: planning({ status: 'ready', message: '你的行程已准备好', progress: 4, draft }) }),
    )
    expect(html).toContain('查看完整行程')
  })
  it('失败态提示可从对话重开', () => {
    const html = renderToStaticMarkup(
      createElement(TripPreview, { planning: planning({ status: 'error', message: '生成失败' }) }),
    )
    expect(html).toContain('开始规划')
  })
})

describe('ChatIntake（对话壳静态冒烟）', () => {
  it('初始渲染出问候语与输入框', () => {
    const html = renderToStaticMarkup(createElement(ChatIntake, { query: new URLSearchParams() }))
    expect(html).toContain('想去哪儿玩')
    expect(html).toContain('说说你的旅行想法')
  })
  it('?city= 预填首句草稿', () => {
    const html = renderToStaticMarkup(createElement(ChatIntake, { query: new URLSearchParams('city=成都&days=3') }))
    expect(html).toContain('想去成都玩 3 天')
  })
})

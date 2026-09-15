import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import type { StreamState } from '../../store/itinerary'
import type { ItineraryDetail } from '../../types/itinerary'
import ButlerStrip from './ButlerStrip.vue'

function makeStream(overrides: Record<string, unknown> = {}): StreamState {
  return {
    phase: 'idle',
    dayNo: null,
    degraded: [],
    degradedDays: [],
    fallbackMode: false,
    retryable: false,
    errorMessage: '',
    evidenceCount: null,
    ...overrides,
  } as unknown as StreamState
}

function makeDetail(overrides: Record<string, unknown> = {}): ItineraryDetail {
  return {
    status: 2,
    days: 3,
    planNote: '先看雷门，再去仲见世。\n第二段：晚上去河边。',
    ...overrides,
  } as unknown as ItineraryDetail
}

describe('ButlerStrip（管家说条）', () => {
  it('摘要取手记首段；完成态显示「已完成」chip', () => {
    const wrapper = mount(ButlerStrip, {
      props: { detail: makeDetail(), doneDays: 3, streamState: makeStream() },
    })
    expect(wrapper.find('.strip-preview').text()).toBe('先看雷门，再去仲见世。')
    expect(wrapper.find('.strip-chip').text()).toBe('已完成')
    expect(wrapper.find('.strip-chip').classes()).toContain('tone-success')
  })

  it('展开显示管家信件全文；收起后隐藏', async () => {
    const wrapper = mount(ButlerStrip, {
      props: { detail: makeDetail(), doneDays: 3, streamState: makeStream() },
    })
    // happy-dom 的 isVisible() 基于布局测量对 display:none 不可靠，直接断言 v-show 的 inline style
    const body = wrapper.find('.strip-body')
    expect((body.element as HTMLElement).style.display).toBe('none')

    await wrapper.find('.strip-btn').trigger('click')
    expect((body.element as HTMLElement).style.display).not.toBe('none')
    expect(body.text()).toContain('第二段：晚上去河边。')

    await wrapper.find('.strip-btn').trigger('click')
    expect((body.element as HTMLElement).style.display).toBe('none')
  })

  it('生成中：状态 chip 透出逐日进度；failed 自动展开并可重试', async () => {
    const generating = mount(ButlerStrip, {
      props: {
        detail: makeDetail({ status: 1, planNote: '' }),
        doneDays: 1,
        streamState: makeStream({ phase: 'day', dayNo: 2 }),
      },
    })
    expect(generating.find('.strip-chip').text()).toBe('排版中 · 第 2/3 天')
    generating.unmount()

    const failed = mount(ButlerStrip, {
      props: {
        detail: makeDetail({ status: 1, planNote: '' }),
        doneDays: 0,
        streamState: makeStream({ phase: 'failed', errorMessage: '研究素材获取失败', retryable: true }),
      },
    })
    await failed.vm.$nextTick()
    expect((failed.find('.strip-body').element as HTMLElement).style.display).not.toBe('none')
    expect(failed.find('.strip-chip').text()).toBe('研究素材获取失败')
    const retry = failed.find('.retry-btn')
    expect(retry.exists()).toBe(true)
    await retry.trigger('click')
    expect(failed.emitted('retry')).toBeTruthy()
  })

  it('对话与版本历史入口抛出对应事件', async () => {
    const wrapper = mount(ButlerStrip, {
      props: { detail: makeDetail(), doneDays: 3, streamState: makeStream() },
    })
    const buttons = wrapper.findAll('.strip-btn')
    await buttons[1].trigger('click')
    await buttons[2].trigger('click')
    expect(wrapper.emitted('chat')).toBeTruthy()
    expect(wrapper.emitted('versions')).toBeTruthy()
  })
})

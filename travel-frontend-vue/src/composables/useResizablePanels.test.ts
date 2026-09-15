import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import { defineComponent, h, ref, type Ref } from 'vue'

import { useResizablePanels } from './useResizablePanels'

// 两栏宽度/折叠/窄带语义（v2.7 §20 R1-R2）：TREK useResizablePanels 的等价断言。
// 挂一个宿主组件把 rootEl 指到一个给定宽度的桩元素上，再读回组合式的公开状态。
function harness(width: number) {
  const api: { panels?: ReturnType<typeof useResizablePanels> } = {}
  const Host = defineComponent({
    setup() {
      const el = ref<HTMLElement | null>(null) as Ref<HTMLElement | null>
      api.panels = useResizablePanels(el)
      return () =>
        h('div', {
          ref: (node: unknown) => {
            el.value = (node as HTMLElement) ?? null
          },
        })
    },
  })
  const wrapper = mount(Host)
  // happy-dom 里 clientWidth 只读：挂载后定义到元素上，再派发一次 resize 让组合式重测
  Object.defineProperty(wrapper.element, 'clientWidth', { value: width, configurable: true })
  window.dispatchEvent(new Event('resize'))
  return { panels: api.panels!, wrapper }
}

beforeEach(() => {
  localStorage.clear()
})

describe('useResizablePanels', () => {
  it('宽屏（工作台 ≥1024）：默认 340/300，折叠是意图态', () => {
    const { panels } = harness(1330)
    expect(panels.narrow.value).toBe(false)
    expect(panels.leftWidth.value).toBe(340)
    expect(panels.rightWidth.value).toBe(300)

    panels.toggleLeft()
    expect(panels.leftHidden.value).toBe(true)
    expect(panels.rightHidden.value).toBe(false)
    panels.toggleRight()
    expect(panels.rightCollapsed.value).toBe(true)
    panels.toggleLeft()
    expect(panels.leftCollapsed.value).toBe(false)
    expect(panels.leftHidden.value).toBe(false)
  })

  it('窄带（工作台 <1024）：单栏三态 left → 纯地图 → right，且不污染宽屏折叠意图', () => {
    const { panels } = harness(900)
    expect(panels.narrow.value).toBe(true)
    expect(panels.leftHidden.value).toBe(false)
    expect(panels.rightHidden.value).toBe(true)

    panels.toggleLeft()
    expect(panels.leftHidden.value).toBe(true)
    expect(panels.rightHidden.value).toBe(true)

    panels.toggleRight()
    expect(panels.leftHidden.value).toBe(true)
    expect(panels.rightHidden.value).toBe(false)

    // 窄带折叠走 narrowPanel，宽屏意图态保持原样（TREK 原文注释语义）
    expect(panels.leftCollapsed.value).toBe(false)
    expect(panels.rightCollapsed.value).toBe(false)
  })

  it('窄带夹紧：拖出来的宽值按「地图保底 360」压窄，存储值不动', () => {
    localStorage.setItem('ta-panel-left', '520')
    const { panels } = harness(600)
    // maxPanel = max(200, 600 - 360 - 20) = 220
    expect(panels.leftWidth.value).toBe(220)
    expect(localStorage.getItem('ta-panel-left')).toBe('520')
  })

  it('窄到装不下时夹到 MIN_SIDEBAR=200，绝不出现负数或 0 宽', () => {
    const { panels } = harness(300)
    expect(panels.leftWidth.value).toBe(200)
  })
})

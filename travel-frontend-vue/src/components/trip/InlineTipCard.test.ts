import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import InlineTipCard from './InlineTipCard.vue'

describe('InlineTipCard（内联提示卡）', () => {
  it('按 kind 输出基调 class 并渲染标题、图标与插槽内容', () => {
    const wrapper = mount(InlineTipCard, {
      props: { kind: 'warn', title: '备选方案' },
      slots: { default: '<p>若下雨改室内路线</p>' },
    })
    expect(wrapper.classes()).toContain('tip-card')
    expect(wrapper.classes()).toContain('kind-warn')
    expect(wrapper.find('.tip-title').text()).toBe('备选方案')
    expect(wrapper.find('svg').exists()).toBe(true)
    expect(wrapper.text()).toContain('若下雨改室内路线')
  })

  it('kind 默认 info', () => {
    const wrapper = mount(InlineTipCard, { props: { title: '实用提示' } })
    expect(wrapper.classes()).toContain('kind-info')
  })
})

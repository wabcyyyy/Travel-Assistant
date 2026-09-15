import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import AppPanel from './AppPanel.vue'
import Chip from './Chip.vue'
import EmptyState from './EmptyState.vue'
import SectionHead from './SectionHead.vue'
import SkeletonCard from './SkeletonCard.vue'
import StatTile from './StatTile.vue'
import Toolbar from './Toolbar.vue'

describe('components/ui primitives（令牌消费纪律）', () => {
  it('AppPanel 渲染标题，flat 变体去掉边框底色（class 由 theme.css 令牌驱动）', () => {
    const normal = mount(AppPanel, { props: { title: '即将出发' } })
    expect(normal.text()).toContain('即将出发')
    expect(normal.classes()).toContain('app-panel')
    expect(normal.classes()).not.toContain('is-flat')

    expect(mount(AppPanel, { props: { flat: true } }).classes()).toContain('is-flat')
  })

  it('AppPanel actions 插槽可见', () => {
    const wrapper = mount(AppPanel, {
      props: { title: 'x' },
      slots: { actions: '<button>新建</button>' },
    })
    expect(wrapper.find('.panel-actions button').text()).toBe('新建')
  })

  it('StatTile 渲染 label / value / sub', () => {
    const wrapper = mount(StatTile, { props: { label: '覆盖城市', value: 6, sub: '2 个国家/地区' } })
    expect(wrapper.text()).toContain('覆盖城市')
    expect(wrapper.find('.tile-value').text()).toBe('6')
    expect(wrapper.text()).toContain('2 个国家/地区')
  })

  it('EmptyState 渲染描述与动作插槽', () => {
    const wrapper = mount(EmptyState, {
      props: { description: '还没有行程' },
      slots: { default: '<button>去生成</button>' },
    })
    expect(wrapper.text()).toContain('还没有行程')
    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('Chip 按 tone 输出对应 class（颜色由令牌 class 承担，不内联色值）', () => {
    const wrapper = mount(Chip, { props: { tone: 'warning' }, slots: { default: '需复核' } })
    expect(wrapper.classes()).toContain('chip')
    expect(wrapper.classes()).toContain('tone-warning')
  })

  it('SectionHead 渲染标题与副标题', () => {
    const wrapper = mount(SectionHead, { props: { title: '今日', sub: '9月15日' } })
    expect(wrapper.find('.head-title').text()).toBe('今日')
    expect(wrapper.find('.head-sub').text()).toBe('9月15日')
  })

  it('SkeletonCard 复用全局 lp-skel-line 骨架件（3 行）', () => {
    expect(mount(SkeletonCard).findAll('.lp-skel-line').length).toBe(3)
  })

  it('Toolbar 基本挂载', () => {
    expect(mount(Toolbar).classes()).toContain('toolbar')
  })
})

import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import AppInput from './AppInput.vue'
import AppNumberInput from './AppNumberInput.vue'
import AppTextarea from './AppTextarea.vue'
import Segmented from './Segmented.vue'

describe('AppInput（自研文本输入）', () => {
  it('输入回传 update:modelValue；占位与 aria-label 生效', async () => {
    const onUpdate = vi.fn()
    const wrapper = mount(AppInput, {
      props: { modelValue: '', placeholder: '搜索行程', ariaLabel: '搜索', 'onUpdate:modelValue': onUpdate },
    })
    const input = wrapper.find('input')
    expect(input.attributes('placeholder')).toBe('搜索行程')
    expect(input.attributes('aria-label')).toBe('搜索')
    await input.setValue('东京')
    expect(onUpdate).toHaveBeenCalledWith('东京')
  })

  it('prefix 插槽与回车事件', async () => {
    const wrapper = mount(AppInput, { slots: { prefix: '<span class="p">@</span>' } })
    expect(wrapper.find('.input-prefix .p').exists()).toBe(true)
    await wrapper.find('input').trigger('keydown.enter')
    expect(wrapper.emitted('enter')).toBeTruthy()
  })
})

describe('AppNumberInput（自研数字输入）', () => {
  it('清空回传 null；失焦按 min/max 夹紧', async () => {
    const onUpdate = vi.fn()
    const wrapper = mount(AppNumberInput, {
      props: { modelValue: 5, 'onUpdate:modelValue': onUpdate },
    })
    await wrapper.find('input').setValue('')
    expect(onUpdate).toHaveBeenCalledWith(null)

    onUpdate.mockClear()
    const clamped = mount(AppNumberInput, {
      props: { modelValue: 120, min: 0, max: 100, 'onUpdate:modelValue': onUpdate },
    })
    await clamped.find('input').trigger('blur')
    expect(onUpdate).toHaveBeenCalledWith(100)
  })

  it('失焦按 precision 舍入', async () => {
    const onUpdate = vi.fn()
    const wrapper = mount(AppNumberInput, {
      props: { modelValue: 3.14159, precision: 2, 'onUpdate:modelValue': onUpdate },
    })
    await wrapper.find('input').trigger('blur')
    expect(onUpdate).toHaveBeenCalledWith(3.14)
  })
})

describe('AppTextarea（自研多行输入）', () => {
  it('rows 透传且输入回传', async () => {
    const onUpdate = vi.fn()
    const wrapper = mount(AppTextarea, {
      props: { modelValue: '', rows: 2, 'onUpdate:modelValue': onUpdate },
    })
    expect(wrapper.find('textarea').attributes('rows')).toBe('2')
    await wrapper.find('textarea').setValue('备注')
    expect(onUpdate).toHaveBeenCalledWith('备注')
  })
})

describe('Segmented（胶囊分段控件）', () => {
  const items = [
    { value: 'all', label: '全部', badge: 3 },
    { value: 'active', label: '计划中' },
    { value: 'done', label: '已完成' },
  ]

  it('radiogroup 语义：选中态 / 唯一 tab 停靠点 / 徽标', () => {
    const wrapper = mount(Segmented, {
      props: { modelValue: 'active', items, ariaLabel: '视图' },
    })
    expect(wrapper.find('[role="radiogroup"]').attributes('aria-label')).toBe('视图')
    const radios = wrapper.findAll('[role="radio"]')
    expect(radios.length).toBe(3)
    expect(radios[1].attributes('aria-checked')).toBe('true')
    expect(radios[1].attributes('tabindex')).toBe('0')
    expect(radios[0].attributes('tabindex')).toBe('-1')
    expect(wrapper.find('.seg-badge').text()).toBe('3')
  })

  it('点击与方向键都回传选择', async () => {
    const onUpdate = vi.fn()
    const wrapper = mount(Segmented, {
      props: { modelValue: 'all', items, 'onUpdate:modelValue': onUpdate },
    })
    await wrapper.findAll('[role="radio"]')[2].trigger('click')
    expect(onUpdate).toHaveBeenCalledWith('done')

    onUpdate.mockClear()
    await wrapper.findAll('[role="radio"]')[0].trigger('keydown', { key: 'ArrowRight' })
    expect(onUpdate).toHaveBeenCalledWith('active')
  })
})

import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'

import AppDialog from './AppDialog.vue'
import AppConfirmHost from './AppConfirmHost.vue'
import AppMenu from './AppMenu.vue'
import AppPopover from './AppPopover.vue'
import AppSheet from './AppSheet.vue'
import AppToastHost from './AppToastHost.vue'
import Sheet from './Sheet.vue'
import { confirmDialog, confirmService } from './confirm'
import { toast } from './toast'

afterEach(() => {
  document.body.innerHTML = ''
})

describe('AppDialog（自研对话框）', () => {
  it('打开时渲染到 body：dialog 语义 + 标题 + 焦点落在首个控件', async () => {
    const wrapper = mount(AppDialog, {
      props: { modelValue: false, title: '移动到其他天' },
      attachTo: document.body,
    })
    expect(document.body.querySelector('.dialog-panel')).toBeNull()

    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    const panel = document.body.querySelector('.dialog-panel')
    expect(panel).not.toBeNull()
    expect(panel!.getAttribute('role')).toBe('dialog')
    expect(panel!.getAttribute('aria-modal')).toBe('true')
    expect(panel!.getAttribute('aria-label')).toBe('移动到其他天')
    expect(document.activeElement).toBe(document.body.querySelector('.dialog-close'))
    wrapper.unmount()
  })

  it('Esc 与遮罩点击都会回传关闭；closeOnMask=false 时遮罩不关闭', async () => {
    const wrapper = mount(AppDialog, { props: { modelValue: true } })
    await flushPromises()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([false])
    expect(wrapper.emitted('close')).toBeTruthy()
    wrapper.unmount()

    const noMask = mount(AppDialog, { props: { modelValue: true, closeOnMask: false } })
    await flushPromises()
    const mask = document.body.querySelector('.dialog-mask')!
    mask.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    await nextTick()
    expect(noMask.emitted('update:modelValue')).toBeUndefined()
    noMask.unmount()
  })
})

describe('AppSheet（自研抽屉）', () => {
  it('btt 为默认形态，rtl 时面板进入右侧形态；size 落为 --sheet-size', async () => {
    const btt = mount(AppSheet, { props: { modelValue: true, title: '图鉴' } })
    await flushPromises()
    const bttPanel = document.body.querySelector('.sheet-panel')!
    expect(bttPanel.classList.contains('is-btt')).toBe(true)
    expect(bttPanel.getAttribute('role')).toBe('dialog')
    btt.unmount()
    document.body.innerHTML = ''

    const rtl = mount(AppSheet, { props: { modelValue: true, direction: 'rtl', size: '420px' } })
    await flushPromises()
    const rtlPanel = document.body.querySelector('.sheet-panel')!
    expect(rtlPanel.classList.contains('is-rtl')).toBe(true)
    expect((rtlPanel as HTMLElement).style.getPropertyValue('--sheet-size')).toBe('420px')
    rtl.unmount()
  })
})

describe('AppMenu（自研下拉菜单）', () => {
  const items = [
    { key: 'open', label: '翻开行程' },
    { key: 'delete', label: '删除行程', danger: true, divided: true },
    { key: 'locked', label: '禁用项', disabled: true },
  ]

  it('点击触发器打开：菜单项、分隔线、禁用态与焦点', async () => {
    const wrapper = mount(AppMenu, { props: { items, triggerLabel: '更多操作' }, attachTo: document.body })
    expect(wrapper.find('.menu-list').exists()).toBe(false)

    await wrapper.find('.menu-trigger').trigger('click')
    await flushPromises()

    expect(wrapper.find('.menu-trigger').attributes('aria-expanded')).toBe('true')
    const menuItems = wrapper.findAll('.menu-item')
    expect(menuItems.length).toBe(3)
    expect(menuItems[1].classes()).toContain('is-danger')
    expect(menuItems[2].attributes('disabled')).toBeDefined()
    expect(wrapper.find('.menu-divider').exists()).toBe(true)
    expect(document.activeElement).toBe(menuItems[0].element)
    wrapper.unmount()
  })

  it('点选回传 key 并关闭；方向键在项间移动焦点', async () => {
    const wrapper = mount(AppMenu, { props: { items }, attachTo: document.body })
    await wrapper.find('.menu-trigger').trigger('click')
    await flushPromises()

    await wrapper.findAll('.menu-item')[0].trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe(wrapper.findAll('.menu-item')[1].element)

    await wrapper.findAll('.menu-item')[0].trigger('click')
    expect(wrapper.emitted('select')?.[0]).toEqual(['open'])
    expect(wrapper.find('.menu-list').exists()).toBe(false)
    wrapper.unmount()
  })

  it('Esc 关闭并还原焦点到触发器；点击外部关闭', async () => {
    const wrapper = mount(AppMenu, { props: { items }, attachTo: document.body })
    await wrapper.find('.menu-trigger').trigger('click')
    await flushPromises()

    await wrapper.find('.menu-list').trigger('keydown', { key: 'Escape' })
    await nextTick()
    expect(wrapper.find('.menu-list').exists()).toBe(false)
    expect(document.activeElement).toBe(wrapper.find('.menu-trigger').element)

    await wrapper.find('.menu-trigger').trigger('click')
    await flushPromises()
    document.body.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.menu-list').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('AppPopover（轻量弹出层）', () => {
  it('点击触发器打开并聚焦首个输入；点击外部 / Esc 关闭', async () => {
    const wrapper = mount(AppPopover, {
      props: { open: false },
      slots: { trigger: '<button class="trg">时间</button>', default: '<input class="fld" />' },
      attachTo: document.body,
    })
    expect(wrapper.find('.pop-panel').exists()).toBe(false)

    await wrapper.find('.trg').trigger('click')
    await flushPromises()
    expect(wrapper.find('.pop-panel').exists()).toBe(true)
    expect(document.activeElement).toBe(wrapper.find('.fld').element)

    document.body.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.pop-panel').exists()).toBe(false)

    await wrapper.find('.trg').trigger('click')
    await flushPromises()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()
    expect(wrapper.find('.pop-panel').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('confirmDialog（自研确认框）', () => {
  afterEach(() => confirmService.resetForTests())

  it('宿主渲染消息与按钮；确认/取消分别 resolve true/false', async () => {
    const wrapper = mount(AppConfirmHost)
    const promise = confirmDialog('确认删除「浅草寺」？', { title: '删除确认', confirmText: '删除' })
    await nextTick()

    const host = document.body.querySelector('.dialog-panel')!
    expect(host.textContent).toContain('确认删除「浅草寺」？')
    expect(host.textContent).toContain('删除确认')

    ;(host.querySelector('.confirm-btn.is-primary') as HTMLButtonElement).click()
    await expect(promise).resolves.toBe(true)
    await nextTick()
    expect(confirmService.state.open).toBe(false)

    const promise2 = confirmDialog('再问一次')
    await nextTick()
    ;(document.body.querySelector('.confirm-btn') as HTMLButtonElement).click()
    await expect(promise2).resolves.toBe(false)
    wrapper.unmount()
  })

  it('遮罩关闭视为取消；重复调用时旧 Promise 保守收敛为 false', async () => {
    const wrapper = mount(AppConfirmHost)
    const first = confirmDialog('旧问题')
    const second = confirmDialog('新问题')
    await nextTick()
    await expect(first).resolves.toBe(false)
    expect(document.body.textContent).toContain('新问题')

    confirmService.confirm()
    await expect(second).resolves.toBe(true)
    wrapper.unmount()
  })
})

describe('toast 队列与宿主', () => {
  afterEach(() => toast.resetForTests())

  it('入队/手动关闭/可见上限 4 条', () => {
    toast.success('已移动', 0)
    toast.error('生成失败', 0)
    expect(toast.state.items.map((item) => item.type)).toEqual(['success', 'error'])

    toast.dismiss(toast.state.items[0].id)
    expect(toast.state.items.length).toBe(1)

    for (let i = 0; i < 6; i += 1) toast.info(`提示 ${i}`, 0)
    expect(toast.state.items.length).toBe(4)
  })

  it('宿主渲染最近消息，可点关闭', async () => {
    toast.success('已加入 D2', 0)
    const wrapper = mount(AppToastHost)
    await nextTick()

    const host = document.body.querySelector('.toast-host')!
    expect(host.getAttribute('role')).toBe('status')
    expect(host.textContent).toContain('已加入 D2')
    expect((host.querySelector('.toast-item') as HTMLElement).className).toContain('tone-success')

    ;(host.querySelector('.toast-close') as HTMLButtonElement).click()
    await nextTick()
    expect(toast.state.items.length).toBe(0)
    wrapper.unmount()
  })
})

describe('Sheet 薄封装', () => {
  it('visible 透传给 AppSheet 并渲染插槽', async () => {
    const wrapper = mount(Sheet, { props: { visible: true, title: '城市列表' }, slots: { default: '<p class="inner">内容</p>' } })
    await flushPromises()
    expect(document.body.querySelector('.sheet-panel')).not.toBeNull()
    expect(document.body.querySelector('.inner')?.textContent).toBe('内容')
    wrapper.unmount()
  })
})

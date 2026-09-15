import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SelectionBar from './SelectionBar.vue'
import { useItineraryStore } from '../../store/itinerary'
import { confirmService } from '../ui/confirm'
import type { ItineraryDetail } from '../../types/itinerary'

// 写操作在 API 边界替换：store 与 useItineraryActions 走真实实现，payload 才可信
const api = vi.hoisted(() => ({
  addItem: vi.fn(),
  updateItem: vi.fn(),
  deleteItem: vi.fn(),
  reorderItems: vi.fn(),
  applyPlans: vi.fn(),
  applyHotelOption: vi.fn(),
}))
vi.mock('../../api/itinerary', () => api)

const DETAIL = {
  id: 97,
  title: '杭州2日游',
  city: '杭州',
  days: 2,
  stayNights: 1,
  persons: 1,
  status: 2,
  totalAmount: 0,
  dayList: [
    {
      dayId: 101,
      dayNo: 1,
      items: [
        { id: 11, itemType: 'attraction', poiName: '浅草寺', address: 'A', latitude: 30, longitude: 120, cost: 50 },
        { id: 12, itemType: 'food', poiName: '楼外楼', startTime: '12:00:00', durationMin: 60 },
      ],
    },
    { dayId: 102, dayNo: 2, items: [] },
  ],
  budgetList: [],
} as unknown as ItineraryDetail

function buttonByText(text: string): HTMLButtonElement {
  const found = Array.from(document.querySelectorAll('button')).find((btn) =>
    btn.textContent?.trim().includes(text),
  )
  if (!found) throw new Error(`button not found: ${text}`)
  return found as HTMLButtonElement
}

async function mountBar(ids: number[] = [11, 12]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useItineraryStore().setDetail(DETAIL)
  const wrapper = mount(SelectionBar, {
    props: { selectedIds: ids },
    global: { plugins: [pinia] },
    attachTo: document.body,
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset())
  api.addItem.mockResolvedValue({ code: 200, message: 'ok', data: DETAIL })
  api.updateItem.mockResolvedValue({ code: 200, message: 'ok', data: DETAIL })
  api.deleteItem.mockResolvedValue({ code: 200, message: 'ok', data: null })
  confirmService.resetForTests()
  document.body.innerHTML = ''
})

describe('SelectionBar（选择态批量条）', () => {
  it('计数与操作按钮；复制到：逐项 addItem（不含时间字段）并清空选择', async () => {
    const wrapper = await mountBar()
    expect(wrapper.text()).toContain('已选 2 项')

    buttonByText('复制到').click()
    await flushPromises()
    expect(document.body.textContent).toContain('批量复制到')
    buttonByText('第 2 天').click()
    await flushPromises()

    expect(api.addItem).toHaveBeenCalledTimes(2)
    expect(api.addItem).toHaveBeenCalledWith(97, expect.objectContaining({ dayId: 102, poiName: '浅草寺' }))
    const second = api.addItem.mock.calls[1][1] as Record<string, unknown>
    expect(second.poiName).toBe('楼外楼')
    expect(second.startTime).toBeUndefined()
    expect(second.durationMin).toBeUndefined()
    expect(wrapper.emitted('clear')).toBeTruthy()
    wrapper.unmount()
  })

  it('移动到：逐项 updateItem(dayId)', async () => {
    const wrapper = await mountBar()
    buttonByText('移动到').click()
    await flushPromises()
    buttonByText('第 2 天').click()
    await flushPromises()

    expect(api.updateItem).toHaveBeenCalledTimes(2)
    expect(api.updateItem).toHaveBeenCalledWith(11, { dayId: 102 })
    expect(api.updateItem).toHaveBeenCalledWith(12, { dayId: 102 })
    expect(wrapper.emitted('clear')).toBeTruthy()
    wrapper.unmount()
  })

  it('删除：取消不删；确认后逐项 deleteItem 并清空选择', async () => {
    const wrapper = await mountBar()
    buttonByText('删除').click()
    await flushPromises()
    confirmService.cancel()
    await flushPromises()
    expect(api.deleteItem).not.toHaveBeenCalled()

    buttonByText('删除').click()
    await flushPromises()
    confirmService.confirm()
    await flushPromises()
    expect(api.deleteItem).toHaveBeenCalledTimes(2)
    expect(wrapper.emitted('clear')).toBeTruthy()
    wrapper.unmount()
  })

  it('部分失败：如实计数（成功 1 项、失败 1 项仍清空并提示）', async () => {
    api.deleteItem
      .mockResolvedValueOnce({ code: 200, message: 'ok', data: null })
      .mockRejectedValueOnce(new Error('boom'))
    const wrapper = await mountBar()
    buttonByText('删除').click()
    await flushPromises()
    confirmService.confirm()
    await flushPromises()

    expect(api.deleteItem).toHaveBeenCalledTimes(2)
    expect(wrapper.emitted('clear')).toBeTruthy()
    wrapper.unmount()
  })
})

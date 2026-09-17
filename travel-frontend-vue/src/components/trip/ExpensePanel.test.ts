import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import ExpensePanel from './ExpensePanel.vue'
import type { ItineraryDetail } from '../../types/itinerary'
import type { ExpenseVO } from '../../types/generated/contracts'
const api = vi.hoisted(() => ({ listExpenses: vi.fn(), createExpense: vi.fn(), updateExpense: vi.fn(), deleteExpense: vi.fn() }))
vi.mock('../../api/expenses', () => api)
vi.mock('../ui/confirm', () => ({ confirmDialog: vi.fn().mockResolvedValue(true) }))
const expense: ExpenseVO = { id: 1, itineraryId: 1, userId: 1, category: 'food', amount: '25.00', currency: 'CNY', dayNo: 1, itemId: 2, spentAt: '2026-09-17', paymentMethod: '现金', note: '午餐', createdAt: '2026-09-17T12:00:00' }
const detail = { id: 1, budgetList: [{ category: 'food', amount: 20 }], dayList: [{ dayId: 1, dayNo: 1, items: [{ id: 2, poiName: '餐厅' }] }] } as unknown as ItineraryDetail
function mountPanel() { return mount(ExpensePanel, { props: { detail }, global: { stubs: { AppDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /></div>' } } } }) }
beforeEach(() => {
  vi.clearAllMocks()
  api.listExpenses.mockResolvedValue({ data: { expenses: [expense], totals: [{ category: 'food', currency: 'CNY', amount: '25.00' }, { category: 'food', currency: 'USD', amount: '5.00' }] } })
})
describe('实际花费', () => {
  it('汇总、超支、币种隔离和点位跳转可用', async () => {
    const w = mountPanel(); await flushPromises()
    expect(w.text()).toContain('CNY 25.00')
    expect(w.get('.over').text()).toContain('预估 ¥20.00')
    expect(w.text()).toContain('不与人民币预算换算')
    expect(w.text()).toContain('现金'); expect(w.text()).toContain('午餐')
    await w.findAll('button').find(b => b.text() === '餐厅')!.trigger('click')
    expect(w.emitted('select-item')).toEqual([[2]])
  })
  it('创建使用十进制文本，保存后重新读取聚合', async () => {
    const w = mountPanel(); await flushPromises()
    await w.findAll('button').find(b => b.text() === '记一笔')!.trigger('click')
    await w.get('input[inputmode="decimal"]').setValue('0.30')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(api.createExpense).toHaveBeenCalledWith(1, expect.objectContaining({ amount: '0.30', currency: 'CNY' }))
    expect(api.listExpenses).toHaveBeenCalledTimes(2)
  })
  it('修改和删除沿用 expenseId', async () => {
    const w = mountPanel(); await flushPromises()
    await w.findAll('button').find(b => b.text() === '编辑')!.trigger('click')
    await w.get('input[inputmode="decimal"]').setValue('30.00')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(api.updateExpense).toHaveBeenCalledWith(1, expect.objectContaining({ amount: '30.00' }))
    await w.findAll('button').find(b => b.text() === '删除')!.trigger('click'); await flushPromises()
    expect(api.deleteExpense).toHaveBeenCalledWith(1)
  })
  it('读取失败可重试，非法金额不发请求', async () => {
    api.listExpenses.mockRejectedValueOnce(new Error('offline'))
    const w = mountPanel(); await flushPromises()
    expect(w.get('[role="alert"]').text()).toContain('读取失败')
    await w.findAll('button').find(b => b.text() === '重试')!.trigger('click'); await flushPromises()
    await w.findAll('button').find(b => b.text() === '记一笔')!.trigger('click')
    await w.get('input[inputmode="decimal"]').setValue('0.001')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(api.createExpense).not.toHaveBeenCalled()
    expect(w.text()).toContain('最多两位小数')
  })
})

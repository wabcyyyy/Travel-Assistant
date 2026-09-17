/**
 * 实际花费（C2.1）：类型走生成契约（expense 组登记进 CONTRACT_GROUPS 后由
 * export_contracts.py 导出），本模块只做 URL 与信封解包。
 */
import { requestDelete, requestGet, requestPost, requestPut } from './request'
import type * as Contracts from '../types/generated/contracts'

export type ExpenseVO = Contracts.ExpenseVO
export type ExpenseCategoryTotal = Contracts.ExpenseCategoryTotal
export type ExpenseListVO = Contracts.ExpenseListVO
export type ExpenseCreate = Contracts.ExpenseCreate
export type ExpenseUpdate = Contracts.ExpenseUpdate

export function listExpenses(itineraryId: number) {
  return requestGet<ExpenseListVO>(`/itinerary/${itineraryId}/expenses`)
}

export function createExpense(itineraryId: number, data: ExpenseCreate) {
  return requestPost<ExpenseVO>(`/itinerary/${itineraryId}/expenses`, data)
}

export function updateExpense(expenseId: number, data: ExpenseUpdate) {
  return requestPut<ExpenseVO>(`/itinerary/expenses/${expenseId}`, data)
}

export function deleteExpense(expenseId: number) {
  return requestDelete(`/itinerary/expenses/${expenseId}`)
}

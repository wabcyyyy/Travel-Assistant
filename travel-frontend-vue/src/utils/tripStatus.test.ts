/** 「今天」的口径：一律取**本地**日历日。
 *
 * 反面教材（2026-09-20 第 2 轮评审）：`new Date().toISOString().slice(0,10)` 取的是
 * UTC 日，在 UTC+8 的每天 00:00–07:59 仍是"昨天"——今天出发的行程显示成"1 天后"，
 * 昨天结束的行程还留在"即将出发"里。目标用户就在 UTC+8，所以这是每天清晨必现的错。
 */

import { describe, expect, it } from 'vitest'

import { daysUntil, localTodayISO } from './tripStatus'

describe('localTodayISO', () => {
  it('按本地日历日格式化，凌晨也算当天', () => {
    expect(localTodayISO(new Date(2026, 8, 20, 0, 30))).toBe('2026-09-20')
    expect(localTodayISO(new Date(2026, 8, 20, 23, 59))).toBe('2026-09-20')
    expect(localTodayISO(new Date(2026, 0, 5))).toBe('2026-01-05')
  })

  it('月/日补零，可直接与后端的 YYYY-MM-DD 做字典序比较', () => {
    expect(localTodayISO(new Date(2026, 9, 9))).toBe('2026-10-09')
  })
})

describe('daysUntil', () => {
  it('出发就是今天 → 0，且与 localTodayISO 同源（两端都是本地零点）', () => {
    const justAfterMidnight = new Date(2026, 8, 20, 0, 30)
    expect(daysUntil(localTodayISO(justAfterMidnight), justAfterMidnight)).toBe(0)
  })

  it('次日出发 → 1，已出发夹到 0', () => {
    const now = new Date(2026, 8, 20, 8, 0)
    expect(daysUntil('2026-09-21', now)).toBe(1)
    expect(daysUntil('2026-09-19', now)).toBe(0)
  })

  it('缺日期与坏日期返回 null，不返回 NaN', () => {
    expect(daysUntil(null)).toBeNull()
    expect(daysUntil(undefined)).toBeNull()
    expect(daysUntil('not-a-date')).toBeNull()
  })
})

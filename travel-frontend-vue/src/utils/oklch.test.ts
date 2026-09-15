import { describe, expect, it } from 'vitest'

import { oklchToHex } from './oklch'

describe('oklchToHex（地图 paint 用的色值换算）', () => {
  it('黑白端点精确', () => {
    expect(oklchToHex(1, 0, 0)).toBe('#ffffff')
    expect(oklchToHex(0, 0, 0)).toBe('#000000')
  })

  it('无彩度灰阶 r=g=b', () => {
    const hex = oklchToHex(0.5, 0, 0)
    const [r, g, b] = [1, 3, 5].map((i) => hex.slice(i, i + 2))
    expect(r).toBe(g)
    expect(g).toBe(b)
  })

  it('与 CSS 标准色对齐（oklch 红 ≈ #ff0000，容差 ±2/通道）', () => {
    const hex = oklchToHex(0.62796, 0.25768, 29.234)
    const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
    expect(Math.abs(channels[0] - 255)).toBeLessThanOrEqual(2)
    expect(channels[1]).toBeLessThanOrEqual(2)
    expect(channels[2]).toBeLessThanOrEqual(2)
  })

  it('输出恒为 7 位 hex（day-tint 令牌同源参数下可用）', () => {
    for (let hue = 0; hue < 360; hue += 45) {
      expect(oklchToHex(0.6, 0.11, hue)).toMatch(/^#[0-9a-f]{6}$/)
    }
  })
})

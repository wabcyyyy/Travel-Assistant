import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// v2.6 §19.2/§19.4 的令牌契约（机器可检）：
// 字体换成 Geist 自托管；day-tint 令牌存在且数值为 TREK 实测原值。
// 与 appearance.test.ts 同一思路：读源码文本断言，防止令牌被误改/回退。
// （vitest 下 import.meta.url 不是 file: 协议，用 cwd = travel-frontend-vue 定位）
const css = readFileSync(resolve(process.cwd(), 'src/styles/theme.css'), 'utf8')

describe('theme.css v2.6/v2.8 契约（字体 + day-tint）', () => {
  it('字体：Poppins 主字重自托管，Geist 保留为拉丁回退，Inter 已移除', () => {
    // v2.8 trek 视觉复刻：字体栈以 Poppins 打头（trek --font-system 实测首位），
    // Geist Sans 降为回退（trek --font-subtext 同款语义）；四个静态字重文件必须都在
    expect(css).toContain("font-family: 'Poppins'")
    for (const w of [400, 500, 600, 700]) {
      expect(css).toContain(`/fonts/poppins-latin-${w}.woff2`)
    }
    expect(css).toContain("font-family: 'Geist Sans'")
    expect(css).toContain('/fonts/geist-latin-var.woff2')
    expect(css).not.toContain("'Inter'")
    expect(css).toMatch(/--lp-font-ui:\s*'Poppins',\s*'Geist Sans'/)
  })

  it('day-tint 消费中的三档透明度为 TREK 实测原值', () => {
    // 只断言有 var() 消费者的令牌（badge/header/header-hover）；
    // activity/l-min/l-max 目前全站零消费，属同义反复，R5-8 移出断言。
    expect(css).toMatch(/--lp-day-tint-badge:\s*16%/)
    expect(css).toMatch(/--lp-day-tint-header:\s*8%/)
    expect(css).toMatch(/--lp-day-tint-header-hover:\s*14%/)
  })

  it('天色相：D1–D8 色相（默认 + teal 两套）与 8 个派生色齐备', () => {
    const hues = css.match(/--lp-day-h-\d:/g) || []
    // :root 8 个 + teal 覆盖 8 个
    expect(hues.length).toBeGreaterThanOrEqual(16)
    const colors = css.match(/--lp-day-\d:/g) || []
    expect(colors.length).toBeGreaterThanOrEqual(8)
    // 每个派生色都由 oklch 从 L/C/H 变量派生（亮度经构造落在 [l-min, l-max] 内）
    expect(css).toMatch(/--lp-day-1:\s*oklch\(var\(--lp-day-l\) var\(--lp-day-c\) var\(--lp-day-h-1\)\)/)
  })

  it('暗色档覆盖亮度与彩度（0.72 / 0.10）', () => {
    const dark = css.slice(css.indexOf('.dark {'))
    expect(dark).toMatch(/--lp-day-l:\s*0\.72/)
    expect(dark).toMatch(/--lp-day-c:\s*0\.1/)
  })
})

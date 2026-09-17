import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { externalMapLink, mapDirectionsUrl } from './geo'

// 深链语义 parity（Y4）：与后端 tests/test_deeplink_parity.py 读**同一份** case 文件
// （travel-agent-python/tests/golden/deeplink_cases.json），各钉各的当前协议口径
// （host+path 前缀+关键查询参数存在/缺席）。任何一侧单方面改语义都会在对侧测试
// 或本测试显形。两侧已确认的口径差异逐条见 deeplink_parity.md 差异表；DIFF_NOTES
// 是其在断言层的落点（src/callnative/坐标数值换算等实现细节不整串相等）。

type SideExpect = {
  host?: string
  path?: string
  params?: string[]
  absent_params?: string[]
  null?: boolean
}
type ParityCase = {
  name: string
  input: {
    name?: string
    city?: string
    latitude?: number
    longitude?: number
    stops?: { name: string; latitude?: number; longitude?: number }[]
  }
  backend: SideExpect
  frontend: SideExpect
}

const cases: ParityCase[] = (
  JSON.parse(
    readFileSync(resolve(process.cwd(), '../travel-agent-python/tests/golden/deeplink_cases.json'), 'utf8'),
  ) as { cases: ParityCase[] }
).cases

const DIFF_NOTES: Record<string, string> = {
  search_domestic_with_coords: 'D1：前端国内搜索顾虑 WGS84≠GCJ-02，一律按名称关键词；后端有坐标走高德 marker（待统一）。',
  search_zero_sentinel: 'D7：0/0 哨兵前端当无坐标走关键词；后端误判海外走谷歌（待统一）。',
  search_out_of_range_coords: 'D2：前端 90/180 校验拒绝越界坐标回落关键词；后端误判海外走谷歌（待统一）。',
  search_hanzi_foreign_city_no_coords: 'D3：前端按国内城市白名单把巴厘岛判海外走谷歌；后端按汉字兜底判国内走高德（待统一）。',
  route_domestic_four_stops: 'D5：高德 URI 前端限 1 个途经点、超出返回 null；后端无上限（待统一）。',
  route_foreign_seven_stops: 'D6：谷歌路线前端按移动端语义限 3 个途经点、超出返回 null；后端无上限（已知且接受）。',
  route_out_of_range_stop: 'D2 同源：越界坐标前端拒绝纳入路线；后端照常纳入（待统一）。',
}

function assertProtocol(url: string | null, expectSide: SideExpect): void {
  if (expectSide.null) {
    expect(url).toBeNull()
    return
  }
  expect(url).toBeTruthy()
  const parsed = new URL(url!)
  expect(parsed.hostname).toBe(expectSide.host)
  expect(parsed.pathname.startsWith(expectSide.path!)).toBe(true)
  for (const key of expectSide.params ?? []) {
    expect(parsed.searchParams.has(key)).toBe(true)
  }
  for (const key of expectSide.absent_params ?? []) {
    expect(parsed.searchParams.has(key)).toBe(false)
  }
}

describe.each(cases)('$name', (c) => {
  it('前端深链协议口径', () => {
    // 双向同步：两侧期望不同的 case 必须在 DIFF_NOTES（与差异表）登记；
    // 期望相同的 case 不允许登记——保证差异表不漏记、不过期。
    const differs = JSON.stringify(c.frontend) !== JSON.stringify(c.backend)
    if (differs) {
      expect(DIFF_NOTES[c.name]).toBeTruthy()
    } else {
      expect(DIFF_NOTES[c.name]).toBeUndefined()
    }
    if (c.input.stops) {
      assertProtocol(mapDirectionsUrl(c.input.stops.map((s) => ({ ...s })), c.input.city ?? null), c.frontend)
    } else {
      assertProtocol(
        externalMapLink(
          { name: c.input.name ?? '', latitude: c.input.latitude ?? null, longitude: c.input.longitude ?? null },
          c.input.city ?? null,
        ),
        c.frontend,
      )
    }
  })
})

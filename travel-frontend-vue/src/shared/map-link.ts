/**
 * 外部地图深链的安全出口（框架无关，Vue 与 React 共用）。
 *
 * 后端 `app/agent/data/map_link.py` 只产出两种深链：国内高德 URI、海外谷歌 Maps。
 * 契约字段（如酒店候选卡 `searchLink`）会原样进 `href`，因此渲染前必须过白名单：
 * 载荷里出现非白名单域名（改后端模板、旧版本残留、数据被改写）时**不渲染链接**，
 * 而不是把任意 URL 交给用户点。
 *
 * 取舍（审查 P1-5 点名的"前端常量或后端下发"）：用**前端常量**。理由——
 * 白名单是渲染侧的防御，不是业务数据；由后端下发等于给同一个静态事实再加一次
 * 线上往返与一个契约字段，且"白名单"本身要能被篡改的那份数据改变，就失去意义。
 * 与后端 `map_link.py` 的同源关系由两侧测试各自钉住域名集合（后端
 * tests/test_deeplink_parity.py、前端 deeplink.parity.test.ts 已在管深链形状）。
 */

/** 允许的深链主机（与后端 map_link 出口一一对应）。 */
export const MAP_LINK_HOSTS = ['uri.amap.com', 'www.google.com', 'google.com'] as const

/** 谷歌域下只有 /maps/ 路径是地图深链（同主机还有账号/广告等无关页面）。 */
const GOOGLE_PATH_PREFIX = '/maps'

export function safeMapLink(url: string | null | undefined): string {
  const text = (url || '').trim()
  if (!text) return ''
  let parsed: URL
  try {
    parsed = new URL(text)
  } catch {
    return ''
  }
  if (parsed.protocol !== 'https:') return ''
  const host = parsed.hostname.toLowerCase()
  if (!(MAP_LINK_HOSTS as readonly string[]).includes(host)) return ''
  if (host.endsWith('google.com') && !parsed.pathname.startsWith(GOOGLE_PATH_PREFIX)) return ''
  return parsed.toString()
}
// 封面单一来源（M4-④ §工程卫生 #7）：
// 城市封面 key 与目的地卡片数据在此集中维护，TripsView / HomeView 等视图统一引用，
// 勿在视图内重复定义 CITY_COVERS / DESTINATIONS。新增城市封面时仅改本文件。
import coverBeijing from '../assets/img/cover-beijing.webp'
import coverChengdu from '../assets/img/cover-chengdu.webp'
import coverChongqing from '../assets/img/cover-chongqing.webp'
import coverHangzhou from '../assets/img/cover-hangzhou.webp'
import coverShanghai from '../assets/img/cover-shanghai.webp'
import coverXian from '../assets/img/cover-xian.webp'
import coverFallback from '../assets/img/hero-handbook.webp'

/** 城市 → 封面图；key 与封面文件名对应，未命中走 coverForCity 回落 */
export const CITY_COVERS: Record<string, string> = {
  北京: coverBeijing,
  成都: coverChengdu,
  重庆: coverChongqing,
  杭州: coverHangzhou,
  上海: coverShanghai,
  西安: coverXian,
}

/** 未命中城市时的兜底封面（手册风通用图） */
export const COVER_FALLBACK = coverFallback

/** 首页「热门目的地」封面墙（点击直达生成页），渲染顺序即展示顺序 */
export const DESTINATIONS = [
  { name: '杭州', img: coverHangzhou },
  { name: '成都', img: coverChengdu },
  { name: '西安', img: coverXian },
  { name: '重庆', img: coverChongqing },
  { name: '北京', img: coverBeijing },
  { name: '上海', img: coverShanghai },
]

/**
 * 城市名 → 封面；支持「杭州市」「成都之旅」等带后缀文案的模糊匹配。
 * TripsView 卡片等以行程城市取图的渲染点统一走本函数。
 */
export function coverForCity(city: string | null | undefined): string {
  const name = (city || '').trim()
  if (CITY_COVERS[name]) return CITY_COVERS[name]
  for (const key of Object.keys(CITY_COVERS)) {
    if (name.includes(key)) return CITY_COVERS[key]
  }
  return COVER_FALLBACK
}

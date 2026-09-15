/**
 * 站间交通估算（v2.7 §20 R3；TREK 的「6h5min · 27.5km」分隔条等价物）。
 *
 * 我们去高德后没有路线 API，且原则是**不伪造数据**：这里出的是**本地直线估算**，
 * 界面一律带「≈」与「估算」字样的 title，不冒充实时路况。折算口径：
 * 直线距离 × 1.3（路网系数）→ ≤1.5km 记步行 4.5km/h，否则记驾车 25km/h（城市均速）。
 */
export interface TravelLeg {
  /** 折算后的路网距离（米） */
  distanceM: number
  minutes: number
  mode: 'walk' | 'drive'
}

interface Coord {
  latitude?: number | null
  longitude?: number | null
}

function coord(point: Coord): [number, number] | null {
  const lat = Number(point.latitude)
  const lng = Number(point.longitude)
  if (!Number.isFinite(lat) || !Number.isFinite(lng) || (lat === 0 && lng === 0)) return null
  return [lat, lng]
}

const EARTH_R = 6371000
/** 直线 → 路网折算系数；城市均速（km/h）分档 */
const ROAD_FACTOR = 1.3
const WALK_SPEED = 4.5
const DRIVE_SPEED = 25
const WALK_MAX_M = 1500

function haversineM(a: [number, number], b: [number, number]): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180
  const dLat = toRad(b[0] - a[0])
  const dLng = toRad(b[1] - a[1])
  const la1 = toRad(a[0])
  const la2 = toRad(b[0])
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLng / 2) ** 2
  return 2 * EARTH_R * Math.asin(Math.sqrt(h))
}

/** 两点都有坐标才出估算；缺坐标返回 null（界面如实不画分隔条）。 */
export function estimateLeg(from: Coord, to: Coord): TravelLeg | null {
  const a = coord(from)
  const b = coord(to)
  if (!a || !b) return null
  const distanceM = Math.round(haversineM(a, b) * ROAD_FACTOR)
  if (distanceM < 50) return null // 同一地点内的微距不画分隔条
  const mode: TravelLeg['mode'] = distanceM <= WALK_MAX_M ? 'walk' : 'drive'
  const speed = mode === 'walk' ? WALK_SPEED : DRIVE_SPEED
  return { distanceM, minutes: Math.max(1, Math.round((distanceM / 1000 / speed) * 60)), mode }
}

/** 分隔条文案：`步行 ≈ 12 分钟 · 0.9 公里`（距离口径与就近推荐一致） */
export function legText(leg: TravelLeg): string {
  const distance = leg.distanceM >= 1000 ? `${(leg.distanceM / 1000).toFixed(1)} 公里` : `${leg.distanceM} 米`
  const mode = leg.mode === 'walk' ? '步行' : '车程'
  return `${mode} ≈ ${leg.minutes} 分钟 · ${distance}`
}

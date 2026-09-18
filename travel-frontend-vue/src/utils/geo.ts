import { DOMESTIC_CITIES, DOMESTIC_PROVINCES } from '../constants/geo'
import { toGcj02 } from './coordinates'

const CITY_SET = new Set(DOMESTIC_CITIES)
const PROVINCE_SET = new Set(DOMESTIC_PROVINCES)

export function isForeignCity(city: string | null | undefined): boolean {
  const name = (city || '').trim()
  if (!name) return false
  if (CITY_SET.has(name) || PROVINCE_SET.has(name)) return false
  for (const province of PROVINCE_SET) {
    if (name.includes(province)) return false
  }
  return true
}

type Coordinates = { latitude?: number | null; longitude?: number | null }
type MapStop = Coordinates & { name: string }

export function hasValidCoordinates(stop: Coordinates): boolean {
  const { latitude, longitude } = stop
  return typeof latitude === 'number' && typeof longitude === 'number'
    && Number.isFinite(latitude) && Number.isFinite(longitude)
    && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180
    && !(latitude === 0 && longitude === 0)
}

export function externalMapLink(target: MapStop, city: string | null | undefined): string {
  // 空格分隔：多词城市名直接粘连会产出「New YorkTimes Square」类坏关键词。
  const keyword = [city?.trim(), target.name.trim()].filter(Boolean).join(' ')
  if (isForeignCity(city)) {
    const query = hasValidCoordinates(target) ? `${target.latitude},${target.longitude}` : keyword
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`
  }
  // OTM/Nominatim 提供 WGS84，不能把原始坐标当高德 GCJ-02 标记；国内按名称核实。
  return `https://uri.amap.com/search?keyword=${encodeURIComponent(keyword)}`
}

export function mapDirectionsUrl(stops: MapStop[], city: string | null | undefined): string | null {
  const points = stops.filter(hasValidCoordinates)
  if (points.length < 2) return null
  const first = points[0]!
  const last = points[points.length - 1]!
  const middle = points.slice(1, -1)
  if (isForeignCity(city)) {
    // 移动浏览器最多支持 3 个途经点；不静默截断而冒充全天路线。
    if (middle.length > 3) return null
    const format = (p: MapStop) => `${p.latitude},${p.longitude}`
    const params = new URLSearchParams({ api: '1', origin: format(first), destination: format(last) })
    if (middle.length) params.set('waypoints', middle.map(format).join('|'))
    return `https://www.google.com/maps/dir/?${params}`
  }
  // 高德驾车 URI 最多支持一个途经点，超过上限时由界面提示分段核实。
  if (middle.length > 1) return null
  const format = (p: MapStop) => {
    const [lat, lon] = toGcj02(p.latitude!, p.longitude!)
    return `${lon},${lat}`
  }
  const params = new URLSearchParams({
    from: format(first), to: format(last), mode: 'car', callnative: '0',
  })
  if (middle.length) params.set('via', format(middle[0]!))
  return `https://uri.amap.com/navigation?${params}`
}

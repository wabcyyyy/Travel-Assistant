import { AttributionControl, ScaleControl, type Map as MapLibreMap } from 'maplibre-gl'

import { basemapUrlForScheme } from '../constants/map'

const COUNTRIES_GEOJSON_URL = '/geo/countries-simplified.json'

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/**
 * 署名（license 要求，SPEC §20 R0）：紧凑控件常驻右下。
 * 三链（OpenFreeMap / © OpenMapTiles / OpenStreetMap）由 OFM 的 TileJSON 自带，
 * 控件会自行收集——线上实测：再给 customAttribution 会整份重复，故不给。
 */
export function addAttribution(map: MapLibreMap): void {
  map.addControl(new AttributionControl({ compact: true }), 'bottom-right')
}

/** 比例尺（三处地图共用）。 */
export function addScaleBar(map: MapLibreMap): void {
  map.addControl(new ScaleControl({ maxWidth: 90, unit: 'metric' }), 'bottom-left')
}

/**
 * 底图随外观切换（v2.7 §20 R0）：html.dark 变化 → setStyle 换样式文档。
 * `style.load` 在初始样式与每次 setStyle 之后都会触发（TREK 的 VectorBasemap 依赖同一
 * 语义重挂图层），调用方在回调里重挂自己 addSource/addLayer 的产物——setStyle 会把它们清掉；
 * marker 是 DOM 覆盖物，不受影响。返回解绑函数。
 */
export function watchBasemapScheme(map: MapLibreMap, onStyleReady: () => void): () => void {
  let current = basemapUrlForScheme()
  map.on('style.load', onStyleReady)
  const observer = new MutationObserver(() => {
    const next = basemapUrlForScheme()
    if (next === current) return
    current = next
    map.setStyle(next)
  })
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
  return () => {
    observer.disconnect()
    map.off('style.load', onStyleReady)
  }
}

const EMPTY_COUNTRY_FILTER = ['==', ['get', 'iso'], ''] as never

/**
 * 「去过的国家」高亮层（Atlas 专用）：底图自带国界后这里只叠一层着色覆盖层，
 * filter 初始不匹配任何国家，`setVisitedCountries` 按 scope 更新。
 * GeoJSON 取自仓内文件；失败不抛——没有高亮也要能出点位。
 */
export async function addVisitedCountriesLayer(map: MapLibreMap): Promise<boolean> {
  try {
    const response = await fetch(COUNTRIES_GEOJSON_URL)
    const data = await response.json()
    map.addSource('countries', { type: 'geojson', data })
    map.addLayer({
      id: 'countries-fill',
      type: 'fill',
      source: 'countries',
      filter: EMPTY_COUNTRY_FILTER,
      paint: {
        'fill-color': cssVar('--lp-accent', '#111827'),
        'fill-opacity': 0.22,
      },
    })
    map.addLayer({
      id: 'countries-line',
      type: 'line',
      source: 'countries',
      filter: EMPTY_COUNTRY_FILTER,
      paint: {
        'line-color': cssVar('--lp-accent', '#111827'),
        'line-width': 1.2,
        'line-opacity': 0.55,
      },
    })
    return true
  } catch {
    return false
  }
}

/** 按 scope 的 highlightCountryCodes 更新高亮层 filter（数据是 iso 码数组）。 */
export function setVisitedCountries(map: MapLibreMap, codes: string[]): void {
  if (!map.getLayer('countries-fill')) return
  const filter = (codes.length
    ? ['in', ['get', 'iso'], ['literal', codes]]
    : EMPTY_COUNTRY_FILTER) as never
  map.setFilter('countries-fill', filter)
  map.setFilter('countries-line', filter)
}

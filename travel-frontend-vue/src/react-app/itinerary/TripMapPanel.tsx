import { useEffect, useMemo, useRef, useState } from 'react'
import { LngLatBounds, Map, Marker, Popup } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { DayPlan } from '../../types/itinerary'
import { Icon } from '../shared/Icon'
import {
  amapLink,
  buildPins,
  dayPinColor,
  estimatedPinCount,
  googleMapsLink,
  missingCoordCount,
} from './mapPins'
import type { MapPin } from './mapPins'

const OPENFREEMAP_LIBERTY = 'https://tiles.openfreemap.org/styles/liberty'

/** 详情页地图卡：全行程 pin（按天着色）+ 逐日路线 + 深链弹窗。
 * estimated 点位带虚线徽章（L6 精神：地图上看得出"这个位置是估的"）；
 * 无坐标点位画不出来，脚注如实交代数量。 */
export function TripMapPanel({
  days,
  activeKey,
  onSelect,
}: {
  days: DayPlan[]
  activeKey: string | null
  onSelect: (pin: MapPin) => void
}) {
  const pins = useMemo(() => buildPins(days), [days])
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<Map | null>(null)
  const loadedRef = useRef(false)
  const pinsRef = useRef(pins)
  pinsRef.current = pins
  const popupRef = useRef<Popup | null>(null)
  const markersRef = useRef<Marker[]>([])
  // 底图拉取失败（403/断网）时地图是整片留白——DOM pin 仍在，给出可见解释而不是无声米色
  const [tilesFailed, setTilesFailed] = useState(false)
  // onSelect 由父组件内联传入（每次渲染都是新引用），经 ref 消费避免 pin 反复重建
  const selectRef = useRef(onSelect)
  selectRef.current = onSelect

  useEffect(() => {
    const container = containerRef.current
    if (!container || mapRef.current) return
    const map = new Map({
      container,
      style: OPENFREEMAP_LIBERTY,
      center: [104.07, 30.66],
      zoom: 10,
      attributionControl: { compact: true },
    })
    mapRef.current = map
    map.on('error', (event) => {
      const status = (event.error as { status?: number } | undefined)?.status
      if (status === undefined || status >= 400) setTilesFailed(true)
    })
    map.on('load', () => {
      loadedRef.current = true
      syncRoutes(map, pinsRef.current)
    })
    return () => {
      popupRef.current?.remove()
      markersRef.current.forEach((marker) => marker.remove())
      markersRef.current = []
      map.remove()
      mapRef.current = null
      loadedRef.current = false
    }
  }, [])

  // 路线层：style load 完成后写入；天数集合在本页固定，只更新数据
  useEffect(() => {
    const map = mapRef.current
    if (map && loadedRef.current) syncRoutes(map, pins)
  }, [pins])

  // pin 重建 + 视野收敛
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    markersRef.current.forEach((marker) => marker.remove())
    markersRef.current = pins.map((pin) => {
      // maplibre 会把定位 transform 内联在标记根元素上，旋转视觉必须放内层
      const wrapper = document.createElement('div')
      wrapper.className = 'map-pin-wrap'
      const element = document.createElement('button')
      element.type = 'button'
      element.className =
        'map-pin' + (pin.estimated ? ' is-estimated' : '') + (pin.key === activeKey ? ' is-active' : '')
      element.style.background = dayPinColor(pin.dayNo)
      element.setAttribute('aria-label', `第 ${pin.dayNo} 天 ${pin.poiName}`)
      const label = document.createElement('span')
      label.textContent = pin.dayNo.toString()
      element.append(label)
      element.addEventListener('click', (event) => {
        event.stopPropagation()
        selectRef.current(pin)
        showPopup(pin)
      })
      wrapper.append(element)
      const marker = new Marker({ element: wrapper }).setLngLat([pin.longitude, pin.latitude]).addTo(map)
      return marker
    })
    if (pins.length) {
      const bounds = new LngLatBounds([pins[0].longitude, pins[0].latitude], [pins[0].longitude, pins[0].latitude])
      pins.forEach((pin) => bounds.extend([pin.longitude, pin.latitude]))
      map.fitBounds(bounds, { padding: 56, maxZoom: 14, duration: 0 })
    }
  }, [pins, activeKey])

  const showPopup = (pin: MapPin) => {
    const map = mapRef.current
    if (!map) return
    popupRef.current?.remove()
    const content = document.createElement('div')
    content.className = 'map-pop'
    const name = document.createElement('strong')
    name.textContent = pin.poiName
    const meta = document.createElement('small')
    meta.textContent = `第 ${pin.dayNo} 天${pin.startTime ? ` · ${pin.startTime}` : ''}${pin.estimated ? ' · 位置为估算' : ''}`
    const links = document.createElement('div')
    links.className = 'map-pop-links'
    const addLink = (label: string, href: string) => {
      if (!href) return
      const anchor = document.createElement('a')
      anchor.href = href
      anchor.target = '_blank'
      anchor.rel = 'noreferrer'
      anchor.textContent = label
      links.append(anchor)
    }
    addLink('高德核实', amapLink(pin))
    addLink('Google 核实', googleMapsLink(pin))
    content.append(name, meta, links)
    popupRef.current = new Popup({ offset: 18, closeButton: false })
      .setLngLat([pin.longitude, pin.latitude])
      .setDOMContent(content)
      .addTo(map)
  }

  const hidden = missingCoordCount(days)
  const estimated = estimatedPinCount(pins)

  if (!pins.length) {
    return <div className="trip-map is-empty"><Icon name="pin" size={20} /><p>这一趟还没有带坐标的点位。</p></div>
  }
  return <div className="trip-map-wrap">
    <div className="trip-map" ref={containerRef} aria-label="行程地图" />
    {tilesFailed && (
      <div className="map-tiles-fallback" role="status">
        底图暂时加载不出来（可能是网络受限），各天点位仍标在图上，点 pin 可跳转地图查看位置。
      </div>
    )}
    <p className="trip-map-note">
      {estimated > 0 && <span className="trip-map-estimated">估算点位 {estimated} 个（图上虚线角标）</span>}
      {hidden > 0 && <span>无坐标隐藏 {hidden} 个</span>}
      <span>底图 OpenFreeMap · 点 pin 跳转地图核实位置</span>
    </p>
  </div>
}

/** 逐日路线层：每天一条折线连接当日有序点位。 */
function syncRoutes(map: Map, pins: MapPin[]) {
  const byDay = new Map<number, MapPin[]>()
  pins.forEach((pin) => {
    const list = byDay.get(pin.dayNo) || []
    list.push(pin)
    byDay.set(pin.dayNo, list)
  })
  for (const [dayNo, list] of byDay) {
    const sourceId = `route-day-${dayNo}`
    const line = list.length >= 2
      ? {
          type: 'Feature' as const,
          geometry: { type: 'LineString' as const, coordinates: list.map((pin) => [pin.longitude, pin.latitude]) },
          properties: {},
        }
      : null
    const source = map.getSource(sourceId) as GeoJSONSource | undefined
    if (source) {
      source.setData(line ?? { type: 'FeatureCollection', features: [] })
      continue
    }
    map.addSource(sourceId, { type: 'geojson', data: line ?? { type: 'FeatureCollection', features: [] } })
    if (!map.getLayer(`${sourceId}-line`)) {
      map.addLayer({
        id: `${sourceId}-line`,
        type: 'line',
        source: sourceId,
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': dayPinColor(dayNo), 'line-width': 2.5, 'line-opacity': 0.65, 'line-dasharray': [2, 2] },
      })
    }
  }
}

<template>
  <div ref="mapContainer" class="map-container"></div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { loadAmap } from '../utils/amap'
import type { TripItem } from '../types/itinerary'

export interface MapItem extends TripItem {
  dayNo: number
}

const props = withDefaults(
  defineProps<{
    items: MapItem[]
    highlightId?: number | null
    routeDay?: number | null
    center?: [number, number]
    zoom?: number
  }>(),
  {
    highlightId: null,
    routeDay: null,
    center: () => [116.4074, 39.9042] as [number, number],
    zoom: 12,
  }
)

const emit = defineEmits<{ (e: 'select', id: number | null): void }>()

const DAY_COLORS = [
  '#5470c6',
  '#91cc75',
  '#fac858',
  '#ee6666',
  '#73c0de',
  '#3ba272',
  '#fc8452',
  '#9a60b4',
  '#ea7ccc',
]

const TYPE_LABEL: Record<string, string> = {
  attraction: '景点',
  food: '餐饮',
  hotel: '酒店',
  transport: '交通',
}

const mapContainer = ref<HTMLDivElement>()
let AMap: any = null
let map: any = null
let markers: any[] = []
let polylines: any[] = []
let infoWindow: any = null

function colorOf(dayNo: number) {
  return DAY_COLORS[(dayNo - 1) % DAY_COLORS.length]
}

function markerContent(item: MapItem, index: number, highlighted: boolean) {
  const bg = colorOf(item.dayNo)
  const border = highlighted ? '2px solid #ff4d4f' : '2px solid #ffffff'
  const z = highlighted ? 'z-index: 9999;' : ''
  const size = highlighted ? 30 : 24
  return (
    `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${bg};` +
    `border:${border};color:#fff;font-size:12px;font-weight:700;display:flex;align-items:center;` +
    `justify-content:center;box-shadow:0 2px 6px rgba(0,0,0,0.3);${z}">${index + 1}</div>`
  )
}

function buildMarkers() {
  clearMarkers()
  const located = props.items.filter((it) => it.latitude != null && it.longitude != null)
  if (!map || !located.length) return
  located.forEach((item, index) => {
    const marker = new AMap.Marker({
      position: [Number(item.longitude), Number(item.latitude)],
      content: markerContent(item, index, item.id === props.highlightId),
      offset: new AMap.Pixel(-12, -12),
      title: item.poiName,
    })
    marker.on('click', () => {
      emit('select', item.id ?? null)
      openInfoWindow(item, marker)
    })
    marker.setMap(map)
    markers.push(marker)
  })
  map.setFitView(markers)
}

function openInfoWindow(item: MapItem, marker: any) {
  if (!infoWindow) {
    infoWindow = new AMap.InfoWindow({ offset: new AMap.Pixel(0, -28) })
  }
  const escapeHtml = (value: string) => {
    const entities: Record<string, string> = {
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }
    return value.replace(/[&<>"']/g, (ch) => entities[ch])
  }
  const name = escapeHtml(item.poiName || '')
  const address = item.address ? escapeHtml(item.address) : ''
  const html = [
    `<div style="padding:4px 8px;min-width:160px">`,
    `<div style="font-weight:700;margin-bottom:4px">${name}</div>`,
    `<div style="color:#666;font-size:12px">${TYPE_LABEL[item.itemType] || item.itemType} · 第${item.dayNo}天</div>`,
    address ? `<div style="color:#666;font-size:12px;margin-top:2px">${address}</div>` : '',
    `</div>`,
  ].join('')
  infoWindow.setContent(html)
  infoWindow.open(map, marker.getPosition())
}

function clearMarkers() {
  markers.forEach((m) => m.setMap(null))
  markers = []
}

function clearRoutes() {
  polylines.forEach((p) => p.setMap(null))
  polylines = []
}

function drawRoute(dayNo: number) {
  clearRoutes()
  const points = props.items
    .filter((it) => it.dayNo === dayNo && it.latitude != null && it.longitude != null)
    .sort((a, b) => (a.sortNo ?? 0) - (b.sortNo ?? 0))
    .map((it) => [Number(it.longitude), Number(it.latitude)])
  if (points.length < 2) return

  const driving = new AMap.Driving({ policy: AMap.DrivingPolicy.LEAST_TIME, hideMarkers: true })
  const waypoints = points.slice(1, -1)
  driving.search(
    points[0],
    points[points.length - 1],
    { waypoints },
    (_status: string, result: any) => {
      const route = result?.routes?.[0]
      if (!route) return
      const path: [number, number][] = []
      route.steps.forEach((step: any) => {
        step.path.forEach((p: any) => path.push([p.lng, p.lat]))
      })
      const polyline = new AMap.Polyline({
        path,
        strokeColor: colorOf(dayNo),
        strokeWeight: 6,
        strokeOpacity: 0.8,
        strokeStyle: 'solid',
        lineJoin: 'round',
      })
      polyline.setMap(map)
      polylines.push(polyline)
      map.setFitView([...markers, polyline])
    }
  )
}

watch(
  () => props.items,
  () => {
    if (!map) return
    buildMarkers()
    if (props.routeDay != null) drawRoute(props.routeDay)
  },
  { deep: true }
)

watch(
  () => props.highlightId,
  () => {
    if (!map) return
    buildMarkers()
  }
)

watch(
  () => props.routeDay,
  (day) => {
    if (!map) return
    if (day == null) {
      clearRoutes()
      map.setFitView(markers)
    } else {
      drawRoute(day)
    }
  }
)

onMounted(async () => {
  try {
    AMap = await loadAmap()
    AMap.plugin(['AMap.Driving'], () => {
      map = new AMap.Map(mapContainer.value, {
        center: props.center,
        zoom: props.zoom,
        mapStyle: 'amap://styles/whitesmoke',
      })
      buildMarkers()
      if (props.routeDay != null) drawRoute(props.routeDay)
    })
  } catch (err) {
    console.error('地图加载失败:', err)
  }
})

onBeforeUnmount(() => {
  clearMarkers()
  clearRoutes()
  if (infoWindow) {
    infoWindow.close()
    infoWindow = null
  }
  if (map) {
    map.destroy()
    map = null
  }
})
</script>

<style scoped>
.map-container {
  width: 100%;
  height: 100%;
  min-height: 320px;
}
</style>

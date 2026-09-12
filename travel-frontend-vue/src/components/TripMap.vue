<template>
  <div class="map-wrap">
    <div ref="mapContainer" class="map-container"></div>
    <!-- a11y §5.5 #4：地图标记键盘可达替代方案。
         高德 Marker/Leaflet 图标非可靠可聚焦 DOM，改用图外标记点列表（视觉隐藏、
         屏幕阅读器可读）：Tab 聚焦 + Enter/Space 激活，触发与鼠标点击相同的选中事件与信息窗。 -->
    <ul v-if="locatedItems().length" class="sr-only marker-list" aria-label="地图标记点列表">
      <li v-for="(item, index) in locatedItems()" :key="item.id ?? index">
        <button
          type="button"
          @click="activateItem(item)"
          @keydown.enter.prevent="activateItem(item)"
          @keydown.space.prevent="activateItem(item)"
        >
          {{ index + 1 }}. {{ item.poiName }}（第{{ item.dayNo }}天·{{ TYPE_LABEL[item.itemType] || item.itemType }}）
        </button>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { loadAmap } from '../utils/amap'
import { loadLeaflet } from '../utils/leaflet'
import { isForeignCity } from '../utils/geo'
import type { TripItem } from '../types/itinerary'

export interface MapItem extends TripItem {
  dayNo: number
}

const props = withDefaults(
  defineProps<{
    items: MapItem[]
    city?: string
    highlightId?: number | null
    routeDay?: number | null
    center?: [number, number]
    zoom?: number
  }>(),
  {
    city: '',
    highlightId: null,
    routeDay: null,
    center: () => [116.4074, 39.9042] as [number, number],
    zoom: 12,
  }
)

const emit = defineEmits<{ (e: 'select', id: number | null): void }>()

// 国外目的地用 Leaflet+OSM（免 key），国内用高德 JSAPI。
const isForeign = computed(() => isForeignCity(props.city))

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
let engine: 'amap' | 'leaflet' | null = null
let AMap: any = null
let L: any = null
let map: any = null
let markers: any[] = []
let polylines: any[] = []
let infoWindow: any = null

function colorOf(dayNo: number) {
  return DAY_COLORS[(dayNo - 1) % DAY_COLORS.length]
}

function locatedItems() {
  return props.items.filter((it) => it.latitude != null && it.longitude != null)
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

function escapeHtml(value: string) {
  const entities: Record<string, string> = {
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }
  return value.replace(/[&<>"']/g, (ch) => entities[ch])
}

function infoHtml(item: MapItem) {
  const name = escapeHtml(item.poiName || '')
  const address = item.address ? escapeHtml(item.address) : ''
  return [
    `<div style="padding:4px 8px;min-width:160px">`,
    `<div style="font-weight:700;margin-bottom:4px">${name}</div>`,
    `<div style="color:#666;font-size:12px">${TYPE_LABEL[item.itemType] || item.itemType} · 第${item.dayNo}天</div>`,
    address ? `<div style="color:#666;font-size:12px;margin-top:2px">${address}</div>` : '',
    `</div>`,
  ].join('')
}

function clearMarkers() {
  if (!markers.length) return
  if (engine === 'amap') markers.forEach((m) => m.setMap(null))
  else if (engine === 'leaflet') markers.forEach((m) => m.remove())
  markers = []
}

function clearRoutes() {
  if (!polylines.length) return
  if (engine === 'amap') polylines.forEach((p) => p.setMap(null))
  else if (engine === 'leaflet') polylines.forEach((p) => p.remove())
  polylines = []
}

function fitMarkers() {
  if (!map) return
  const points = locatedItems()
  if (engine === 'amap' && markers.length) {
    map.setFitView(markers)
  } else if (engine === 'leaflet' && points.length) {
    map.fitBounds(L.latLngBounds(points.map((it) => [Number(it.latitude), Number(it.longitude)])))
  }
}

/**
 * 统一激活入口：选中行程项并打开对应信息窗（高德 InfoWindow / Leaflet Popup）。
 * 鼠标点击标记与键盘「标记点列表」激活共用，保证两条路径行为一致。
 */
function activateItem(item: MapItem) {
  emit('select', item.id ?? null)
  const index = locatedItems().indexOf(item)
  const marker = markers[index]
  if (!marker) return
  if (engine === 'amap') {
    if (!infoWindow) infoWindow = new AMap.InfoWindow({ offset: new AMap.Pixel(0, -28) })
    infoWindow.setContent(infoHtml(item))
    infoWindow.open(map, marker.getPosition())
  } else if (engine === 'leaflet') {
    marker.bindPopup(infoHtml(item)).openPopup()
  }
}

function buildMarkers() {
  clearMarkers()
  const located = locatedItems()
  if (!map || !located.length) return
  if (engine === 'amap') {
    located.forEach((item, index) => {
      const marker = new AMap.Marker({
        position: [Number(item.longitude), Number(item.latitude)],
        content: markerContent(item, index, item.id === props.highlightId),
        offset: new AMap.Pixel(-12, -12),
        title: item.poiName,
      })
      marker.on('click', () => activateItem(item))
      marker.setMap(map)
      markers.push(marker)
    })
  } else if (engine === 'leaflet') {
    located.forEach((item, index) => {
      const icon = L.divIcon({
        html: markerContent(item, index, item.id === props.highlightId),
        className: '',
        iconSize: [24, 24],
        iconAnchor: [12, 12],
      })
      const marker = L.marker([Number(item.latitude), Number(item.longitude)], {
        icon,
        title: item.poiName,
      })
      marker.on('click', () => activateItem(item))
      marker.addTo(map)
      markers.push(marker)
    })
  }
  fitMarkers()
}

function drawRoute(dayNo: number) {
  clearRoutes()
  const points = props.items
    .filter((it) => it.dayNo === dayNo && it.latitude != null && it.longitude != null)
    .sort((a, b) => (a.sortNo ?? 0) - (b.sortNo ?? 0))
  if (points.length < 2) return
  if (engine === 'amap') {
    const path: [number, number][] = points.map(
      (it) => [Number(it.longitude), Number(it.latitude)] as [number, number]
    )
    const driving = new AMap.Driving({ policy: AMap.DrivingPolicy.LEAST_TIME, hideMarkers: true })
    const waypoints = path.slice(1, -1)
    driving.search(path[0], path[path.length - 1], { waypoints }, (_status: string, result: any) => {
      const route = result?.routes?.[0]
      if (!route) return
      const routePath: [number, number][] = []
      route.steps.forEach((step: any) => {
        step.path.forEach((p: any) => routePath.push([p.lng, p.lat]))
      })
      const polyline = new AMap.Polyline({
        path: routePath,
        strokeColor: colorOf(dayNo),
        strokeWeight: 6,
        strokeOpacity: 0.8,
        strokeStyle: 'solid',
        lineJoin: 'round',
      })
      polyline.setMap(map)
      polylines.push(polyline)
      map.setFitView([...markers, polyline])
    })
  } else if (engine === 'leaflet') {
    // 国外无路线服务 key：按坐标画直线示意，如实标注而非伪造真实路况。
    const latLngs = points.map((it) => [Number(it.latitude), Number(it.longitude)] as [number, number])
    const polyline = L.polyline(latLngs, { color: colorOf(dayNo), weight: 6, opacity: 0.8 })
    polyline.addTo(map)
    polylines.push(polyline)
    map.fitBounds(L.latLngBounds(latLngs))
  }
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
      fitMarkers()
    } else {
      drawRoute(day)
    }
  }
)

async function initAmap() {
  AMap = await loadAmap()
  AMap.plugin(['AMap.Driving'], () => {
    engine = 'amap'
    map = new AMap.Map(mapContainer.value, {
      center: props.center,
      zoom: props.zoom,
      mapStyle: 'amap://styles/whitesmoke',
    })
    buildMarkers()
    if (props.routeDay != null) drawRoute(props.routeDay)
  })
}

async function initLeaflet() {
  L = await loadLeaflet()
  engine = 'leaflet'
  map = L.map(mapContainer.value, { center: [props.center[1], props.center[0]], zoom: props.zoom })
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 18,
  }).addTo(map)
  buildMarkers()
  if (props.routeDay != null) drawRoute(props.routeDay)
}

onMounted(async () => {
  try {
    // 海外且无任何有效坐标：不加载地图引擎（父层已展示空态说明）。
    if (isForeign.value && locatedItems().length === 0) return
    if (isForeign.value) await initLeaflet()
    else await initAmap()
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
    map.destroy ? map.destroy() : map.remove()
    map = null
  }
})
</script>

<style scoped>
.map-wrap {
  position: relative;
}

.map-container {
  width: 100%;
  height: 100%;
  min-height: 320px;
}

/* 键盘可达标记点列表：视觉隐藏，仅屏幕阅读器/键盘用户可用（不遮挡地图交互） */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  border: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}
</style>

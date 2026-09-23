<template>
  <div class="trip-map">
    <div
      ref="mapEl"
      class="map-canvas"
      role="img"
      :aria-label="`行程地图：已标出 ${visibleItems.length} 个点位`"
    ></div>

    <!-- 地图工具（v2.6 §19.3）：按天可见性 + 路线开关 -->
    <div class="map-tools">
      <div class="day-toggles" role="group" aria-label="按天显示">
        <button
          v-for="d in days"
          :key="d.dayId"
          type="button"
          class="day-toggle"
          :class="{ 'is-off': !dayVisible(d.dayNo) }"
          :style="{ '--chip-color': dayCssVar(d.dayNo) }"
          :aria-pressed="dayVisible(d.dayNo) ? 'true' : 'false'"
          :title="`第 ${d.dayNo} 天：${dayVisible(d.dayNo) ? '点击隐藏' : '点击显示'}`"
          @click="toggleDay(d.dayNo)"
        >
          D{{ String(d.dayNo).padStart(2, '0') }}
        </button>
      </div>
      <label class="routes-toggle">
        <input type="checkbox" :checked="showRoutes" @change="onRoutesToggle" />
        <span>显示路线</span>
      </label>
      <!-- 上图实况（v2.7 §20 R1 起收进工具簇）：与「显示路线」同列，不再单独压地图底部 -->
      <p class="map-note">
        <span>已上图 {{ visibleItems.length }} 项</span>
        <span v-if="hiddenDays.length" class="map-note-dim"> · 已隐藏 {{ hiddenDays.length }} 天</span>
        <span v-if="missing.length" class="map-note-warn">
          · {{ missing.length }} 项无坐标未上图<template v-if="missingNames">（{{ missingNames }}）</template>
        </span>
        <span v-else-if="!visibleItems.length" class="map-note-warn">· 暂无带坐标的点位</span>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
// maplibre-gl v6 的 ESM 构建只有命名导出（无 default）
import { LngLatBounds, Map as MapLibreMap, Marker, type GeoJSONSource } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

import { basemapUrlForScheme } from '../../constants/map'
import { addAttribution, addScaleBar, watchBasemapScheme } from '../../utils/mapBasemap'
import { oklchToHex } from '../../utils/oklch'
import type { DayPlan, TripItem } from '../../types/itinerary'

// 行程地图（SPEC §7.4；v2.6 §19.3 中栏升级；v2.7 §20 R0）：与 Atlas/加点工作台同一 SDK 与
// 同一 **OpenFreeMap 免 key 在线矢量底图**（样式文档 URL，亮/暗随外观切换）。
// - 编号圆钉（day-tint 色 + 天内序号）：DOM 覆盖物**立即渲染**（不依赖样式表/worker）
// - 按天可见性（D01…D0N 开关）+ 「显示路线」开关；路线按天色相（oklch→hex 供 paint 使用）
// - marker 是真实 <button>（键盘可达）：点击 emit select；点地图空白 emit clear（供详情卡关闭）
// - activeItemId 变化 → flyTo 居中（[data-reduce-motion] / 系统偏好下退化 jumpTo）
// - 无坐标项**不进图**，在脚注如实标注数量与名字（不静默丢）

const props = defineProps<{
  days: DayPlan[]
  activeItemId: number | null
}>()
const emit = defineEmits<{
  select: [item: TripItem]
  /** 点地图空白处（关闭贴底详情卡，W2 接线） */
  clear: []
}>()

const mapEl = ref<HTMLDivElement | null>(null)
let map: MapLibreMap | null = null
let ready = false
let stopSchemeWatch: (() => void) | null = null
const markers = new Map<number, Marker>()

/* ---------- 按天可见性 / 路线开关（面板内本地态，不持久化） ---------- */
const hiddenDays = ref<number[]>([])
const showRoutes = ref(true)

function dayVisible(dayNo: number): boolean {
  return !hiddenDays.value.includes(dayNo)
}

function toggleDay(dayNo: number): void {
  hiddenDays.value = hiddenDays.value.includes(dayNo)
    ? hiddenDays.value.filter((n) => n !== dayNo)
    : [...hiddenDays.value, dayNo]
}

function onRoutesToggle(event: Event): void {
  showRoutes.value = (event.target as HTMLInputElement).checked
}

/* ---------- 天色相（oklch 令牌 → CSS 变量 / paint 用 hex） ---------- */
function dayCssVar(dayNo: number): string {
  return `var(--lp-day-${((dayNo - 1) % 8) + 1})`
}

function dayHex(dayNo: number): string {
  const root = getComputedStyle(document.documentElement)
  const hueRaw = root.getPropertyValue(`--lp-day-h-${((dayNo - 1) % 8) + 1}`).trim()
  const hue = Number(hueRaw)
  if (!hueRaw || !Number.isFinite(hue)) return cssVar('--lp-accent', '#0e7490')
  const l = Number(root.getPropertyValue('--lp-day-l').trim()) || 0.6
  const c = Number(root.getPropertyValue('--lp-day-c').trim()) || 0.11
  return oklchToHex(l, c, hue)
}

function hasCoord(item: TripItem): boolean {
  const lat = Number(item.latitude)
  const lng = Number(item.longitude)
  return Number.isFinite(lat) && Number.isFinite(lng) && !(lat === 0 && lng === 0)
}

const allItems = computed(() => props.days.flatMap((day) => day.items ?? []))
const missing = computed(() => allItems.value.filter((item) => !hasCoord(item)))
const missingNames = computed(() => {
  const names = missing.value.slice(0, 3).map((item) => item.poiName)
  return names.join('、') + (missing.value.length > 3 ? '…' : '')
})

/** 点位 → 天内序号（编号圆钉的号码来源；与左栏行内编号徽同口径） */
const pinMeta = computed(() => {
  const meta = new Map<number, { dayNo: number; index: number }>()
  for (const day of props.days) {
    ;(day.items || []).forEach((item, i) => {
      if (item.id != null && hasCoord(item)) meta.set(item.id, { dayNo: day.dayNo, index: i + 1 })
    })
  }
  return meta
})

const visibleItems = computed(() =>
  allItems.value.filter((item) => hasCoord(item) && dayVisible(sourceDayNo(item))),
)

function sourceDayNo(item: TripItem): number {
  if (item.id != null) {
    const meta = pinMeta.value.get(item.id)
    if (meta) return meta.dayNo
  }
  return -1
}

function reduceMotion(): boolean {
  if (document.documentElement.getAttribute('data-reduce-motion') === 'true') return true
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function position(item: TripItem): [number, number] {
  return [Number(item.longitude), Number(item.latitude)]
}

function renderMarkers(): void {
  if (!map) return
  markers.forEach((marker) => marker.remove())
  markers.clear()
  for (const item of visibleItems.value) {
    if (item.id == null) continue
    const meta = pinMeta.value.get(item.id)
    if (!meta) continue
    const el = document.createElement('button')
    el.type = 'button'
    el.className = 'map-pin'
    el.style.setProperty('--pin-color', dayCssVar(meta.dayNo))
    const num = document.createElement('span')
    num.className = 'pin-num'
    num.textContent = String(meta.index)
    el.append(num)
    el.title = item.poiName
    el.setAttribute('aria-label', `第${meta.index}站：${item.poiName}`)
    el.addEventListener('click', () => emit('select', item))
    markers.set(item.id, new Marker({ element: el }).setLngLat(position(item)).addTo(map))
  }
  syncActive(false)
}

function updateRoutes(): void {
  if (!map || !ready) return
  const features = props.days
    .filter((day) => dayVisible(day.dayNo))
    .map((day) => ({
      dayNo: day.dayNo,
      color: dayHex(day.dayNo),
      coords: (day.items ?? []).filter(hasCoord).map(position),
    }))
    .filter((entry) => entry.coords.length >= 2)
    .map((entry) => ({
      type: 'Feature' as const,
      properties: { dayNo: entry.dayNo, color: entry.color },
      geometry: { type: 'LineString' as const, coordinates: entry.coords },
    }))
  const data = { type: 'FeatureCollection' as const, features }
  const source = map.getSource('routes') as GeoJSONSource | undefined
  if (source) {
    source.setData(data)
    applyRoutesVisibility()
    return
  }
  map.addSource('routes', { type: 'geojson', data })
  map.addLayer({
    id: 'routes',
    type: 'line',
    source: 'routes',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      // 逐日路线色（day-tint 色相，oklch→hex 后在特征属性上携带）
      'line-color': ['get', 'color'],
      'line-width': 3,
      'line-opacity': 0.85,
    },
  })
  applyRoutesVisibility()
}

function applyRoutesVisibility(): void {
  if (!map?.getLayer('routes')) return
  map.setLayoutProperty('routes', 'visibility', showRoutes.value ? 'visible' : 'none')
}

function fitBounds(): void {
  if (!map || !visibleItems.value.length) return
  if (visibleItems.value.length === 1) {
    map.jumpTo({ center: position(visibleItems.value[0]), zoom: 12 })
    return
  }
  const bounds = new LngLatBounds()
  visibleItems.value.forEach((item) => bounds.extend(position(item)))
  map.fitBounds(bounds, { padding: 56, maxZoom: 14, duration: reduceMotion() ? 0 : 600 })
}

function syncActive(animate = true): void {
  markers.forEach((marker, id) => {
    marker.getElement().classList.toggle('is-active', id === props.activeItemId)
  })
  if (!map || props.activeItemId == null) return
  const active = visibleItems.value.find((item) => item.id === props.activeItemId)
  if (!active) return
  if (animate && !reduceMotion()) {
    map.flyTo({ center: position(active), zoom: Math.max(map.getZoom(), 13), duration: 500 })
  } else {
    map.jumpTo({ center: position(active) })
  }
}

onMounted(() => {
  if (!mapEl.value) return
  map = new MapLibreMap({
    container: mapEl.value,
    style: basemapUrlForScheme(),
    center: [104, 35],
    zoom: 3,
    attributionControl: false,
  })
  addScaleBar(map)
  addAttribution(map)
  // marker 是 DOM 覆盖物、不依赖样式表：**立即渲染**（底图未就绪时点位照常可见）
  renderMarkers()
  fitBounds()
  // 路线图层依赖样式源：初始 load 与每次换肤 setStyle 后都要重挂（style.load 两处都触发）
  stopSchemeWatch = watchBasemapScheme(map, () => {
    ready = true
    updateRoutes()
  })
  // 点地图空白 → 通知壳关闭详情卡（W2 消费）
  map.on('click', () => emit('clear'))
  // 底图/瓦片失败不抛出：面板保留脚注与交互，不阻塞详情页
  map.on('error', () => undefined)
})

watch(
  () => visibleItems.value.map((item) => `${item.id}:${item.latitude},${item.longitude}`).join('|')
    + `#${hiddenDays.value.join(',')}`,
  () => {
    renderMarkers()
    fitBounds()
    updateRoutes()
  },
)
watch(
  () => props.days.map((day) => `${day.dayId}:${(day.items ?? []).length}`).join('|'),
  () => {
    updateRoutes()
  },
)
watch(() => props.activeItemId, () => syncActive())
watch(showRoutes, () => applyRoutesVisibility())

onBeforeUnmount(() => {
  stopSchemeWatch?.()
  stopSchemeWatch = null
  markers.clear()
  map?.remove()
  map = null
  ready = false
})
</script>

<style scoped>
.trip-map {
  position: relative;
}

.map-canvas {
  height: clamp(420px, calc(100dvh - 260px), 720px);
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-card);
  overflow: hidden;
  background: var(--lp-surface-2);
}

/* ---------- 地图工具（按天可见性 + 路线开关） ---------- */
.map-tools {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: var(--lp-z-sticky);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}

.day-toggles {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-width: 260px;
  padding: 6px;
  border: 1px solid var(--lp-glass-border);
  border-radius: var(--lp-radius-sm);
  background: var(--lp-glass-bg);
  box-shadow: var(--lp-glass-shadow), var(--lp-glass-highlight);
  backdrop-filter: var(--lp-glass-blur);
  -webkit-backdrop-filter: var(--lp-glass-blur);
}

.day-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  padding: 3px 8px;
  border: 1px solid color-mix(in oklch, var(--chip-color) 45%, transparent);
  border-radius: var(--lp-radius-pill);
  background: color-mix(in oklch, var(--chip-color) var(--lp-day-tint-badge), transparent);
  color: color-mix(in oklch, var(--chip-color) 72%, var(--lp-text-1));
  font-family: var(--lp-font-mono);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: opacity 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}

.day-toggle.is-off {
  border-color: var(--lp-edge-2);
  background: var(--lp-surface-2);
  color: var(--lp-text-faint);
  opacity: 0.72;
}

.routes-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: 1px solid var(--lp-glass-border);
  border-radius: var(--lp-radius-sm);
  background: var(--lp-glass-bg);
  box-shadow: var(--lp-glass-shadow), var(--lp-glass-highlight);
  backdrop-filter: var(--lp-glass-blur);
  -webkit-backdrop-filter: var(--lp-glass-blur);
  font-size: 12px;
  font-weight: 600;
  color: var(--lp-text-2);
  cursor: pointer;
}

.routes-toggle input {
  margin: 0;
  accent-color: var(--lp-accent);
}

/* 上图实况小签（工具簇第三行）：玻璃底、单行省略，不上色块 */
.map-note {
  margin: 0;
  max-width: 100%;
  padding: 5px 10px;
  border: 1px solid var(--lp-glass-border);
  border-radius: var(--lp-radius-xs);
  background: var(--lp-glass-bg);
  box-shadow: var(--lp-glass-shadow), var(--lp-glass-highlight);
  backdrop-filter: var(--lp-glass-blur);
  -webkit-backdrop-filter: var(--lp-glass-blur);
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.map-note-dim {
  color: var(--lp-text-muted);
}

.map-note-warn {
  color: var(--lp-warning);
}

/* ---------- 编号圆钉（day-tint 色 + 天内序号） ----------
   marker 由 JS 创建（无 scoped 属性）：用 :deep 落令牌样式 */
:deep(.map-pin) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 2px solid var(--lp-surface-card);
  border-radius: 50%;
  background: var(--pin-color, var(--lp-accent));
  box-shadow: var(--lp-shadow-sm);
  cursor: pointer;
  transition: transform var(--lp-dur-fast) var(--lp-ease-out-quint), box-shadow var(--lp-dur-fast) var(--lp-ease-out-quint);
}

:deep(.map-pin .pin-num) {
  font-family: var(--lp-font-mono);
  font-size: 11px;
  font-weight: 700;
  /* 深色字压在 day-tint 中调上：对比 ≥ AA（白字在同色上不足） */
  color: color-mix(in oklch, var(--pin-color, var(--lp-accent)) 25%, var(--lp-text-1));
}

:deep(.map-pin:hover) {
  transform: scale(1.12);
}

:deep(.map-pin.is-active) {
  transform: scale(1.28);
  box-shadow: 0 0 0 3px var(--lp-surface-card),
    0 0 0 6px color-mix(in oklch, var(--pin-color, var(--lp-accent)) 55%, transparent);
}

/* ---------- 详情工作台模式（v2.7 §20 R1）：地图铺满工作台，控件贴着走廊放 ----------
   走廊 = 两侧浮层面板留下的可见区，宽由壳写 --lp-corridor-left/right（收起即 0）。 */
@media (min-width: 768px) {
  .trip-map {
    position: absolute;
    inset: 0;
  }

  .map-canvas {
    height: 100%;
    border: none;
    border-radius: 0;
  }

  .map-tools {
    left: calc(var(--lp-corridor-left, 0px) + 12px);
    max-width: calc(100% - var(--lp-corridor-left, 0px) - var(--lp-corridor-right, 0px) - 24px);
  }

  /* 署名（license 要求）与比例尺让开面板：缩进走廊内 */
  :deep(.maplibregl-ctrl-bottom-right) {
    right: calc(var(--lp-corridor-right, 0px) + 4px);
    transition: right 0.25s ease;
  }

  :deep(.maplibregl-ctrl-bottom-left) {
    left: calc(var(--lp-corridor-left, 0px) + 4px);
    bottom: 40px;
    transition: left 0.25s ease;
  }
}

/* <768 移动壳：地图回到流内一段（桌面模式下它铺满工作台，高度不设限） */
@media (max-width: 767px) {
  .map-canvas {
    height: clamp(360px, calc(100dvh - 300px), 520px);
  }
}
</style>

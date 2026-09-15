<template>
  <div class="atlas">
    <SectionHead title="旅程图鉴" :sub="headSub">
      <template #actions>
        <div class="scope-pills" aria-label="范围筛选">
          <button
            v-for="item in SCOPES"
            :key="item.value"
            type="button"
            class="scope-pill"
            :class="{ active: scope === item.value }"
            :aria-pressed="scope === item.value"
            @click="setScope(item.value)"
          >
            {{ item.label }}
          </button>
        </div>
      </template>
    </SectionHead>

    <!-- coverage 是契约字段（SPEC §6.7）：海外 0% 坐标也如实呈现，不藏 -->
    <p v-if="atlas" class="coverage-line">
      坐标覆盖：{{ atlas.coverage.itemsWithoutCoord }} 个点位缺坐标 · {{ atlas.coverage.dictMiss }} 城未归国
      <template v-if="atlas.unknownCities.length">
        · 未上图 {{ atlas.unknownCities.length }} 城
      </template>
    </p>

    <div v-if="loading" class="atlas-body">
      <SkeletonCard height="440px" />
      <SkeletonCard height="220px" />
    </div>

    <AppPanel v-else-if="loadError">
      <EmptyState description="图鉴数据加载失败，请确认服务已启动后重试">
        <el-button type="primary" @click="load">重试</el-button>
      </EmptyState>
    </AppPanel>

    <AppPanel v-else-if="atlas && !atlas.stats.tripCount">
      <EmptyState :description="emptyDescription">
        <el-button v-if="scope !== 'all'" @click="setScope('all')">看全部</el-button>
        <el-button v-else type="primary" @click="$router.push('/generate')">生成第一份行程</el-button>
      </EmptyState>
    </AppPanel>

    <div v-else-if="atlas" class="atlas-body">
      <div class="map-panel">
        <div
          ref="mapEl"
          class="atlas-map"
          role="img"
          :aria-label="`旅程地图：${atlas.stats.cityCount} 个城市`"
        ></div>
        <p v-if="!atlas.pins.length" class="map-note">
          当前范围内没有可上图的城市（缺坐标或未归国），侧栏列表照常可用
        </p>
        <p v-else class="map-note">
          圆点大小 ∝ 旅程段数 · 白描边 = 点位质心，警示描边 = 字典兜底 · 点击圆点定位城市
        </p>
        <!-- <768px：侧栏转底部面板（SPEC §7.5） -->
        <el-button v-if="isNarrow" class="sheet-btn" type="primary" @click="sheetVisible = true">
          城市列表（{{ atlas.pins.length }}）
        </el-button>
      </div>

      <aside v-if="!isNarrow" class="sidebar" aria-label="城市列表">
        <AtlasSidebar
          :pins="atlas.pins"
          :unknown-cities="atlas.unknownCities"
          :selected-city="selectedCity"
          @select="focusCity"
          @open="openTrip"
        />
      </aside>

      <Sheet v-model:visible="sheetVisible" :title="`城市列表（${atlas.pins.length}）`">
        <AtlasSidebar
          :pins="atlas.pins"
          :unknown-cities="atlas.unknownCities"
          :selected-city="selectedCity"
          @select="onSheetSelect"
          @open="openTrip"
        />
      </Sheet>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  LngLatBounds,
  Map as MapLibreMap,
  type GeoJSONSource,
  type MapLayerMouseEvent,
} from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

import { getAtlas } from '../api/atlas'
import AtlasSidebar from '../components/atlas/AtlasSidebar.vue'
import AppPanel from '../components/ui/AppPanel.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import SectionHead from '../components/ui/SectionHead.vue'
import Sheet from '../components/ui/Sheet.vue'
import SkeletonCard from '../components/ui/SkeletonCard.vue'
import { basemapUrlForScheme } from '../constants/map'
import {
  addAttribution,
  addScaleBar,
  addVisitedCountriesLayer,
  setVisitedCountries,
  watchBasemapScheme,
} from '../utils/mapBasemap'
import type { AtlasPin, AtlasResponse } from '../types/atlas'

// 旅程图鉴（SPEC §7.5；v2.7 §20 R0）：一行程 = 一个 city 的聚合图鉴（不是逐城足迹）。
// - 底图 OpenFreeMap 免 key 在线矢量瓦片（亮/暗随外观切换）；「去过的国家」高亮是
//   叠在底图上的着色覆盖层，国家轮廓来自仓内 geojson（public/geo，169KB，不占首屏 JS）
// - 圆点大小 ∝ 段数；描边两态区分 coordSource；高亮国家由 highlightCountryCodes 驱动
// - A4 结论（静态）：海外坐标 0% 的根因是语料无种子（sql/seed_*.sql 无京都/东京），
//   修复走 sql/enrich_pois.py --cities 京都；本页如实呈现 coverage，不掩盖
const SCOPES = [
  { value: 'all', label: '全部' },
  { value: 'planned', label: '计划' },
  { value: 'visited', label: '去过' },
] as const
type ScopeValue = (typeof SCOPES)[number]['value']

const router = useRouter()
const scope = ref<ScopeValue>('all')
const loading = ref(true)
const loadError = ref(false)
const atlas = ref<AtlasResponse | null>(null)
const selectedCity = ref<string | null>(null)
const sheetVisible = ref(false)
const isNarrow = ref(false)

const headSub = computed(() => {
  const stats = atlas.value?.stats
  return stats ? `${stats.cityCount} 城 · ${stats.countryCount} 国 · ${stats.tripCount} 段旅程` : ''
})

// scope 过滤后的空态与「从零开始」的空态文案不同：去过/计划是口径，不是没数据
const emptyDescription = computed(() => {
  if (scope.value === 'visited') return '没有「去过」的行程（去过 = 已结束且生成完成）'
  if (scope.value === 'planned') return '没有「计划中」的行程（计划 = 未结束或未生成完成）'
  return '还没有旅程记录，生成一次就可以在这里回看'
})

function setScope(value: ScopeValue): void {
  if (scope.value === value) return
  scope.value = value
  void load()
}

function openTrip(id: number): void {
  void router.push({ name: 'trip-detail', params: { id } })
}

// ---------- 数据 ----------

async function load(): Promise<void> {
  loading.value = true
  loadError.value = false
  try {
    const res = await getAtlas(scope.value)
    atlas.value = res.data
    if (selectedCity.value && !res.data.pins.some((pin) => pin.city === selectedCity.value)) {
      selectedCity.value = null
    }
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

// ---------- 地图（与详情页同一 SDK/底图；换底图只改 constants/map.ts） ----------

const mapEl = ref<HTMLDivElement | null>(null)
let map: MapLibreMap | null = null
let countriesLoaded = false
let stopSchemeWatch: (() => void) | null = null
// 图层（addSource/addLayer）必须等样式解析完成；数据 watcher 与 immediate watcher
// 都可能先于 load 触发，缺这道闸门就是 "Style is not done loading" 报错 + 地图空白。
let styleReady = false

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function reduceMotion(): boolean {
  return (
    document.documentElement.getAttribute('data-reduce-motion') === 'true' ||
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

async function ensureCountries(): Promise<void> {
  if (!map || !styleReady || countriesLoaded) return
  countriesLoaded = true
  // 「去过的国家」高亮覆盖层（utils/mapBasemap.ts）；失败不阻塞点位（置回未加载）
  countriesLoaded = await addVisitedCountriesLayer(map)
}

function renderAtlas(): void {
  if (!map || !atlas.value || !styleReady) return

  // 国家高亮：按当前 scope 的 highlightCountryCodes 收窄覆盖层 filter（底图自带国界）
  setVisitedCountries(map, atlas.value.highlightCountryCodes)

  const data = {
    type: 'FeatureCollection' as const,
    features: atlas.value.pins.map((pin) => ({
      type: 'Feature' as const,
      properties: { city: pin.city, tripCount: pin.tripCount, coordSource: pin.coordSource },
      geometry: { type: 'Point' as const, coordinates: [pin.lng, pin.lat] },
    })),
  }
  const source = map.getSource('cities') as GeoJSONSource | undefined
  if (source) {
    source.setData(data)
  } else {
    // 换肤 setStyle 会清掉这个图层：重挂前先退订旧委托监听，避免重复注册
    map.off('click', 'cities', onCityClick)
    map.off('mouseenter', 'cities', onCityEnter)
    map.off('mouseleave', 'cities', onCityLeave)
    map.addSource('cities', { type: 'geojson', data })
    map.addLayer({
      id: 'cities',
      type: 'circle',
      source: 'cities',
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['get', 'tripCount'], 1, 7, 6, 18] as never,
        'circle-color': cssVar('--lp-accent', '#0e7490'),
        'circle-opacity': 0.9,
        'circle-stroke-width': 2,
        // 两态描边：items=白（点位质心），geo_fallback=警示色（字典兜底）
        'circle-stroke-color': [
          'match',
          ['get', 'coordSource'],
          'items',
          cssVar('--lp-surface-card', '#ffffff'),
          'geo_fallback',
          cssVar('--lp-warning', '#b45309'),
          cssVar('--lp-surface-card', '#ffffff'),
        ] as never,
      },
    })
    map.addLayer({
      id: 'cities-selected',
      type: 'circle',
      source: 'cities',
      filter: ['==', ['get', 'city'], ''] as never,
      paint: {
        'circle-radius': ['+', ['interpolate', ['linear'], ['get', 'tripCount'], 1, 9, 6, 20], 4] as never,
        'circle-opacity': 0,
        'circle-stroke-width': 3,
        'circle-stroke-color': cssVar('--lp-danger', '#be123c'),
        'circle-stroke-opacity': 0.9,
      },
    })
    map.on('click', 'cities', onCityClick)
    map.on('mouseenter', 'cities', onCityEnter)
    map.on('mouseleave', 'cities', onCityLeave)
  }

  syncSelection()
  fitPins()
}

// 具名 handler：换肤重挂图层时要 off 掉同一引用（匿名闭包退不掉）
function onCityClick(event: MapLayerMouseEvent): void {
  const city = event.features?.[0]?.properties?.city
  if (city) focusCity(String(city))
}

function onCityEnter(): void {
  if (map) map.getCanvas().style.cursor = 'pointer'
}

function onCityLeave(): void {
  if (map) map.getCanvas().style.cursor = ''
}

function syncSelection(): void {
  if (!map || !map.getLayer('cities-selected')) return
  map.setFilter('cities-selected', ['==', ['get', 'city'], selectedCity.value ?? ''] as never)
}

function fitPins(): void {
  const pins = atlas.value?.pins ?? []
  if (!map || !pins.length) return
  if (pins.length === 1) {
    const only = pins[0]
    const center: [number, number] = [only.lng, only.lat]
    if (reduceMotion()) map.jumpTo({ center, zoom: 9 })
    else map.flyTo({ center, zoom: 9, duration: 600 })
    return
  }
  const bounds = new LngLatBounds()
  pins.forEach((pin: AtlasPin) => bounds.extend([pin.lng, pin.lat]))
  map.fitBounds(bounds, { padding: 64, maxZoom: 10, duration: reduceMotion() ? 0 : 700 })
}

/** 城市定位：侧栏点城市 / 地图点圆点共用（双向联动的「点城市 → flyTo」一侧） */
function focusCity(city: string): void {
  selectedCity.value = city
  syncSelection()
  const pin = atlas.value?.pins.find((item) => item.city === city)
  if (pin && map) {
    const center: [number, number] = [pin.lng, pin.lat]
    if (reduceMotion()) map.jumpTo({ center, zoom: Math.max(map.getZoom(), 8) })
    else map.flyTo({ center, zoom: Math.max(map.getZoom(), 8), duration: 600 })
  }
  // 点圆点 → 滚到对应卡片（双向联动的另一侧）
  document
    .getElementById(`city-card-${city}`)
    ?.scrollIntoView({ behavior: reduceMotion() ? 'auto' : 'smooth', block: 'center' })
}

function onSheetSelect(city: string): void {
  sheetVisible.value = false
  focusCity(city)
}

async function initMap(): Promise<void> {
  if (map || !mapEl.value) return
  styleReady = false
  map = new MapLibreMap({
    container: mapEl.value,
    style: basemapUrlForScheme(),
    center: [104, 35],
    zoom: 2.6,
    attributionControl: false,
  })
  map.on('error', () => undefined)
  addScaleBar(map)
  addAttribution(map)
  // 初始 load 与换肤 setStyle 后同一入口：重挂覆盖层与城市点
  stopSchemeWatch = watchBasemapScheme(map, () => {
    styleReady = true
    countriesLoaded = false
    void ensureCountries().then(() => renderAtlas())
  })
}

function destroyMap(): void {
  stopSchemeWatch?.()
  stopSchemeWatch = null
  map?.remove()
  map = null
  countriesLoaded = false
  styleReady = false
}

watch(
  () => Boolean(atlas.value?.stats.tripCount),
  async (hasTrips) => {
    if (hasTrips) {
      await nextTick()
      await initMap()
      renderAtlas()
    } else {
      destroyMap()
    }
  },
  { immediate: true },
)

watch(atlas, () => {
  if (map) void ensureCountries().then(() => renderAtlas())
})

onMounted(async () => {
  isNarrow.value = window.matchMedia('(max-width: 767px)').matches
  const media = window.matchMedia('(max-width: 767px)')
  media.addEventListener('change', (event) => {
    isNarrow.value = event.matches
  })
  await load()
})

onBeforeUnmount(destroyMap)
</script>

<style scoped>
.atlas {
  display: flex;
  flex-direction: column;
  gap: var(--lp-space-3);
}

.scope-pills {
  display: flex;
  gap: var(--lp-space-2);
}

.scope-pill {
  padding: 5px 14px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-pill);
  background: var(--lp-surface-card);
  color: var(--lp-text-2);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}

.scope-pill:hover {
  border-color: var(--lp-accent);
  color: var(--lp-accent);
}

.scope-pill.active {
  background: var(--lp-accent);
  border-color: var(--lp-accent);
  color: var(--lp-accent-on-fill);
}

.coverage-line {
  margin: 0;
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
}

.atlas-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: var(--lp-space-3);
  align-items: start;
}

.map-panel {
  position: relative;
}

.atlas-map {
  height: min(70vh, 640px);
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-card);
  overflow: hidden;
  background: var(--lp-surface-2);
}

.map-note {
  margin: var(--lp-space-2) 0 0;
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
}

.sheet-btn {
  position: absolute;
  right: var(--lp-space-3);
  bottom: var(--lp-space-3);
  z-index: var(--lp-z-sticky);
}

.sidebar {
  max-height: min(70vh, 640px);
  overflow: auto;
}

@media (max-width: 767px) {
  .atlas-body {
    display: block;
  }

  .atlas-map {
    height: 56vh;
  }
}
</style>

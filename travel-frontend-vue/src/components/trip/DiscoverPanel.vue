<template>
  <section class="discover-panel" aria-label="发现">
    <div class="discover-head">
      <h2 class="panel-title">发现</h2>

      <AppInput
        v-model="query"
        class="panel-search"
        placeholder="搜索地点，回车检索"
        aria-label="搜索地点"
        @enter="runSearch"
      >
        <template #prefix><Search :size="15" /></template>
      </AppInput>

      <Segmented v-model="scope" class="scope" :items="scopeItems" aria-label="点位范围" />

      <div class="cat-row" role="group" aria-label="分类筛选">
        <button
          v-for="chip in CATEGORY_CHIPS"
          :key="chip.value"
          type="button"
          class="cat-chip"
          :class="{ 'is-active': category === chip.value }"
          :aria-pressed="category === chip.value ? 'true' : 'false'"
          @click="category = chip.value"
        >
          {{ chip.label }}
        </button>
      </div>

      <p v-if="presetDayNo" class="preset-hint">
        排入目标：第 {{ presetDayNo }} 天（点卡片上的 ＋ 直接加入）
        <button type="button" class="caption-btn" @click="emit('clearPreset')">取消</button>
      </p>
    </div>

    <!-- 头部钉在面板顶，只有列表滚（面板高度固定，超出必须走内滚而不是被裁掉） -->
    <div class="discover-scroll">
      <p class="list-caption">
        <template v-if="searching">检索中…</template>
        <template v-else-if="searchMode">
          「{{ activeQuery }}」结果 {{ entries.length }} 条
          <button type="button" class="caption-btn" @click="clearSearch">清除</button>
        </template>
        <template v-else>未排 {{ unplannedCount }} · 已排 {{ plannedCount }}</template>
      </p>

      <ul v-if="entries.length" class="poi-list">
        <li
          v-for="entry in entries"
          :key="entry.key"
          class="poi-card"
          :class="{ 'is-planned': entry.kind === 'planned' }"
          draggable="true"
          :role="entry.kind === 'planned' ? 'button' : undefined"
          :tabindex="entry.kind === 'planned' ? 0 : undefined"
          :aria-label="entry.kind === 'planned' ? `查看「${entry.name}」详情` : undefined"
          @dragstart="onDragStart(entry, $event)"
          @click="entry.kind === 'planned' && entry.item && emit('select', entry.item)"
          @keydown.enter.prevent="entry.kind === 'planned' && entry.item && emit('select', entry.item)"
        >
          <div class="poi-thumb">
            <img
              v-if="!thumbFailed[entry.key]"
              :src="thumbUrl(entry)"
              :alt="entry.name"
              loading="lazy"
              @error="thumbFailed[entry.key] = true"
            />
            <span v-else class="thumb-fallback">{{ categoryLabel(entry.category) }}</span>
          </div>
          <div class="poi-body">
            <p class="poi-name" :title="entry.name">
              {{ entry.name }}
              <span v-if="isUnverifiedSuggestion(entry)" class="poi-unverified">{{ SUGGESTION_UNVERIFIED_LABEL }}</span>
            </p>
            <p v-if="entry.note" class="poi-note" :title="entry.note">{{ entry.note }}</p>
          </div>
          <button
            v-if="entry.kind === 'planned'"
            type="button"
            class="poi-day"
            :title="`第 ${entry.dayNo} 天，点击定位`"
            @click.stop="entry.item && emit('select', entry.item)"
          >
            D{{ String(entry.dayNo).padStart(2, '0') }}
          </button>
          <button
            v-else
            type="button"
            class="poi-add"
            :aria-label="`排入「${entry.name}」`"
            title="排入某天"
            @click.stop="openAdd(entry)"
          >
            <Plus :size="15" />
          </button>
        </li>
      </ul>
      <p v-else class="panel-empty">{{ emptyText }}</p>
    </div>

    <!-- 排入某天（自研弹窗；写作入口仍是 useItineraryActions.addItem 单点） -->
    <AppDialog v-model="addVisible" title="排入某天" width="min(360px, calc(100vw - 32px))">
      <p v-if="addTarget" class="add-tip">将「{{ addTarget.name }}」加入哪一天？</p>
      <p v-if="addTarget?.suggestion?.needReservation" class="add-rsvp">
        该地点通常需要提前预约，建议加入后尽早通过官方渠道预约。
      </p>
      <div class="day-grid">
        <button
          v-for="d in dayOptions"
          :key="d.dayId"
          type="button"
          class="day-pick"
          :disabled="adding"
          @click="confirmAdd(d.dayId)"
        >
          第 {{ d.dayNo }} 天<template v-if="d.travelDate"> · {{ d.travelDate }}</template>
        </button>
      </div>
      <p v-if="!dayOptions.length" class="add-tip">行程暂无可用天</p>
    </AppDialog>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { Plus, Search } from 'lucide-vue-next'

import { searchLocalPois, type LocalPoi } from '../../api/pois'
import { SUGGESTION_UNVERIFIED_LABEL } from '../../constants/data-provenance'
import { useItineraryStore } from '../../store/itinerary'
import { useDiscoverAdd } from '../../composables/useDiscoverAdd'
import { typeLabel } from './day-card/shared'
import type { TripItem } from '../../types/itinerary'
import type { Suggestion } from '../../types/generated/contracts'
import AppDialog from '../ui/AppDialog.vue'
import AppInput from '../ui/AppInput.vue'
import Segmented from '../ui/Segmented.vue'
import { toast } from '../ui/toast'

// 「发现」面板（v2.6 §19.3，右栏常驻）：搜索加点（本地点位库）+ 全部/未排/已排过滤 + 分类
// + 卡片（未排/搜索结果「＋排入」，已排卡整卡可点→中央详情卡，任意卡片可**拖拽到左栏某天**排入/移动）。
// 写入口统一在 useDiscoverAdd（与拖拽入天共用同一条 payload 口径）。
// （就近推荐已移除：poi-nearby 的 OTM 近邻与行程相关度太低，产品口径下不展示。）
const props = defineProps<{
  /** 日尾「添加地点」预设的目标天：＋ 点击即直排该天（不再弹选天框） */
  presetDayId?: number | null
}>()

const emit = defineEmits<{
  /** 已排卡片点击：交壳滚动并高亮左栏对应行 */
  select: [item: TripItem]
  /** 取消预设目标天 */
  clearPreset: []
}>()

const DRAG_MIME = 'application/x-discover-entry'

type Category = 'attraction' | 'food' | 'hotel' | 'shopping' | 'other'

interface PanelEntry {
  key: string
  kind: 'planned' | 'suggestion' | 'search'
  name: string
  note: string
  category: Category
  dayNo?: number
  item?: TripItem
  suggestion?: Suggestion
  poi?: LocalPoi
}

const CATEGORY_CHIPS: { value: Category | 'all'; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'attraction', label: '景点' },
  { value: 'food', label: '美食' },
  { value: 'hotel', label: '酒店' },
  { value: 'shopping', label: '购物' },
  { value: 'other', label: '其他' },
]

// 分类中文标签走全站唯一口径（R5-3）：typeLabel 覆盖 attraction/food/hotel/shopping/other
function categoryLabel(category: Category): string {
  return typeLabel(category)
}

function normalizeCategory(raw: string): Category {
  if (raw === 'attraction' || raw === 'activity') return 'attraction'
  if (raw === 'food') return 'food'
  if (raw === 'hotel') return 'hotel'
  if (raw === 'shopping' || raw === 'souvenir') return 'shopping'
  return 'other'
}

const store = useItineraryStore()
const { detail } = storeToRefs(store)
const { addSuggestionToDay, addPoiToDay } = useDiscoverAdd()

/* ---------- 三个来源 → 统一卡片模型 ---------- */
const usedPoiNames = computed(() => {
  const names = new Set<string>()
  for (const d of detail.value?.dayList || []) {
    for (const item of d.items) names.add((item.poiName || '').replace(/\s+/g, ''))
  }
  return names
})

const plannedEntries = computed<PanelEntry[]>(() =>
  (detail.value?.dayList || []).flatMap((day) =>
    (day.items || []).map((item) => ({
      key: `i${item.id}`,
      kind: 'planned' as const,
      name: item.poiName,
      note: item.address || item.intro || '',
      category: normalizeCategory(item.itemType),
      dayNo: day.dayNo,
      item,
    })),
  ),
)

/** 未排 = 行程级 suggestions（used=false）且排除已在行程中的同名点位（与旧 DiscoverPool 同口径） */
const unplannedEntries = computed<PanelEntry[]>(() =>
  (detail.value?.suggestions ?? [])
    .filter((s) => !s.used && !usedPoiNames.value.has((s.name || '').replace(/\s+/g, '')))
    .map((s) => ({
      key: `s${s.name}`,
      kind: 'suggestion' as const,
      name: s.name,
      note: s.intro || s.address || '',
      category: normalizeCategory(s.category),
      suggestion: s,
    })),
)

/** 没有坐标 = 后台批量后验证没能证实这个名字存在（见 constants/data-provenance）。 */
function isUnverifiedSuggestion(entry: PanelEntry): boolean {
  if (entry.kind !== 'suggestion' || !entry.suggestion) return false
  return entry.suggestion.latitude == null || entry.suggestion.longitude == null
}

const plannedCount = computed(() => plannedEntries.value.length)
const unplannedCount = computed(() => unplannedEntries.value.length)

const scope = ref<'all' | 'unplanned' | 'planned'>('all')
const scopeItems = computed(() => [
  { value: 'all', label: '全部', badge: plannedCount.value + unplannedCount.value },
  { value: 'unplanned', label: '未排', badge: unplannedCount.value },
  { value: 'planned', label: '已排', badge: plannedCount.value },
])

const category = ref<Category | 'all'>('all')

/* ---------- 检索（本地点位库；回车触发） ---------- */
const query = ref('')
const activeQuery = ref('')
const searchMode = ref(false)
const searching = ref(false)
const searchEntries = ref<PanelEntry[]>([])
const coveredCities = ref<string[]>([])

function toSearchEntry(poi: LocalPoi): PanelEntry {
  return {
    key: `p${poi.id}`,
    kind: 'search',
    name: poi.name,
    note: poi.address || poi.tags || '',
    category: normalizeCategory(poi.category),
    poi,
  }
}

async function runSearch(): Promise<void> {
  const keyword = query.value.trim()
  if (!keyword) {
    clearSearch()
    return
  }
  searching.value = true
  searchMode.value = true
  activeQuery.value = keyword
  try {
    const res = await searchLocalPois(detail.value?.city ?? '', keyword)
    searchEntries.value = (res.data.items || []).map(toSearchEntry)
    coveredCities.value = (res.data.coveredCities || []).map((city) => city.city)
  } catch {
    searchEntries.value = []
    coveredCities.value = []
    toast.error('检索失败，请稍后重试')
  } finally {
    searching.value = false
  }
}

function clearSearch(): void {
  query.value = ''
  activeQuery.value = ''
  searchMode.value = false
  searchEntries.value = []
  coveredCities.value = []
}

/* ---------- 列表合成（搜索模式覆盖范围；分类筛选两模式都生效） ---------- */
const entries = computed<PanelEntry[]>(() => {
  let list: PanelEntry[]
  if (searchMode.value) list = searchEntries.value
  else if (scope.value === 'planned') list = plannedEntries.value
  else if (scope.value === 'unplanned') list = unplannedEntries.value
  else list = [...plannedEntries.value, ...unplannedEntries.value]
  if (category.value !== 'all') list = list.filter((entry) => entry.category === category.value)
  return list
})

const emptyText = computed(() => {
  if (searchMode.value) {
    return coveredCities.value.length
      ? `没有匹配的地点 · 本地库已覆盖：${coveredCities.value.join('、')}`
      : '没有匹配的地点'
  }
  return '该分类下暂无点位'
})

/* ---------- 缩略图（同源 POI 实景图代理；失败落分类占位块） ---------- */
const thumbFailed = ref<Record<string, boolean>>({})

function thumbUrl(entry: PanelEntry): string {
  const city = detail.value?.city ?? ''
  return `/api/poi-photo?name=${encodeURIComponent(entry.name)}&city=${encodeURIComponent(city)}`
}

/* ---------- 拖拽入天（HTML5 DnD）：载荷经 dataTransfer 交给左栏日卡，壳负责落库 ---------- */
type DragSource = PanelEntry | { kind: 'suggestion'; suggestion: Suggestion }

function onDragStart(source: DragSource, event: DragEvent): void {
  if (!event.dataTransfer) return
  let payload: Record<string, unknown> | null = null
  if (source.kind === 'planned') {
    const entry = source as PanelEntry
    if (entry.item?.id == null) return
    payload = { kind: 'planned', itemId: entry.item.id, name: entry.name }
  } else if (source.kind === 'search') {
    const poi = (source as PanelEntry).poi
    if (!poi) return
    payload = { kind: 'search', poi }
  } else {
    const suggestion = (source as PanelEntry).suggestion
    if (!suggestion) return
    payload = { kind: 'suggestion', suggestion }
  }
  event.dataTransfer.setData(DRAG_MIME, JSON.stringify(payload))
  event.dataTransfer.effectAllowed = 'copyMove'
}

/* ---------- 排入某天 ---------- */
const addVisible = ref(false)
const addTarget = ref<PanelEntry | null>(null)
const adding = ref(false)
const dayOptions = computed(() => detail.value?.dayList ?? [])

const presetDayNo = computed(
  () => dayOptions.value.find((d) => d.dayId === props.presetDayId)?.dayNo ?? null,
)

function openAdd(entry: PanelEntry): void {
  // 预设目标天（日尾「添加地点」入口）→ 直接排入，不再弹选天框
  if (props.presetDayId != null) {
    void directAdd(entry, props.presetDayId)
    return
  }
  addTarget.value = entry
  addVisible.value = true
}

async function directAdd(entry: PanelEntry, dayId: number): Promise<void> {
  if (adding.value) return
  adding.value = true
  try {
    if (entry.kind === 'suggestion' && entry.suggestion) await addSuggestionToDay(entry.suggestion, dayId)
    else if (entry.kind === 'search' && entry.poi) await addPoiToDay(entry.poi, dayId)
  } finally {
    adding.value = false
  }
}

async function confirmAdd(dayId: number): Promise<void> {
  const entry = addTarget.value
  if (!entry || adding.value) return
  await directAdd(entry, dayId)
  addVisible.value = false
}
</script>

<style scoped>
/* 面板本体撑满 .panel-fill 并受其高度约束：头部钉死，列表内滚（否则内容超高会被面板裁掉） */
.discover-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  min-height: 0;
}

.discover-head {
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.discover-scroll {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.panel-title {
  margin: 0;
  font-family: var(--lp-font-display);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--lp-text-1);
}

.panel-search {
  width: 100%;
}

.scope {
  align-self: flex-start;
}

.cat-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.cat-chip {
  padding: 3px 10px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-pill);
  background: var(--lp-surface-card);
  color: var(--lp-text-muted);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}

.cat-chip:hover {
  color: var(--lp-accent);
  border-color: var(--lp-accent);
}

.cat-chip.is-active {
  background: var(--lp-accent);
  border-color: var(--lp-accent);
  color: var(--lp-accent-on-fill);
}

.preset-hint {
  margin: 0;
  padding: 6px 10px;
  border-radius: var(--lp-radius-xs);
  background: var(--lp-accent-subtle);
  color: var(--lp-accent-hover);
  font-size: 11.5px;
  font-weight: 600;
}

.list-caption {
  margin: 0;
  font-size: 11.5px;
  color: var(--lp-text-muted);
}

.caption-btn {
  margin-left: 6px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--lp-accent);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
}

/* ---------- 卡片列表 ---------- */
.poi-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.poi-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-sm);
  background: var(--lp-surface-card);
  cursor: grab;
  transition: border-color 0.15s ease;
}

/* 已排卡整卡可点（出中央详情卡），不再是只有 D01 小徽章可点 */
.poi-card.is-planned {
  cursor: pointer;
}

.poi-card.is-planned:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: -2px;
}

.poi-card:hover {
  border-color: var(--lp-accent);
}

/* v2.7 §20 R3：发现卡压缩为 40px 缩略 + 12.5 名称 + 10px 单行描述（与左栏行同规格） */
.poi-thumb {
  flex: none;
  width: 40px;
  height: 40px;
  border-radius: var(--lp-radius-xs);
  overflow: hidden;
  background: var(--lp-surface-2);
}

.poi-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.thumb-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--lp-accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.poi-body {
  flex: 1;
  min-width: 0;
}

.poi-name {
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--lp-font-display);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.015em;
  color: var(--lp-text-1);
}

.poi-unverified {
  font-size: 11px;
  color: var(--lp-text-faint);
}

.poi-note {
  margin: 2px 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  line-height: 1.35;
  color: var(--lp-text-muted);
}

.poi-day {
  flex: none;
  padding: 3px 9px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-pill);
  background: var(--lp-surface-2);
  color: var(--lp-text-2);
  font-family: var(--lp-font-display);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.poi-day:hover {
  color: var(--lp-accent);
  border-color: var(--lp-accent);
}

.poi-add {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--lp-edge-1);
  border-radius: 50%;
  background: var(--lp-surface-elevated);
  color: var(--lp-text-2);
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}

.poi-add.is-small {
  width: 22px;
  height: 22px;
}

.poi-add:hover {
  border-color: var(--lp-accent);
  color: var(--lp-accent);
}

.panel-empty {
  margin: 6px 0;
  padding: 18px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--lp-text-muted);
}

/* ---------- 排入弹窗 ---------- */
.add-tip {
  margin: 0 0 12px;
  font-size: 13.5px;
  color: var(--lp-text-1);
}

.add-rsvp {
  margin: -4px 0 12px;
  padding: 8px 12px;
  border-radius: var(--lp-radius-xs);
  border-left: 3px solid var(--lp-warning);
  background: var(--lp-warning-soft);
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--lp-text-2);
}

.day-grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lp-space-2);
}

.day-pick {
  padding: 6px 12px;
  border: 1px solid var(--lp-edge-2);
  border-radius: var(--lp-radius-xs);
  background: var(--lp-surface-card);
  color: var(--lp-text-2);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.day-pick:hover:not(:disabled) {
  color: var(--lp-accent);
  border-color: var(--lp-accent);
}

.day-pick:disabled {
  color: var(--lp-text-faint);
  cursor: default;
}
</style>

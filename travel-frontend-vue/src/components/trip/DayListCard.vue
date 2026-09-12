<template>
  <details class="day-panel" :class="{ 'is-glowing': isActiveDay }" :open="expanded">
    <summary @click="onSummaryClick">
      <span class="day-idx">{{ String(day.dayNo).padStart(2, '0') }}</span>
      <span class="day-main">
        <!-- 流式研究阶段：日卡骨架态（shimmer 由 .lp-skel-line 公共件按系统动效偏好启停） -->
        <template v-if="isSkeleton">
          <span class="lp-skel-line sk-meta"></span>
          <span class="lp-skel-line sk-title"></span>
          <span class="lp-skel-line sk-count"></span>
        </template>
        <template v-else>
          <span class="day-meta">第{{ day.dayNo }}天<template v-if="day.travelDate"> · {{ day.travelDate }}</template></span>
          <span class="day-title">{{ dayTitle(day) }}</span>
          <span class="day-count">
            {{ (day.items || []).length }} 个点位
            <span v-if="isActiveDay" class="day-state state-active">生成中</span>
            <span v-else-if="isPendingDay" class="day-state">待生成</span>
          </span>
        </template>
        <!-- 降级/失败如实可见（原则 4）：degraded 按 scope 对应日卡，PARTIAL 保留 degradedDays -->
        <span v-if="notGenerated" class="day-flag flag-fail">未成功生成</span>
        <span v-else-if="dayDegraded" class="day-flag">已降级 · {{ dayDegraded.reason }}</span>
      </span>
      <span class="day-plus" aria-hidden="true">＋</span>
    </summary>
    <div class="day-content">
      <!-- 每日叙事区（§5.3.2）：theme/note/practicalNotes/photoSpots/backupPlan，空态各自静默 -->
      <DayNarrativePanel :day="day" />
      <div class="route-toolbar">
        <el-button type="primary" size="small" :disabled="!mapReady" @click="openAddDialog">添加景点</el-button>
      </div>
      <draggable
        :list="day.items"
        item-key="id"
        handle=".drag-handle"
        :animation="150"
        @end="emit('item-drop', day)"
      >
        <template #item="{ element, index }">
          <div
            :id="`item-${element.id}`"
            class="route-row"
            :class="{ highlighted: element.id === highlightId }"
            role="button"
            tabindex="0"
            :aria-label="`行程点位：${element.poiName}`"
            @click="onItemClick(element)"
            @keydown.enter.prevent="onItemClick(element)"
          >
            <div class="row-img">
              <img
                v-if="imgLevel(element) < 2 && imgSrc(element) && (element.itemType === 'attraction' || element.itemType === 'food' || element.image || element.imageUrl || (element.longitude && element.latitude))"
                :src="imgSrc(element)"
                :alt="element.poiName"
                loading="lazy"
                @error="onImgError(element)"
              />
              <div v-else class="row-img-fallback">{{ typeLabel(element.itemType) }}</div>
            </div>
            <span class="row-no">
              <DragSortHandle
                :day="day"
                :item="element"
                :index="index"
                :total="(day.items || []).length"
                @moved="emit('item-drop', $event)"
              />
              <i class="row-idx">{{ String(index + 1).padStart(2, '0') }}</i>
            </span>
            <div class="row-main">
              <div class="row-top">
                <span class="row-name">{{ element.poiName }}</span>
                <el-tag :type="tagType(element.itemType)" size="small">
                  {{ typeLabel(element.itemType) }}
                </el-tag>
                <span v-if="element.startTime" class="row-time">
                  {{ element.startTime }}<template v-if="element.endTime"> - {{ element.endTime }}</template>
                </span>
                <span v-if="element.durationMin" class="row-dwell">约 {{ element.durationMin }} 分钟</span>
              </div>
              <div
                v-if="element.openTime || element.cost != null || element.tag || element.verificationStatus"
                class="row-meta"
              >
                <span v-if="element.openTime">开放 {{ element.openTime }}</span>
                <span v-if="element.cost != null">
                  ￥{{ element.cost }}{{ element.itemType === 'hotel' ? '/晚/间' : '/人' }}
                </span>
                <span v-if="element.tag">{{ element.tag }}</span>
                <el-tag v-if="element.verificationStatus && element.verificationStatus !== 'verified'" size="small" type="warning">
                  {{ element.valueKind === 'estimated' ? '参考估算' : '待确认' }}
                </el-tag>
                <el-tag v-else-if="element.verificationStatus === 'verified'" size="small" type="success">
                  已核实
                </el-tag>
              </div>
              <p v-if="element.source || element.sourceUpdatedAt" class="poi-source">
                来源：{{ sourceLabel(element.source) }}<span v-if="element.sourceUpdatedAt"> · 更新于 {{ formatSourceDate(element.sourceUpdatedAt) }}</span>
              </p>
              <p
                v-if="(element.intro || element.description)"
                class="poi-desc"
                :class="{ expanded: descExpanded[element.id!] }"
              >
                {{ element.intro || element.description }}
              </p>
              <el-button
                v-if="(element.intro || element.description) && descLong(element)"
                class="poi-desc-toggle"
                link
                type="primary"
                size="small"
                @click.stop="toggleDesc(element)"
              >
                {{ descExpanded[element.id!] ? '收起' : '展开全部' }}
              </el-button>
              <!-- why_this 次级行（§5.3.3）：item.whyThis 有值才渲染，attraction 与否一视同仁 -->
              <WhyThisLine :why-this="element.whyThis" @click.stop @keydown.stop />
              <p v-if="element.remark" class="poi-remark">{{ element.remark }}</p>
              <!-- 附近推荐（轻量 GraphRAG）：打开时拉取，结果缓存于子组件实例 -->
              <NearbyRecommends :item="element" :open="!!nearbyOpen[element.id!]" />
            </div>
            <div class="row-side">
              <a class="row-map" :href="amapLink(element)" target="_blank" rel="noopener">{{ mapLinkLabel }} ↗</a>
              <el-button
                v-if="element.itemType === 'attraction' || element.itemType === 'food'"
                link
                type="primary"
                size="small"
                @click.stop="toggleNearby(element)"
              >
                附近
              </el-button>
              <el-button link type="primary" size="small" @click.stop="openEditDialog(element)">
                编辑
              </el-button>
              <el-button link type="danger" size="small" @click.stop="onDeleteItem(element)">
                删除
              </el-button>
            </div>
          </div>
        </template>
      </draggable>
      <el-empty v-if="!(day.items || []).length" description="当天暂无安排" :image-size="80" />
      <!-- 方案分叉区（§5.3.4）：day_options 0-2 组并列卡，只展示不切换 -->
      <DayOptionsFork :options="day.dayOptions || []" />
    </div>

    <PoiSearchDialog v-model:visible="addDialogVisible" :day-id="day.dayId" />
    <ItemEditDialog v-model:visible="editDialogVisible" :item="editTarget" />
  </details>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import draggable from 'vuedraggable'
import { storeToRefs } from 'pinia'

import { useItineraryStore, type StreamState } from '../../store/itinerary'
import { useItineraryActions } from '../../composables/useItineraryActions'
import { useItemPhoto } from '../../composables/useItemPhoto'
import type { DayPlan, TripItem } from '../../types/itinerary'
import { isForeignCity } from '../../utils/geo'
import DayNarrativePanel from './DayNarrativePanel.vue'
import WhyThisLine from './WhyThisLine.vue'
import DayOptionsFork from './DayOptionsFork.vue'
import DragSortHandle from './DragSortHandle.vue'
import NearbyRecommends from './NearbyRecommends.vue'
import PoiSearchDialog from './PoiSearchDialog.vue'
import ItemEditDialog from './ItemEditDialog.vue'

// 单日折叠卡（M4-②a §5.4 / M4-②b §5.3 叙事化升级）：
// - 叙事渲染（theme/note/practical_notes/photo_spots/backup_plan）在 DayNarrativePanel；
// - why_this 次级行在 WhyThisLine；day_options 分叉区在 DayOptionsFork；
// - 附近推荐 / 搜索添加 / 行内编辑对话框均为自包含子组件（props 可见性 + 自读写 store）；
// - 图片三级降级收敛为 useItemPhoto（§5.3.6）。
// 组件只读 store，写变更一律经 useItineraryActions；拖拽/键盘排序为乐观本地变更，
// 壳接收 item-drop 后走 actions.reorderItems 持久化（快照兜底，失败回滚顺序）。
const props = defineProps<{
  day: DayPlan
  /** SSE 生成状态机（§5.3.5）：驱动骨架态 / 当日微光 / 待生成与降级角标 */
  streamState: StreamState
  /** 手风琴展开态（受控于壳的 openDayNo，单天展开） */
  expanded: boolean
  /** 地图联动高亮的行程项 id */
  highlightId: number | null
}>()

const emit = defineEmits<{
  'item-drop': [day: DayPlan]
  'item-select': [item: TripItem]
  toggle: [dayNo: number]
}>()

const store = useItineraryStore()
const actions = useItineraryActions()
const { detail } = storeToRefs(store)

const amapReady = ref(!!import.meta.env.VITE_AMAP_JS_KEY)
const detailForeign = computed(() => isForeignCity(detail.value?.city ?? ''))
const mapReady = computed(() => amapReady.value || detailForeign.value)
const mapLinkLabel = computed(() => (detailForeign.value ? '谷歌地图' : '高德地图'))

const { imgLevel, imgSrc, onImgError } = useItemPhoto()

// ---------- 流式生成状态（§5.3.5）：store.streamState 驱动 ----------
const phase = computed(() => props.streamState.phase)
/** research_start 后全部日卡骨架态 */
const isSkeleton = computed(() => phase.value === 'researching')
/** day_start → 当日卡微光态 */
const isActiveDay = computed(() => phase.value === 'day' && props.streamState.dayNo === props.day.dayNo)
/** 尚未排到的天数挂「待生成」静态文案（reduce 模式下的状态兜底） */
const isPendingDay = computed(
  () => phase.value === 'day' && props.streamState.dayNo != null && props.day.dayNo > props.streamState.dayNo!,
)
/** complete(PARTIAL)：未成功生成的天如实保留角标 */
const notGenerated = computed(() => phase.value === 'complete' && props.streamState.degradedDays.includes(props.day.dayNo))
/** degraded 事件按 scope（如 day:2）对应到日卡，挂「已降级 · 原因」角标 */
const dayDegraded = computed(() => {
  if (phase.value !== 'day' && phase.value !== 'butler' && phase.value !== 'complete') return undefined
  return props.streamState.degraded.find((d) =>
    new RegExp(`day[:_\\- ]?${props.day.dayNo}(\\D|$)`).test(d.scope),
  )
})

function onSummaryClick(event: MouseEvent) {
  // 手风琴：拦截 summary 原生 toggle，展开态由壳的 openDayNo 单一受控，避免多天同时展开
  event.preventDefault()
  emit('toggle', props.day.dayNo)
}

function onItemClick(item: TripItem) {
  emit('item-select', item)
}

// ---------- 景点介绍长文本展开/收起 ----------
const descExpanded = ref<Record<number, boolean>>({})

function toggleDesc(item: TripItem) {
  const id = item.id!
  descExpanded.value[id] = !descExpanded.value[id]
}

function descLong(item: TripItem) {
  return (item.intro || item.description || '').length > 60
}

function dayTitle(d: DayPlan) {
  if (d.theme) return d.theme
  const items = d.items || []
  if (!items.length) return '暂无安排'
  const first = items[0]?.poiName || ''
  const last = items.length > 1 ? items[items.length - 1]?.poiName || '' : ''
  return last && last !== first ? `${first} → ${last}` : first
}

function amapLink(item: TripItem) {
  // 海外与后端一致走 Google Maps：有真实坐标优先按坐标打开，否则按名称检索
  if (detailForeign.value) {
    if (item.latitude != null && item.longitude != null) {
      return `https://www.google.com/maps/search/?api=1&query=${item.latitude},${item.longitude}`
    }
    const keyword = `${detail.value?.city ?? ''}${item.poiName}`
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(keyword)}`
  }
  const keyword = `${detail.value?.city ?? ''}${item.poiName}`
  return `https://uri.amap.com/search?keyword=${encodeURIComponent(keyword)}`
}

// ---------- 附近推荐：开合状态在本组件，取数与渲染在 NearbyRecommends ----------
const nearbyOpen = ref<Record<number, boolean>>({})

function toggleNearby(item: TripItem) {
  const id = item.id!
  nearbyOpen.value[id] = !nearbyOpen.value[id]
}

const TYPE_LABEL: Record<string, string> = {
  attraction: '景点',
  food: '美食',
  hotel: '酒店',
  transport: '交通',
}

const TYPE_TAG: Record<string, string> = {
  attraction: 'primary',
  food: 'warning',
  hotel: 'success',
  transport: 'info',
}

function typeLabel(type: string) {
  return TYPE_LABEL[type] || type
}

function tagType(type: string) {
  return (TYPE_TAG[type] || 'info') as 'primary' | 'warning' | 'success' | 'info'
}

function sourceLabel(source?: string | null) {
  if (!source) return '待补充'
  if (source === 'mysql.poi_knowledge') return '目的地知识库'
  if (source === 'llm.open_day') return '开放研究（需复核）'
  if (source === 'amap-grounding' || source === 'amap') return '高德地图'
  return source
}

function formatSourceDate(value?: string | null) {
  if (!value) return ''
  return value.replace('T', ' ').replace(/([+-]\d{2}:?\d{2}|Z)$/, '').slice(0, 16)
}

async function onDeleteItem(item: TripItem) {
  await ElMessageBox.confirm(`确认删除「${item.poiName}」？`, '删除确认', { type: 'warning' })
  await actions.deleteItem(item.id!)
  ElMessage.success('已删除')
}

// ---------- 行内增删改对话框：可见性在本组件，表单逻辑在子组件 ----------
const addDialogVisible = ref(false)

function openAddDialog() {
  addDialogVisible.value = true
}

const editDialogVisible = ref(false)
const editTarget = ref<TripItem | null>(null)

function openEditDialog(item: TripItem) {
  editTarget.value = item
  editDialogVisible.value = true
}
</script>

<style scoped>
/* ---------- 逐日折叠面板 ---------- */
.day-panel summary {
  display: grid;
  grid-template-columns: 78px 1fr 34px;
  gap: 24px;
  align-items: center;
  padding: 26px 0 22px;
  border-bottom: 1px solid #d8dfda;
  cursor: pointer;
  list-style: none;
}

.day-panel summary::-webkit-details-marker {
  display: none;
}

.day-idx {
  font-family: var(--lp-font-display);
  font-style: italic;
  font-weight: 400;
  font-size: 36px;
  line-height: 1.1;
  color: var(--lp-accent-warm);
  font-variant-numeric: tabular-nums;
}

.day-meta {
  display: block;
  font-size: 12px;
  color: var(--lp-muted);
}

.day-title {
  display: block;
  margin: 6px 0 4px;
  font-family: var(--lp-font-display);
  font-weight: 500;
  font-size: 23px;
  line-height: 1.25;
  color: var(--lp-ink);
  letter-spacing: -0.01em;
}

.day-count {
  display: block;
  font-size: 13px;
  color: var(--lp-muted);
}

/* ---------- 流式生成态（§5.3.5） ---------- */
/* 当日微光：--lp-stream-glow 背景脉冲；reduce 下退化为静态微光底 + 「生成中」文案 */
.day-panel.is-glowing > summary {
  animation: lp-day-glow 2s ease-in-out infinite;
}

@keyframes lp-day-glow {
  0%,
  100% {
    background-color: transparent;
  }

  50% {
    background-color: var(--lp-stream-glow);
  }
}

@media (prefers-reduced-motion: reduce) {
  .day-panel.is-glowing > summary {
    animation: none;
    background-color: var(--lp-stream-glow);
  }
}

.sk-meta {
  width: 32%;
  height: 11px;
}

.sk-title {
  width: 64%;
  height: 20px;
  margin-top: 8px;
}

.sk-count {
  width: 26%;
  height: 11px;
  margin-top: 8px;
}

/* 状态徽标：状态取基础层色，待生成/生成中为 data mono 小字 */
.day-state {
  display: inline-block;
  margin-left: 8px;
  padding: 1px 8px;
  border: 1px solid var(--lp-rule);
  border-radius: 999px;
  font-family: var(--lp-font-data);
  font-size: 10.5px;
  color: var(--lp-why-ink);
}

.day-state.state-active {
  border-color: var(--lp-accent);
  color: var(--lp-accent);
}

/* 降级角标：--lp-why-ink + 警示描边（原则 4 如实可见）；失败态用 danger */
.day-flag {
  display: inline-flex;
  align-items: center;
  margin-top: 6px;
  padding: 2px 10px;
  border: 1px solid var(--lp-warning);
  border-radius: 999px;
  background: var(--el-color-warning-light-9);
  font-size: 11px;
  color: var(--lp-why-ink);
}

.day-flag.flag-fail {
  border-color: var(--lp-danger);
  background: var(--el-color-danger-light-9);
  color: var(--lp-danger);
}

.day-plus {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid #c9d2cc;
  border-radius: 50%;
  font-size: 16px;
  color: var(--lp-ink-soft);
  transition: transform 0.25s ease;
}

.day-panel[open] .day-plus {
  transform: rotate(45deg);
}

.day-content {
  padding: 18px 0 8px;
}

.route-toolbar {
  display: flex;
  justify-content: flex-end;
  margin: 0 0 10px;
}

/* ---------- 站点轨道行 ---------- */
.route-row {
  display: grid;
  grid-template-columns: 104px 40px minmax(0, 1fr) auto;
  gap: 12px;
  padding: 14px 16px;
  margin-bottom: 10px;
  background: #fff;
  border: 1px solid var(--lp-border);
  border-radius: 12px;
  cursor: pointer;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}

.route-row:hover {
  border-color: var(--lp-accent);
}

.route-row:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: 2px;
}

.row-img {
  width: 104px;
  height: 72px;
  border-radius: 8px;
  overflow: hidden;
  background: var(--lp-sand);
}

.row-img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.row-img-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--lp-accent);
  font-weight: 700;
  font-size: 12px;
  letter-spacing: 0.08em;
}

@media (max-width: 640px) {
  .route-row {
    grid-template-columns: 72px 40px minmax(0, 1fr) auto;
  }

  .row-img {
    width: 72px;
    height: 54px;
  }
}

.route-row.highlighted {
  border-color: var(--lp-accent);
  box-shadow: 0 0 0 2px var(--lp-accent-soft);
}

.row-no {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding-top: 2px;
}

.row-idx {
  font-family: var(--lp-font-display);
  font-style: italic;
  font-size: 17px;
  color: var(--lp-accent-warm);
}

.row-main {
  min-width: 0;
}

.row-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

/* POI 名称用正文轨（衬线展示层只承担叙事标题，§5.1 排版规则） */
.row-name {
  font-family: var(--lp-font-body);
  font-weight: 600;
  font-size: 15px;
  color: var(--lp-ink);
}

.row-time {
  font-size: 13px;
  font-weight: 700;
  color: var(--lp-ink-soft);
  font-variant-numeric: tabular-nums;
}

.row-dwell {
  font-size: 11px;
  color: var(--lp-muted);
}

.row-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin-top: 6px;
  color: var(--lp-muted);
  font-size: 12px;
}

.poi-source {
  margin: 3px 0 0;
  color: var(--lp-muted);
  font-size: 11px;
  opacity: 0.85;
}

.poi-desc {
  margin: 8px 0 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--lp-ink-soft);
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.poi-desc.expanded {
  display: block;
  -webkit-line-clamp: unset;
  line-clamp: unset;
  overflow: visible;
}

.poi-desc-toggle {
  height: auto;
  padding: 0;
  margin-top: 4px;
}

.poi-remark {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--lp-muted);
}

.row-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: center;
  gap: 6px;
}

.row-side .el-button + .el-button {
  margin-left: 0;
}

.row-map {
  font-size: 11px;
  color: var(--lp-accent);
  text-decoration: none;
  border-bottom: 1px solid transparent;
}

.row-map:hover {
  border-bottom-color: var(--lp-accent);
}
</style>

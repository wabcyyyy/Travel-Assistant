<template>
  <details
    class="day-panel"
    :class="{ 'is-glowing': isActiveDay, 'is-drop-over': dropOver }"
    :open="!collapsed"
    :style="dayTintStyle"
    @dragover.prevent="dropOver = true"
    @dragleave="onDragLeave"
    @drop.prevent="onDrop"
  >
    <summary @click="onSummaryClick">
      <span class="day-badge" :aria-label="`第 ${day.dayNo} 天`">
        {{ String(day.dayNo).padStart(2, '0') }}
      </span>
      <span class="day-main">
        <!-- 流式研究阶段：日卡骨架态（shimmer 由 .lp-skel-line 公共件按系统动效偏好启停） -->
        <template v-if="isSkeleton">
          <span class="lp-skel-line sk-meta"></span>
          <span class="lp-skel-line sk-title"></span>
          <span class="lp-skel-line sk-count"></span>
        </template>
        <template v-else>
          <span class="day-meta">{{ dayMetaText(day) }}</span>
          <span class="qe-wrap day-title-wrap" @click.stop>
            <AppPopover
              :open="subtitleOpen"
              label="编辑日标题"
              align="start"
              @update:open="(open) => syncSubtitle(open)"
            >
              <template #trigger>
                <button
                  type="button"
                  class="day-title day-title-btn"
                  :title="day.theme ? '点击编辑副标题' : '点击添加副标题'"
                >
                  {{ dayTitle(day) }}
                </button>
              </template>
              <div class="qe-body">
                <label class="qe-label">
                  副标题（留空回退自动标题）
                  <AppInput v-model="subtitleDraft" placeholder="例如：老街与市集" aria-label="日标题" />
                </label>
                <button type="button" class="qe-save" @click="saveSubtitle">保存</button>
              </div>
            </AppPopover>
          </span>
          <span class="day-count">
            {{ (day.items || []).length }} 个点位<template v-if="dayTotalAmount > 0"> · 约 ￥{{ dayTotalAmount.toLocaleString('zh-CN') }}</template>
            <span v-if="isActiveDay" class="day-state state-active">排版中</span>
            <span v-else-if="isPendingDay" class="day-state">待排版</span>
          </span>
          <!-- 日头工作台（W3）：建议方案（day_options 只读）/ 优化路线（确定性重排，可回滚） -->
          <span v-if="dayOptions.length || activeCount >= 2" class="day-tools" @click.stop>
            <span v-if="dayOptions.length" class="qe-wrap">
              <AppPopover
                :open="optionsOpen"
                label="建议方案"
                align="start"
                @update:open="(open) => (optionsOpen = open)"
              >
                <template #trigger>
                  <button type="button" class="diy-tool">
                    <Lightbulb :size="14" /> 建议方案
                  </button>
                </template>
                <div class="opt-list">
                  <div v-for="(opt, i) in dayOptions" :key="i" class="opt-card">
                    <p class="opt-head">
                      <span class="opt-label">{{ opt.label }}</span>
                      <span class="opt-summary">{{ opt.summary }}</span>
                    </p>
                    <p v-if="opt.tradeoff" class="opt-sub">取舍：{{ opt.tradeoff }}</p>
                    <p v-if="optionNames(opt).length" class="opt-sub">
                      点位：{{ optionNames(opt).join('、') }}
                    </p>
                  </div>
                </div>
              </AppPopover>
            </span>
            <button
              v-if="activeCount >= 2"
              type="button"
              class="diy-tool"
              :disabled="optimizing"
              :title="`按交通耗时重排当天 ${activeCount} 个点位（可在版本历史回滚）`"
              @click="onOptimize"
            >
              <Route :size="14" /> {{ optimizing ? '优化中…' : '优化路线' }}
            </button>
          </span>
        </template>
        <!-- 降级/失败如实可见（原则 4）：degraded 按 scope 对应日卡，PARTIAL 保留 degradedDays -->
        <span v-if="notGenerated" class="day-flag flag-fail">未成功生成</span>
        <span v-else-if="dayDegraded" class="day-flag">已降级 · {{ dayDegraded.reason }}</span>
      </span>
      <span class="day-chev" aria-hidden="true"><ChevronDown :size="18" /></span>
    </summary>

    <div class="day-content">
      <!-- 导语与方案分叉（DayNarrativePanel）；实用/拍照/备选已拆为内联提示卡 -->
      <DayNarrativePanel :day="day" />

      <DayInlineTips :day="day" />

      <div v-if="!(day.items || []).length" class="day-empty">当天暂无安排</div>
      <draggable
        :list="day.items"
        item-key="id"
        handle=".drag-handle"
        :animation="150"
        :group="{ name: 'trip-items' }"
        :data-day-id="day.dayId"
        @end="onDragEnd"
      >
        <template #item="{ element, index }">
          <div :id="`item-${element.id}`" :data-item-id="element.id" class="row-wrap">
            <!-- 站间分隔条（v2.7 §20 R3，TREK 的「6h5min · 27.5km」等价物）：
                 本地直线估算 + 明确标注，缺坐标不画 -->
            <div v-if="legAt(index)" class="leg-row" :title="LEG_HINT">
              <span class="leg-line" aria-hidden="true"></span>
              <component
                :is="legAt(index)?.mode === 'walk' ? Footprints : Car"
                :size="10"
                :stroke-width="2"
                aria-hidden="true"
              />
              <span class="leg-text">{{ legLabel(index) }}</span>
              <span class="leg-line" aria-hidden="true"></span>
            </div>
            <div
              class="route-row"
              :class="{ highlighted: element.id === highlightId }"
              role="button"
              tabindex="0"
              :aria-label="`行程点位：${element.poiName}`"
              @click="onItemClick(element)"
              @keydown.enter.prevent="onItemClick(element)"
            >
              <input
                type="checkbox"
                class="row-check"
                :checked="selectedIds.includes(element.id!)"
                :aria-label="`选择「${element.poiName}」`"
                @click.stop
                @change="emit('toggle-select', element)"
              />
              <DragSortHandle
                class="row-grip"
                :day="day"
                :item="element"
                :index="index"
                :total="(day.items || []).length"
                @moved="emit('item-drop', $event)"
              />
              <!-- 28px 圆头像（TREK 行解剖）：缩略图失败落分类字块；左上角压天内序号 -->
              <span class="row-avatar">
                <img
                  v-if="imgLevel(element) < 2 && imgSrc(element)"
                  :src="imgSrc(element)"
                  :alt="element.poiName"
                  loading="lazy"
                  @error="onImgError(element)"
                />
                <span v-else class="row-avatar-fallback" aria-hidden="true">
                  {{ typeLabel(element.itemType).slice(0, 1) }}
                </span>
                <i class="stop-badge" aria-hidden="true">{{ index + 1 }}</i>
              </span>
              <div class="row-main">
                <div class="row-top">
                  <!-- 分类小图标 10px + 名称 12.5px/500 + 时间 10px 文本（点开即改，不再常显 chip） -->
                  <component
                    :is="typeIcon(element.itemType)"
                    class="row-type-icon"
                    :size="10"
                    :stroke-width="2"
                    aria-hidden="true"
                  />
                  <span class="row-name">{{ element.poiName }}</span>
                  <span class="qe-wrap" @click.stop>
                    <AppPopover
                      :open="quickEdit?.id === element.id && quickEdit?.field === 'time'"
                      :label="`编辑「${element.poiName}」的时间`"
                      align="start"
                      @update:open="(open) => syncQuick(element, 'time', open)"
                    >
                      <template #trigger>
                        <button v-if="element.startTime" type="button" class="row-time" title="编辑时间">
                          <Clock :size="9" :stroke-width="2" />
                          {{ formatTime(element.startTime) }}<template v-if="element.endTime"> – {{ formatTime(element.endTime) }}</template>
                        </button>
                        <button v-else type="button" class="row-time is-empty" title="添加时间">加时间</button>
                      </template>
                      <div class="qe-body">
                        <label class="qe-label">
                          开始时间
                          <AppInput v-model="timeDraft" type="time" aria-label="开始时间" />
                        </label>
                        <label class="qe-label">
                          时长（分钟）
                          <AppNumberInput v-model="durDraft" :min="0" aria-label="时长" />
                        </label>
                        <button type="button" class="qe-save" @click="saveTime(element)">保存</button>
                      </div>
                    </AppPopover>
                  </span>
                </div>
                <!-- 描述行：10px 单行省略（全文见贴底详情卡）；无描述落地址 -->
                <p v-if="element.intro || element.description || element.address" class="row-desc">
                  {{ element.intro || element.description || element.address }}
                </p>
                <!-- 备注行：10px + StickyNote 9px 单行 -->
                <p v-if="element.remark" class="row-remark">
                  <StickyNote :size="9" :stroke-width="2" aria-hidden="true" />
                  <span>{{ element.remark }}</span>
                </p>
              </div>
              <span class="qe-wrap row-cost-wrap" @click.stop>
                <AppPopover
                  :open="quickEdit?.id === element.id && quickEdit?.field === 'cost'"
                  :label="`编辑「${element.poiName}」的费用`"
                  align="end"
                  @update:open="(open) => syncQuick(element, 'cost', open)"
                >
                  <template #trigger>
                    <button v-if="element.cost != null" type="button" class="row-cost" title="编辑费用">
                      ￥{{ element.cost }}
                    </button>
                    <button v-else type="button" class="row-cost is-empty" title="添加费用">￥—</button>
                  </template>
                  <div class="qe-body">
                    <label class="qe-label">
                      费用（￥{{ element.itemType === 'hotel' ? '每晚每间' : '每人' }}）
                      <AppNumberInput v-model="costDraft" :min="0" :precision="2" aria-label="费用" />
                    </label>
                    <button type="button" class="qe-save" @click="saveCost(element)">保存</button>
                  </div>
                </AppPopover>
              </span>
              <!-- 行操作：hover/聚焦才现身（TREK 的「悬停出操作」语义），图标 16px -->
              <div class="row-actions">
                <a
                  class="row-icon"
                  :href="mapLinkOf(element)"
                  target="_blank"
                  rel="noopener"
                  :title="mapLinkLabel"
                  :aria-label="mapLinkLabel"
                  @click.stop
                >
                  <ExternalLink :size="16" />
                </a>
                <button
                  type="button"
                  class="row-icon"
                  title="移至其他天"
                  aria-label="移至其他天"
                  @click.stop="emit('move-request', element)"
                >
                  <ArrowRightLeft :size="16" />
                </button>
                <button
                  type="button"
                  class="row-icon"
                  title="编辑详情"
                  aria-label="编辑详情"
                  @click.stop="emit('edit-request', element)"
                >
                  <Pencil :size="16" />
                </button>
                <button
                  type="button"
                  class="row-icon is-danger"
                  title="删除"
                  aria-label="删除"
                  @click.stop="onDeleteItem(element)"
                >
                  <Trash2 :size="16" />
                </button>
              </div>
            </div>
          </div>
        </template>
      </draggable>

      <!-- 日尾：添加地点（整行虚线钮；打开右栏「发现」并预设本天为目标天，W2） -->
      <button type="button" class="quick-add" @click="emit('add-request', day.dayId)">
        <Plus :size="16" /> 添加地点
      </button>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import draggable from 'vuedraggable'
import { storeToRefs } from 'pinia'
import {
  ArrowRightLeft,
  Car,
  ChevronDown,
  Clock,
  ExternalLink,
  Footprints,
  Lightbulb,
  Pencil,
  Plus,
  Route,
  StickyNote,
  Trash2,
} from 'lucide-vue-next'

import { useItineraryStore, type StreamState } from '../../store/itinerary'
import { useItineraryActions } from '../../composables/useItineraryActions'
import { dayMetaText, dayTitle, dayTotalAmountOf, dayTintVar, formatTime, typeIcon, typeLabel } from './day-card/shared'
import DayInlineTips from './day-card/DayInlineTips.vue'
import { useItemPhoto } from '../../composables/useItemPhoto'
import { useQuickEdit } from './day-card/useQuickEdit'
import type { DayOption, DayPlan, TripItem } from '../../types/itinerary'
import { isForeignCity, externalMapLink } from '../../utils/geo'
import { estimateLeg, legText, type TravelLeg } from '../../utils/travelEstimate'
import DayNarrativePanel from './DayNarrativePanel.vue'
import DragSortHandle from './DragSortHandle.vue'
import AppInput from '../ui/AppInput.vue'
import AppNumberInput from '../ui/AppNumberInput.vue'
import AppPopover from '../ui/AppPopover.vue'
import { confirmDialog } from '../ui/confirm'
import { toast } from '../ui/toast'

// 单日卡（M4-②a §5.4 / M4-②b §5.3；v2.6 §19.3 天平铺重排）：
// - 展开态由壳的 collapsedDays 反向控制（默认全展开，可单天折叠）；
// - 日头 = day-tint 编号徽 + 日期/星期 + 标题 + 计数；内联提示卡（实用/拍照/备选）；
// - why_this 并入 poi-desc 段尾；搜索添加 / 行内编辑对话框均为自包含子组件；
// - 图片三级降级收敛为 useItemPhoto（§5.3.6）。
// 组件只读 store，写变更一律经 useItineraryActions；拖拽/键盘排序为乐观本地变更，
// 壳接收 item-drop 后走 actions.reorderItems 持久化（快照兜底，失败回滚顺序）。
const props = defineProps<{
  day: DayPlan
  /** SSE 生成状态机（§5.3.5）：驱动骨架态 / 当日微光 / 待生成与降级角标 */
  streamState: StreamState
  /** 折叠态（受控于壳的 collapsedDays，天平铺默认全展开） */
  collapsed: boolean
  /** 地图联动高亮的行程项 id */
  highlightId: number | null
  /** 选择态（W2 批量）：被勾选的行程项 id 集合 */
  selectedIds: number[]
}>()

const emit = defineEmits<{
  'item-drop': [day: DayPlan]
  'item-select': [item: TripItem]
  toggle: [dayNo: number]
  /** 请求跨天移动（打开目标日选择，键盘可达路径） */
  'move-request': [item: TripItem]
  /** 请求打开「更多字段」编辑对话框（壳层统一持有 ItemEditDialog） */
  'edit-request': [item: TripItem]
  /** 勾选/取消勾选行程项（批量条由壳渲染） */
  'toggle-select': [item: TripItem]
  /** 日尾「添加地点」：壳打开右栏发现面板并预设本天为目标天 */
  'add-request': [dayId: number]
  /** 右栏「发现」卡片拖落到本天（载荷由 dataTransfer JSON 携带，壳做结构校验与落库） */
  'discover-drop': [payload: { dayId: number; entry: unknown }]
  /** 拖拽落在别的日卡上：交壳持久化（复用 updateItem 带 dayId，不新增端点） */
  'item-moved': [payload: { itemId: number; targetDayId: number }]
}>()

const store = useItineraryStore()
const actions = useItineraryActions()
const { quickEdit, timeDraft, durDraft, costDraft, syncQuick, saveTime, saveCost } = useQuickEdit(actions)
const { detail } = storeToRefs(store)

const detailForeign = computed(() => isForeignCity(detail.value?.city ?? ''))
const mapLinkLabel = computed(() => (detailForeign.value ? '谷歌地图' : '高德地图'))

const dayTintStyle = computed(() => ({
  '--day-color': dayTintVar(props.day.dayNo),
}))

/* day-tint 消费（v2.6 §19.4）：D1–D8 循环取色，日头/编号徽按档位上色 */
const { imgLevel, imgSrc, onImgError } = useItemPhoto()

const dayTotalAmount = computed(() => dayTotalAmountOf(props.day.items, detail.value?.persons ?? 1))

/* ---------- 站间交通片（v2.7 §20 R3）：本地直线估算，界面带「≈」与估算说明 ---------- */
const LEG_HINT = '本地直线估算（含路网折算，非实时路况）'
const legs = computed<(TravelLeg | null)[]>(() => {
  const items = props.day.items || []
  return items.map((item, i) => (i === 0 ? null : estimateLeg(items[i - 1], item)))
})

function legAt(index: number): TravelLeg | null {
  return legs.value[index] ?? null
}

function legLabel(index: number): string {
  const leg = legs.value[index]
  return leg ? legText(leg) : ''
}

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

/** 拖拽结束：跨天（落点在别的日卡）走 item-moved；日内仍走 item-drop 排序。 */
function onDragEnd(evt: { to?: HTMLElement; from?: HTMLElement; item?: HTMLElement }) {
  const targetDayId = Number(evt.to?.dataset?.dayId)
  const sourceDayId = Number(evt.from?.dataset?.dayId)
  const itemId = Number(evt.item?.dataset?.itemId)
  if (targetDayId && sourceDayId && targetDayId !== sourceDayId && Number.isFinite(itemId)) {
    emit('item-moved', { itemId, targetDayId })
    return
  }
  emit('item-drop', props.day)
}

function onSummaryClick(event: MouseEvent) {
  // 折叠态由壳的 collapsedDays 单一受控：拦截 summary 原生 toggle，只发意图
  event.preventDefault()
  emit('toggle', props.day.dayNo)
}

function onItemClick(item: TripItem) {
  emit('item-select', item)
}

/** 地图外链：统一口径在 utils/geo（国内高德搜索 / 海外 Google Maps，有坐标优先） */
function mapLinkOf(item: TripItem) {
  return externalMapLink(
    { name: item.poiName, latitude: item.latitude, longitude: item.longitude },
    detail.value?.city,
  )
}

async function onDeleteItem(item: TripItem) {
  const ok = await confirmDialog(`确认删除「${item.poiName}」？`, { title: '删除确认', confirmText: '删除' })
  if (!ok) return
  await actions.deleteItem(item.id!)
  toast.success('已删除')
}

// ---------- 日头工作台（W3）：副标题编辑 / 建议方案（只读）/ 优化路线 ----------
const dayOptions = computed(() =>
  (props.day.dayOptions || []).filter(
    (opt) => (opt.label || opt.summary || opt.tradeoff || '').toString().trim(),
  ),
)

function optionNames(opt: DayOption): string[] {
  return (opt.items || []).map((item) => item.poiName).filter(Boolean)
}

/** 可优化活动项计数（与后端 optimize 的 400 门槛同口径：attraction / food） */
const activeCount = computed(
  () => (props.day.items || []).filter((it) => it.itemType === 'attraction' || it.itemType === 'food').length,
)

const subtitleOpen = ref(false)
const subtitleDraft = ref('')

function syncSubtitle(open: boolean) {
  if (open) subtitleDraft.value = props.day.theme || ''
  subtitleOpen.value = open
}

async function saveSubtitle() {
  await actions.updateDay(detail.value!.id, props.day.dayId, subtitleDraft.value.trim())
  subtitleOpen.value = false
  toast.success('日标题已更新')
}

const optionsOpen = ref(false)
const optimizing = ref(false)

async function onOptimize() {
  if (optimizing.value) return
  optimizing.value = true
  try {
    await actions.optimizeDay(detail.value!.id, props.day.dayId)
    toast.success('已按交通耗时重排当天（版本历史可回滚）')
  } finally {
    optimizing.value = false
  }
}

// ---------- 对话框：编辑对话框与添加入口均已收编壳层/右栏（W2 退役 PoiWorkbench） ----------

// ---------- 拖拽入天（W2）：接收右栏「发现」卡片（dataTransfer JSON 载荷），落库交壳 ----------
const dropOver = ref(false)

function onDragLeave(event: DragEvent) {
  const current = event.currentTarget as HTMLElement | null
  const next = event.relatedTarget as Node | null
  if (!current || !next || !current.contains(next)) dropOver.value = false
}

function onDrop(event: DragEvent) {
  dropOver.value = false
  const raw = event.dataTransfer?.getData('application/x-discover-entry')
  if (!raw) return
  try {
    emit('discover-drop', { dayId: props.day.dayId, entry: JSON.parse(raw) })
  } catch {
    /* 非法载荷忽略（不打断拖拽后的其他交互） */
  }
}

// ---------- 行内快捷编辑（时间 / 费用）：AppPopover + updateItem 单点写（v2.6 §19.3） ----------
</script>

<style scoped>
/* ---------- 逐日面板（天平铺）：日头带 day-tint，可单天折叠 ---------- */
.day-panel summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) 34px;
  gap: 14px;
  align-items: center;
  margin: 0 -12px;
  padding: 16px 12px;
  border-radius: var(--lp-radius-sm);
  background: color-mix(in oklch, var(--day-color) var(--lp-day-tint-header), transparent);
  border-bottom: 1px solid var(--lp-edge-faint);
  cursor: pointer;
  list-style: none;
  transition: background 0.15s ease;
}

.day-panel summary:hover {
  background: color-mix(in oklch, var(--day-color) var(--lp-day-tint-header-hover), transparent);
}

.day-panel summary::-webkit-details-marker {
  display: none;
}

/* 编号徽（day-tint badge 档）：替代旧衬线斜体序号 */
.day-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 40px;
  height: 40px;
  padding: 0 8px;
  border-radius: var(--lp-radius-sm);
  background: color-mix(in oklch, var(--day-color) var(--lp-day-tint-badge), transparent);
  color: color-mix(in oklch, var(--day-color) 70%, var(--lp-text-1));
  font-family: var(--lp-font-mono);
  font-size: 14px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.day-meta {
  display: block;
  font-size: 12px;
  color: var(--lp-muted);
}

.day-title {
  display: block;
  margin: 4px 0 3px;
  font-family: var(--lp-font-ui);
  font-weight: 700;
  font-size: 17px;
  line-height: 1.3;
  color: var(--lp-ink);
  letter-spacing: -0.01em;
}

/* 标题即可编辑入口（点击开副标题 popover）：视觉不变，hover 虚线提示可编辑 */
.day-title-btn {
  max-width: 100%;
  padding: 0;
  border: none;
  background: transparent;
  text-align: left;
  cursor: text;
}

.day-title-btn:hover {
  text-decoration: underline dashed;
  text-decoration-color: var(--lp-edge-2);
  text-underline-offset: 4px;
}

/* 日头工具行（建议方案 / 优化路线）：小号幽灵胶囊 */
.day-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.diy-tool {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 9px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-pill);
  background: var(--lp-surface-card);
  color: var(--lp-text-muted);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.diy-tool:hover:not(:disabled) {
  color: var(--lp-accent);
  border-color: var(--lp-accent);
}

.diy-tool:disabled {
  color: var(--lp-text-faint);
  cursor: default;
}

/* 建议方案弹层内容（自 DayNarrativePanel 迁入，v2.6 W3） */
.opt-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 300px;
}

.opt-card {
  padding: 8px 10px;
  border: 1px solid var(--lp-edge-1);
  border-left: 3px solid var(--lp-branch-b);
  border-radius: 0 8px 8px 0;
  background: var(--lp-surface-2);
}

.opt-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 0;
}

.opt-label {
  font-weight: 700;
  color: var(--lp-accent-hover);
  font-size: 13px;
}

.opt-summary {
  font-size: 12.5px;
  color: var(--lp-text-2);
}

.opt-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--lp-text-muted);
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

.day-chev {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--lp-edge-2);
  border-radius: 50%;
  font-size: 14px;
  color: var(--lp-ink-soft);
  transition: transform 0.25s ease;
}

/* 收起/展开语义明确化：箭头旋转 180°，替代旧「＋→×」的歧义旋转 */
.day-panel[open] .day-chev {
  transform: rotate(180deg);
}

.day-content {
  padding: 14px 0 10px;
}

.day-empty {
  padding: 18px 0;
  text-align: center;
  color: var(--lp-text-muted);
  font-size: 13px;
}

/* ---------- 站间交通片（v2.7 §20 R3）：虚线 + 图标 + 「步行 ≈ 12 分钟 · 0.9 公里」 ---------- */
.row-wrap {
  border-radius: var(--lp-radius-xs);
}

.leg-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 12px;
  color: var(--lp-text-faint);
  font-size: 9.5px;
  font-variant-numeric: tabular-nums;
  pointer-events: none;
}

.leg-line {
  flex: 1;
  border-top: 1px dashed var(--lp-edge-2);
}

.leg-text {
  flex: none;
  white-space: nowrap;
}

/* ---------- 站点行（v2.7 §20 R3 照抄 TREK DayPlanSidebar 行解剖） ----------
   一条横长条：勾选 + 抓手 + 28px 圆头像 + 名称/时间/描述/备注三行文本 + 费用；
   hover 出 16px 图标操作列（地图外链 / 移至 / 编辑 / 删除） */
.route-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  scroll-margin-top: 84px;
  padding: 7px 8px 7px 10px;
  border-left: 3px solid transparent;
  border-radius: var(--lp-radius-xs);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.route-row:hover {
  background: var(--lp-surface-hover);
}

.route-row:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: -2px;
}

.route-row.highlighted {
  background: var(--lp-surface-selected);
  border-left-color: var(--lp-accent);
}

/* 拖拽入天落点提示：整卡虚线描边（dragover 期间） */
.day-panel.is-drop-over > summary {
  outline: 2px dashed var(--lp-accent);
  outline-offset: -2px;
}

.row-check {
  flex: none;
  width: 14px;
  height: 14px;
  margin: 0;
  accent-color: var(--lp-accent);
  cursor: pointer;
  opacity: 0.5;
  transition: opacity 0.15s;
}

.route-row:hover .row-check,
.row-check:checked {
  opacity: 1;
}

/* 抓手：常态 0.3 亮度，行 hover/聚焦才亮起（TREK 同款） */
.row-grip {
  flex: none;
  opacity: 0.3;
  transition: opacity 0.15s;
}

.route-row:hover .row-grip,
.route-row:focus-within .row-grip {
  opacity: 1;
}

/* 28px 圆头像；缩略图失败落分类字块；左上角压天内序号（与地图图钉同号） */
.row-avatar {
  position: relative;
  flex: none;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  overflow: visible;
  background: var(--lp-surface-2);
}

.row-avatar img {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  display: block;
}

.row-avatar-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: color-mix(in oklch, var(--day-color) var(--lp-day-tint-badge), transparent);
  color: color-mix(in oklch, var(--day-color) 75%, var(--lp-text-1));
  font-size: 11px;
  font-weight: 700;
}

/* 编号徽（day-tint badge 档，与日头徽/地图图钉同源） */
.stop-badge {
  position: absolute;
  top: -4px;
  left: -4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 15px;
  height: 15px;
  padding: 0 3px;
  border-radius: var(--lp-radius-pill);
  background: var(--lp-surface-card);
  color: color-mix(in oklch, var(--day-color) 75%, var(--lp-text-1));
  box-shadow: 0 0 0 1.5px color-mix(in oklch, var(--day-color) var(--lp-day-tint-badge), transparent);
  font-family: var(--lp-font-mono);
  font-size: 9px;
  font-style: normal;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.row-main {
  flex: 1;
  min-width: 0;
}

.row-top {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.row-type-icon {
  flex: none;
  color: var(--lp-text-muted);
}

.row-name {
  font-family: var(--lp-font-body);
  font-weight: 500;
  font-size: 12.5px;
  line-height: 1.2;
  color: var(--lp-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 时间 10px 纯文本（v2.7 §20 R3：不再常显 chip），点开即改 */
.row-time {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: 6px;
  padding: 0;
  border: none;
  background: none;
  color: var(--lp-text-faint);
  font-family: inherit;
  font-size: 10px;
  font-weight: 400;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}

.row-time:hover {
  color: var(--lp-text-1);
}

.row-time.is-empty {
  color: var(--lp-text-faint);
  opacity: 0.75;
}

/* 描述行：10px 单行省略（全文在贴底详情卡） */
.row-desc {
  margin: 2px 0 0;
  max-height: 1.2em;
  font-size: 10px;
  line-height: 1.2;
  color: var(--lp-text-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 备注行：10px + StickyNote 9px（TREK 同款单行） */
.row-remark {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 2px 0 0;
  font-size: 10px;
  line-height: 1.2;
  color: var(--lp-text-faint);
  overflow: hidden;
}

.row-remark span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-cost-wrap {
  flex: none;
  margin-left: auto;
}

.row-cost {
  padding: 0;
  border: none;
  background: none;
  color: var(--lp-text-muted);
  font-family: var(--lp-font-mono);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}

.row-cost:hover {
  color: var(--lp-text-1);
}

.row-cost.is-empty {
  opacity: 0.6;
}

/* 行操作：默认隐去，hover/聚焦浮出行尾；底衬淡出避免压字 */
.row-actions {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 0 8px 0 18px;
  border-radius: 0 var(--lp-radius-xs) var(--lp-radius-xs) 0;
  background: linear-gradient(
    to right,
    transparent,
    var(--lp-surface-hover) 24%,
    var(--lp-surface-hover)
  );
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
}

.route-row:hover .row-actions,
.route-row:focus-within .row-actions {
  opacity: 1;
  pointer-events: auto;
}

.route-row.highlighted:hover .row-actions {
  background: linear-gradient(
    to right,
    transparent,
    var(--lp-surface-selected) 24%,
    var(--lp-surface-selected)
  );
}

.row-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--lp-radius-xs);
  background: transparent;
  color: var(--lp-text-muted);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.row-icon:hover {
  background: var(--lp-surface-card);
  color: var(--lp-text-1);
}

.row-icon.is-danger:hover {
  color: var(--lp-danger);
}

/* ---------- 日尾添加地点（整行虚线钮；打开右栏「发现」并预设目标天） ---------- */
.quick-add {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  margin-top: 10px;
  padding: 9px 0;
  border: 1px dashed var(--lp-edge-2);
  border-radius: var(--lp-radius-sm);
  background: transparent;
  color: var(--lp-text-muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.quick-add:hover {
  color: var(--lp-accent);
  border-color: var(--lp-accent);
}

/* ---------- 行内快捷编辑（时间 / 费用） ---------- */
.qe-wrap {
  display: inline-flex;
}

.qe-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.qe-label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
  color: var(--lp-text-muted);
}

.qe-save {
  align-self: flex-end;
  padding: 4px 14px;
  border: none;
  border-radius: var(--lp-radius-xs);
  background: var(--lp-accent);
  color: var(--lp-accent-on-fill);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.qe-save:hover {
  background: var(--lp-accent-hover);
}
</style>

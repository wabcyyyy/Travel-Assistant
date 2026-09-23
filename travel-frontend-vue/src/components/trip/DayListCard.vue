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
          <span v-if="readOnly !== true" class="qe-wrap day-title-wrap" @click.stop>
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
          <span v-if="dayOptions.length || activeCount >= 2 || routeStops.length >= 2" class="day-tools" @click.stop>
            <a v-if="directionsUrl" class="diy-tool" :href="directionsUrl" target="_blank" rel="noopener noreferrer">
              <Route :size="14" /> {{ routeStops.length === (day.items || []).length ? '全天路线' : '有坐标点路线' }}
            </a>
            <span v-else-if="routeStops.length >= 2" class="route-hint">点位超出地图途经点上限，请逐项核实</span>
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
              v-if="activeCount >= 2 && readOnly !== true"
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
        :disabled="readOnly === true"
        @end="onDragEnd"
      >
        <!-- 行解剖已抽到 DayItemRow（bc58c82 收尾）：勾选/抓手/头像/行内编辑/hover 操作均在其内部。
             draggable 的 item 插槽只允许一个根子节点，注释也不能放里面 -->
        <template #item="{ element, index }">
          <DayItemRow
            :item="element"
            :index="index"
            :day="day"
            :leg="legAt(index)"
            :selected="selectedIds.includes(element.id!)"
            :highlighted="element.id === highlightId"
            :read-only="readOnly === true"
            @item-drop="(d) => emit('item-drop', d)"
            @item-select="(item) => emit('item-select', item)"
            @toggle-select="(item) => emit('toggle-select', item)"
            @move-request="(item) => emit('move-request', item)"
            @edit-request="(item) => emit('edit-request', item)"
          />
        </template>
      </draggable>

      <!-- 日尾：添加地点（整行虚线钮；打开右栏「发现」并预设本天为目标天，W2） -->
      <button v-if="readOnly !== true" type="button" class="quick-add" @click="emit('add-request', day.dayId)">
        <Plus :size="16" /> 添加地点
      </button>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import draggable from 'vuedraggable'
import { storeToRefs } from 'pinia'
import { ChevronDown, Lightbulb, Plus, Route } from 'lucide-vue-next'

import { useItineraryStore, type StreamState } from '../../store/itinerary'
import { useItineraryActions } from '../../composables/useItineraryActions'
import { dayMetaText, dayTitle, dayTotalAmountOf, dayTintVar } from './day-card/shared'
// DayItemRow 必须显式导入：依赖 unplugin 自动按名解析时，其 scoped 样式模块会被
// 整体丢出打包（dev/build 皆然），行会退回无样式的巨图+全宽文本（2026-09-17 实测）。
import DayItemRow from './day-card/DayItemRow.vue'
import DayInlineTips from './day-card/DayInlineTips.vue'
import type { DayOption, DayPlan, TripItem } from '../../types/itinerary'
import { estimateLeg, type TravelLeg } from '../../utils/travelEstimate'
import { hasValidCoordinates, mapDirectionsUrl } from '../../utils/geo'
import DayNarrativePanel from './DayNarrativePanel.vue'
import AppInput from '../ui/AppInput.vue'
import AppPopover from '../ui/AppPopover.vue'
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
  /** 协作（C2.3）：viewer 只读——隐藏添加/勾选/编辑入口并禁拖拽（后端闸门为准） */
  readOnly?: boolean
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
const { detail } = storeToRefs(store)

const dayTintStyle = computed(() => ({
  '--day-color': dayTintVar(props.day.dayNo),
}))

const dayTotalAmount = computed(() => dayTotalAmountOf(props.day.items, detail.value?.persons ?? 1))
const routeStops = computed(() => (props.day.items || []).filter(hasValidCoordinates)
  .map((item) => ({ name: item.poiName, latitude: item.latitude, longitude: item.longitude })))
const directionsUrl = computed(() => mapDirectionsUrl(routeStops.value, detail.value?.city))

/* ---------- 站间交通片（v2.7 §20 R3）：本地直线估算，leg 文案在 DayItemRow 内渲染 ---------- */
const legs = computed<(TravelLeg | null)[]>(() => {
  const items = props.day.items || []
  return items.map((item, i) => (i === 0 ? null : estimateLeg(items[i - 1], item)))
})

function legAt(index: number): TravelLeg | null {
  return legs.value[index] ?? null
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
  padding: 18px 14px;
  border-radius: var(--lp-radius-sm);
  background: color-mix(in oklch, var(--day-color) var(--lp-day-tint-header), transparent);
  border-bottom: 1px solid var(--lp-edge-1);
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

/* 编号徽（day-tint badge 档） */
.day-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  height: 44px;
  padding: 0 10px;
  border-radius: var(--lp-radius-sm);
  background: color-mix(in oklch, var(--day-color) var(--lp-day-tint-badge), transparent);
  color: color-mix(in oklch, var(--day-color) 70%, var(--lp-text-1));
  font-family: var(--lp-font-display);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

.day-meta {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: var(--lp-text-muted);
}

.day-title {
  display: block;
  margin: 4px 0 3px;
  font-family: var(--lp-font-display);
  font-weight: 600;
  font-size: 18px;
  line-height: 1.25;
  color: var(--lp-text-1);
  letter-spacing: -0.02em;
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
  font-weight: 500;
  color: var(--lp-text-muted);
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
  font-size: 11px;
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
</style>

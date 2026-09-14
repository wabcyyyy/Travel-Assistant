<template>
  <div class="trip-detail" v-loading="loading">
    <div class="reading-progress" aria-hidden="true"></div>

    <!-- 加载失败/无权限/不存在：完整错误态页，页面自解释而非只剩页脚 -->
    <el-card v-if="loadError && !detail" shadow="never" class="load-error">
      <el-empty :image-size="120" :description="loadErrorDescription">
        <div class="load-error-actions">
          <el-button type="primary" @click="$router.push('/trips')">返回我的行程</el-button>
          <el-button @click="$router.push('/generate')">去生成新行程</el-button>
          <el-button text @click="loadDetail">重新加载</el-button>
        </div>
      </el-empty>
    </el-card>

    <TripCoverHeader
      v-if="detail"
      :detail="detail"
      :exporting-pdf="exportBarRef?.exportingPdf"
      :exporting-img="exportBarRef?.exportingImg"
      @export-pdf="onExportPdf"
      @export-image="onExportImage"
      @similar="$router.push('/generate')"
      @back="$router.back()"
    />

    <!-- §5.3.1 主题叙事条：trip_theme 衬线大字 + theme-accent 底线；意图回显行有值才渲染；
         无 trip_theme（历史行程/降级生成）整条隐藏，不出现空壳 -->
    <section v-if="detail?.tripTheme" class="theme-bar">
      <h2 class="theme-title">{{ detail.tripTheme }}</h2>
      <p v-if="detail.intent" class="theme-intent">{{ detail.intent }}</p>
    </section>

    <el-card v-if="detail" shadow="never" class="head">
      <HeadStatusPanel :detail="detail" :done-days="doneDays" :stream-state="streamState" @retry="onStreamRetry" />
      <ButlerNoteCard
        v-if="detail.planNote && detail.status !== 3"
        :note="detail.planNote"
        :streaming="streamState.phase === 'butler'"
      />
      <ChatEditPanel :itinerary-id="detail.id" @apply-draft="loadDetail" />
    </el-card>

    <!-- 预算概览条：替代原右栏看板，天级小计在日卡标题、条目价格在点位卡 -->
    <BudgetStrip
      v-if="detail"
      :budget-list="detail.budgetList"
      :total-amount="detail.totalAmount"
      :budget-limit="detail.budget"
      :persons="detail.persons"
      :days="detail.dayList.length"
    />

    <!-- 手册白底大区：粘性迷你目录 + 逐日轨道全宽（原右栏已随地图/预算看板一并取消） -->
    <div v-if="detail" class="handbook-body">
      <nav class="day-toc" aria-label="每日目录">
        <button
          v-for="d in detail.dayList"
          :key="d.dayId"
          type="button"
          class="toc-pill"
          :class="{ 'is-active': activeTocDay === d.dayNo, 'is-open': openDayNo === d.dayNo }"
          @click="jumpToDay(d.dayNo)"
        >
          D{{ String(d.dayNo).padStart(2, '0') }}
        </button>
      </nav>
      <section class="day-list">
        <div
          v-for="d in detail.dayList"
          :id="`day-block-${d.dayNo}`"
          :key="d.dayId"
          :ref="(el) => setDayBlockRef(el, d.dayNo)"
          class="day-block"
        >
          <DayListCard
            :day="d"
            :expanded="d.dayNo === openDayNo"
            :highlight-id="highlightId"
            :stream-state="streamState"
            @toggle="onDayToggle"
            @item-drop="onItemDrop"
            @item-select="onItemSelect"
          />
        </div>
      </section>
    </div>

    <DiscoverPool v-if="detail" />

    <footer class="handbook-footer">
      <button type="button" class="back-top" @click="onBackTop">回到顶部</button>
    </footer>

    <ExportBar ref="exportBarRef" :stream-connected="streamConnected" :stream-on="stream.on" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import TripCoverHeader from '../components/TripCoverHeader.vue'
import BudgetStrip from '../components/trip/BudgetStrip.vue'
import DayListCard from '../components/trip/DayListCard.vue'
import ChatEditPanel from '../components/trip/ChatEditPanel.vue'
import DiscoverPool from '../components/trip/DiscoverPool.vue'
import ExportBar from '../components/trip/ExportBar.vue'
import ButlerNoteCard from '../components/trip/ButlerNoteCard.vue'
import HeadStatusPanel from '../components/trip/HeadStatusPanel.vue'
import { storeToRefs } from 'pinia'
import { getItineraryDetail } from '../api/itinerary'
import { useItineraryStore } from '../store/itinerary'
import { useItineraryActions } from '../composables/useItineraryActions'
import { useItineraryStream, type ItineraryStreamEvent } from '../composables/useItineraryStream'
import type { DayPlan, TripItem } from '../types/itinerary'

// 行程详情编排壳（M4-②a §5.4）：只做组合、路由参数、loadDetail/reconcile/SSE 生命周期
// 编排；页面区块分别由 components/trip/ 下的子组件承载。
const route = useRoute()
const store = useItineraryStore()
const actions = useItineraryActions()
const loading = ref(false)
// 详情加载失败态（不存在/无权限/网络异常）：el-empty 错误页替代空白页
const loadError = ref(false)
const loadErrorDescription = ref('行程加载失败')
// detail 为行程全量单一数据源（M4-①）；酒店选择持久化观察收敛在壳内（读写均经 store 单点）
const { detail, streamState, hotelSelections } = storeToRefs(store)
const openDayNo = ref<number | null>(null)
const highlightId = ref<number | null>(null)
const doneDays = computed(
  () => (detail.value?.dayList || []).filter((d) => (d.items || []).length > 0).length,
)

async function loadDetail() {
  loading.value = true
  loadError.value = false
  try {
    const res = await getItineraryDetail(route.params.id as string)
    // 行程详情落 store 单一数据源；对话/草稿/酒店选择由 ChatEditPanel 随 itineraryId 自行装载
    store.setDetail(res.data)
    openDayNo.value = detail.value?.dayList[0]?.dayNo ?? 1
  } catch (err) {
    // 拦截器已 toast 具体原因；页面本身给出可操作的错误态（不存在/无权限/网络异常）
    const message = err instanceof Error ? err.message : ''
    loadErrorDescription.value =
      message || '行程不存在、无权访问或加载失败，请返回重试'
    loadError.value = true
  } finally {
    loading.value = false
  }
}

let timer = 0
let pollFailures = 0

function startPolling() {
  stopPolling()
  pollFailures = 0
  timer = window.setInterval(async () => {
    try {
      const res = await getItineraryDetail(route.params.id as string)
      pollFailures = 0
      store.setDetail(res.data)
      if (detail.value && detail.value.status !== 1) {
        stopPolling()
        ElMessage[detail.value.status === 2 ? 'success' : 'warning'](
          detail.value.status === 2 ? '行程生成完成' : '生成失败',
        )
      }
    } catch {
      // 持续失败（网络断/服务挂）时不能每 2.5s 无限重试：连续 5 次失败停止轮询并提示，
      // 用户刷新页面可恢复。
      pollFailures += 1
      if (pollFailures >= 5) {
        stopPolling()
        ElMessage.warning('无法获取行程进度，请检查网络后刷新页面')
      }
    }
  }, 2500)
}

function stopPolling() {
  if (timer) {
    window.clearInterval(timer)
    timer = 0
  }
}

// ---------------- SSE 事件主路径：轮询仅作降级兜底 ----------------

const stream = useItineraryStream()
const { connected: streamConnected } = stream
const exportBarRef = ref<InstanceType<typeof ExportBar> | null>(null)

/** 增量刷新：只更新行程详情，不动对话/草稿/酒店选择等面板本地状态（区别于 loadDetail）。 */
const refreshDetailOnly = async () => {
  if (!route.params.id) return
  try {
    await store.detail$(route.params.id as string)
  } catch {
    // 偶发刷新失败可忽略：下一天事件/轮询兜底会再刷
  }
}

async function reconcileAfterReconnect() {
  // 断线重连不回放 missed 事件（协议 §4.3.4）：全量对账一次，若期间已终态则收尾
  await loadDetail()
  if (detail.value && detail.value.status !== 1) {
    stream.close()
    ElMessage[detail.value.status === 2 ? 'success' : 'warning'](
      detail.value.status === 2 ? '行程生成完成' : '生成失败',
    )
  }
}

function notifyGenerationFinished(status?: number) {
  ElMessage[status === 2 ? 'success' : 'warning'](status === 2 ? '行程生成完成' : '生成失败')
}

// 事件处理器在 setup 期注册一次（composable 的注册表跨 open 复用）。
stream.on('day_done', () => refreshDetailOnly())
stream.on('butler_note', () => refreshDetailOnly())
stream.on('degraded', (event: ItineraryStreamEvent) => {
  // 原则 4：降级如实可见，不静默
  const data = event.data as { scope?: string; reason?: string } | undefined
  ElMessage.warning(`部分内容已降级（${data?.scope ?? '未知环节'}）：${data?.reason ?? '将简化交付'}`)
})
stream.on('complete', (event: ItineraryStreamEvent) => {
  const data = event.data as { status?: string; degradedDays?: number[] } | undefined
  stream.close()
  loadDetail().then(() => {
    if (data?.status === 'PARTIAL') {
      ElMessage.warning(`行程生成完成，但第 ${((data.degradedDays ?? []) as number[]).join('、') || '?'} 天未成功，可稍后重试`)
    } else {
      notifyGenerationFinished(detail.value?.status)
    }
  })
})
stream.on('error', () => {
  // 不可恢复错误：对账一次，若仍在生成就回退轮询兜底
  stream.close()
  loadDetail().then(() => {
    if (detail.value?.status === 1) startPolling()
    else notifyGenerationFinished(detail.value?.status)
  })
})

/** 生成进度主入口：优先 SSE，连续失败自动降级 startPolling（composable 内触发）。 */
function startGenerationProgress() {
  if (detail.value?.status !== 1) return
  stream.open(route.params.id as string, {
    onFallback: startPolling,
    onReconcile: reconcileAfterReconnect,
  })
}

/** §5.3.5 error(retryable) 重试：重新 loadDetail 对账 + 重建事件流（stream.open 内部会 resetStream）。 */
async function onStreamRetry() {
  await loadDetail()
  startGenerationProgress()
}

// ---------- 迷你目录（粘性 scrollspy）：顶替被删地图的方位感职责 ----------

const activeTocDay = ref<number | null>(null)
const dayBlockEls = new Map<number, HTMLElement>()
let tocObserver: IntersectionObserver | null = null

function setDayBlockRef(el: unknown, dayNo: number) {
  if (el instanceof HTMLElement) {
    el.dataset.dayNo = String(dayNo)
    dayBlockEls.set(dayNo, el)
  } else {
    dayBlockEls.delete(dayNo)
  }
}

/** 滚动联动高亮：取视口上部最近的一个天块（不自动滚页，避免与用户滚动打架） */
function setupTocObserver() {
  tocObserver?.disconnect()
  if (!detail.value?.dayList.length || typeof IntersectionObserver === 'undefined') return
  tocObserver = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((e) => e.isIntersecting)
        .map((e) => ({ no: Number((e.target as HTMLElement).dataset.dayNo), top: e.boundingClientRect.top }))
        .filter((e) => !Number.isNaN(e.no))
        .sort((a, b) => a.top - b.top)
      if (visible.length) activeTocDay.value = visible[0].no
    },
    { rootMargin: '-15% 0px -60% 0px', threshold: 0 },
  )
  dayBlockEls.forEach((el) => tocObserver!.observe(el))
}

watch(
  () => (detail.value?.dayList || []).map((d) => d.dayId).join(','),
  () => nextTick(setupTocObserver),
  { immediate: true },
)

function scrollToEl(el: HTMLElement | null, block: ScrollLogicalPosition = 'start') {
  if (!el) return
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  el.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block })
}

function jumpToDay(dayNo: number) {
  openDayNo.value = dayNo
  scrollToEl(dayBlockEls.get(dayNo) ?? null)
}

function onDayToggle(dayNo: number) {
  // 手风琴：展开态由 openDayNo 单一受控，避免多天同时展开
  openDayNo.value = openDayNo.value === dayNo ? null : dayNo
}

function onItemSelect(item: TripItem) {
  highlightId.value = item.id ?? null
}

function onItemDrop(day: DayPlan) {
  const itemIds = day.items.map((it) => it.id).filter((id): id is number => id != null)
  // 拖拽/键盘排序为乐观本地变更（DayListCard 直接改 store 内 items）：
  // actions 快照兜底，失败自动回滚顺序
  void actions.reorderItems(detail.value!.id, day.dayId, itemIds)
}

// ---------- 导出（逻辑在 ExportBar，按钮在 TripCoverHeader） ----------

function onExportPdf() {
  void exportBarRef.value?.exportPdf()
}

function onExportImage() {
  void exportBarRef.value?.exportImage()
}

function onBackTop() {
  const main = document.querySelector('.el-main')
  if (main) main.scrollTo({ top: 0, behavior: 'smooth' })
  else window.scrollTo({ top: 0, behavior: 'smooth' })
}

// 酒店选择变更（含 ChatEditPanel 内的写入）统一经此单点落 localStorage
watch(hotelSelections, (value) => {
  store.persistHotelSelections(String(route.params.id), value)
}, { deep: true })

onMounted(async () => {
  await loadDetail()
  startGenerationProgress()
})

// 浏览器前进/后退在同一路由 /trips/:id 间切换时组件被复用：监听 id 变化重载并重接事件流。
watch(
  () => route.params.id,
  async (id, prev) => {
    if (!id || id === prev) return
    stopPolling()
    stream.close()
    await loadDetail()
    startGenerationProgress()
  },
)

onUnmounted(() => {
  stopPolling()
  stream.close()
  tocObserver?.disconnect()
})
</script>

<style scoped>
.trip-detail { margin: 0 auto; }

/* ---------- 阅读进度条（el-main 命名滚动时间轴驱动） ---------- */
.reading-progress { position: fixed; top: 0; left: 0; width: 100%; height: 3px; z-index: 2000; pointer-events: none; }

@supports (animation-timeline: scroll()) {
  .reading-progress {
    background: linear-gradient(90deg, var(--lp-accent), var(--lp-accent-warm));
    transform-origin: 0 50%;
    transform: scaleX(0);
    animation: lp-reading-grow linear both;
    animation-timeline: --lp-page-scroll;
  }
}

@keyframes lp-reading-grow { to { transform: scaleX(1); } }

.head { margin-bottom: 16px; }

/* ---------- 加载失败错误态 ---------- */
.load-error { margin-bottom: 16px; }
.load-error-actions { display: flex; justify-content: center; gap: 4px; flex-wrap: wrap; }

/* ---------- §5.3.1 主题叙事条：trip_theme 衬线大字 + --lp-theme-accent 底线 ---------- */
.theme-bar {
  position: relative;
  margin: 0 0 16px;
  padding: 16px 2px 14px;
}

.theme-bar::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  background-image: var(--lp-theme-accent);
  border-radius: 2px;
}

.theme-title {
  margin: 0;
  font-family: var(--lp-font-display);
  font-weight: 500;
  font-size: clamp(20px, 2.6vw, 28px);
  line-height: 1.3;
  letter-spacing: -0.01em;
  color: var(--lp-ink);
}

/* 意图回显行：「系统听懂了什么」首屏即见；后端暂不回传，空态自动隐藏 */
.theme-intent {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--lp-muted);
}

/* ---------- 手册白底大区：粘性迷你目录 + 逐日轨道全宽 ---------- */
.handbook-body {
  background: #fff; border-radius: 16px; padding: 8px 32px 28px; margin-bottom: 16px;
}

@media (max-width: 1024px) {
  .handbook-body { padding: 8px 16px 24px; }
}

/* ---------- 迷你目录：粘性 scrollspy，D01-D0N 药丸 ---------- */
.day-toc {
  position: sticky;
  top: -8px; /* 抵消 .handbook-body 顶部 padding，吸住滚动视口上缘 */
  z-index: 30;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 -32px;
  padding: 10px 32px;
  background: rgb(255 255 255 / 94%);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--lp-rule);
  overflow-x: auto;
  scrollbar-width: none;
}

.day-toc::-webkit-scrollbar {
  display: none;
}

.toc-pill {
  flex: none;
  min-width: 52px;
  padding: 5px 12px;
  border: 1px solid var(--lp-border);
  border-radius: 999px;
  background: #fff;
  font-family: var(--lp-font-data);
  font-size: 12px;
  font-weight: 600;
  color: var(--lp-muted);
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
}

.toc-pill:hover {
  color: var(--lp-accent);
  border-color: var(--lp-accent);
}

.toc-pill.is-active {
  background: var(--lp-accent);
  border-color: var(--lp-accent);
  color: #fff;
}

/* 已展开但非当前视口的天：浅青绿底提示状态 */
.toc-pill.is-open:not(.is-active) {
  background: var(--lp-accent-soft);
  border-color: var(--lp-accent-soft);
  color: var(--lp-accent-hover);
}

.day-block {
  scroll-margin-top: 72px; /* 目录跳转时留出粘性目录高度 */
}

/* ---------- 回到顶部 ---------- */
.handbook-footer { text-align: center; padding: 8px 0 28px; }
.back-top {
  background: none; border: none; cursor: pointer; font-family: var(--lp-font-display);
  font-style: italic; font-size: 14px; color: var(--lp-ink-soft); text-decoration: underline;
  text-underline-offset: 4px;
}
.back-top:hover { color: var(--lp-accent-warm); }
</style>

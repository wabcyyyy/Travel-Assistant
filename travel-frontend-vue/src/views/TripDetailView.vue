<template>
  <div class="trip-detail" v-loading="loading">
    <div class="reading-progress" aria-hidden="true"></div>

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

    <div v-if="detail" class="handbook-body">
      <section class="day-list">
        <DayListCard
          v-for="d in detail.dayList"
          :key="d.dayId"
          :day="d"
          :expanded="d.dayNo === openDayNo"
          :highlight-id="highlightId"
          :stream-state="streamState"
          @toggle="onDayToggle"
          @item-drop="onItemDrop"
          @item-select="onItemSelect"
        />
      </section>

      <div class="side-col">
        <el-card shadow="never" class="map-card">
          <div class="map-toolbar">
            <span class="toolbar-title">当日路线</span>
            <el-tag v-if="!mapReady" type="warning" size="small">未配置地图 key，地图不可用</el-tag>
            <el-tag v-else-if="detailForeign && !mapHasCoords" type="info" size="small">海外目的地暂无坐标，地图已隐藏</el-tag>
          </div>
          <div v-if="detailForeign && !mapHasCoords" class="map-empty">
            <p class="map-empty-title">海外地图未启用</p>
            <p class="map-empty-desc">
              行程点位仍可浏览与编辑。配置服务端
              <code>GOOGLE_MAPS_API_KEY</code> 后可自动落海外坐标并恢复地图。
            </p>
          </div>
          <TripMap v-else class="map" :items="mapItems" :city="detail?.city" :highlight-id="highlightId" :route-day="routeDay" @select="onMapSelect" />
        </el-card>

        <el-card shadow="never" class="budget-card">
          <BudgetPanel
            :budget-list="detail.budgetList"
            :total-amount="detail.totalAmount"
            :budget-limit="detail.budget"
            :persons="detail.persons"
            :day-list="detail.dayList"
          />
        </el-card>
      </div>
    </div>

    <DiscoverPool v-if="detail" />

    <footer class="handbook-footer">
      <button type="button" class="back-top" @click="onBackTop">回到顶部</button>
    </footer>

    <ExportBar ref="exportBarRef" :stream-connected="streamConnected" :stream-on="stream.on" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import TripMap, { type MapItem } from '../components/TripMap.vue'
import TripCoverHeader from '../components/TripCoverHeader.vue'
import BudgetPanel from '../components/BudgetPanel.vue'
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
import { isForeignCity } from '../utils/geo'

// 行程详情编排壳（M4-②a §5.4）：只做组合、路由参数、loadDetail/reconcile/SSE 生命周期
// 与地图联动编排；页面区块分别由 components/trip/ 下的子组件承载。
const route = useRoute()
const store = useItineraryStore()
const actions = useItineraryActions()
const loading = ref(false)
// detail 为行程全量单一数据源（M4-①）；酒店选择持久化观察收敛在壳内（读写均经 store 单点）
const { detail, streamState, hotelSelections } = storeToRefs(store)
const openDayNo = ref<number | null>(null)
const routeDay = ref(1)
const highlightId = ref<number | null>(null)
const amapReady = ref(!!import.meta.env.VITE_AMAP_JS_KEY)
// 国外目的地：有坐标才渲染 Leaflet+OSM；无坐标时隐藏地图（避免空图误导）。
const detailForeign = computed(() => isForeignCity(detail.value?.city ?? ''))
const mapReady = computed(() => amapReady.value || detailForeign.value)
const mapHasCoords = computed(() =>
  (mapItems.value || []).some((it) => it.latitude != null && it.longitude != null),
)
const doneDays = computed(
  () => (detail.value?.dayList || []).filter((d) => (d.items || []).length > 0).length,
)
const activeDay = computed(
  () => detail.value?.dayList.find((d) => d.dayNo === routeDay.value) ?? detail.value?.dayList[0],
)
const mapItems = computed<MapItem[]>(() => {
  if (!detail.value) return []
  return (activeDay.value ? [activeDay.value] : detail.value.dayList).flatMap((day) =>
    day.items.map((it) => ({ ...it, dayNo: day.dayNo }))
  )
})

async function loadDetail() {
  loading.value = true
  try {
    const res = await getItineraryDetail(route.params.id as string)
    // 行程详情落 store 单一数据源；对话/草稿/酒店选择由 ChatEditPanel 随 itineraryId 自行装载
    store.setDetail(res.data)
    openDayNo.value = detail.value?.dayList[0]?.dayNo ?? 1
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

// ---------- 地图联动编排：日卡点选 ↔ 地图高亮 ----------

function onDayToggle(dayNo: number) {
  // 手风琴：展开态由 openDayNo 单一受控，避免多天同时展开；同时驱动当日路线
  openDayNo.value = openDayNo.value === dayNo ? null : dayNo
  routeDay.value = dayNo
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

function onMapSelect(id: number | null) {
  highlightId.value = id
  if (id != null) {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    document.getElementById(`item-${id}`)?.scrollIntoView({
      behavior: reduceMotion ? 'auto' : 'smooth',
      block: 'center',
    })
  }
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

/* ---------- 手册白底大区：左逐日轨道 + 右当日地图/预算 ---------- */
.handbook-body {
  display: grid; grid-template-columns: minmax(0, 1fr) 440px; gap: 24px; align-items: start;
  background: #fff; border-radius: 16px; padding: 8px 32px 28px; margin-bottom: 16px;
}

.side-col { display: flex; flex-direction: column; gap: 16px; min-width: 0; }

@media (max-width: 1024px) {
  .handbook-body { grid-template-columns: 1fr; padding: 8px 16px 24px; }
}

/* ---------- 地图 / 预算 ---------- */
.map-card { margin-bottom: 0; }
.map-toolbar { display: flex; align-items: center; margin-bottom: 8px; }
.toolbar-title { margin-right: 12px; font-weight: 700; }
.map { height: 460px; }

.map-empty {
  display: flex; flex-direction: column; align-items: flex-start; justify-content: center;
  gap: 8px; min-height: 180px; padding: 20px 18px; border-radius: 12px;
  background: var(--lp-sand); border: 1px dashed var(--lp-border);
}
.map-empty-title { margin: 0; font-weight: 700; color: var(--lp-ink); font-size: 14px; }
.map-empty-desc { margin: 0; font-size: 12.5px; line-height: 1.7; color: var(--lp-muted); }
.map-empty-desc code {
  padding: 1px 5px; border-radius: 4px; background: rgb(0 0 0 / 6%);
  font-family: var(--lp-font-data); font-size: 12px;
}
.budget-card { margin-bottom: 0; }

/* ---------- 回到顶部 ---------- */
.handbook-footer { text-align: center; padding: 8px 0 28px; }
.back-top {
  background: none; border: none; cursor: pointer; font-family: var(--lp-font-display);
  font-style: italic; font-size: 14px; color: var(--lp-ink-soft); text-decoration: underline;
  text-underline-offset: 4px;
}
.back-top:hover { color: var(--lp-accent-warm); }
</style>

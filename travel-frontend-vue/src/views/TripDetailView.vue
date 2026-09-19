<template>
  <div class="trip-detail" v-loading="loading">
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

    <!-- 「管家说」细条（v2.6 §19.3；v2.7 §20 R1 压缩为 h40，桌面端固定在导航之下） -->
    <ButlerStrip
      v-if="detail"
      class="butler-slot"
      :detail="detail"
      :done-days="doneDays"
      :stream-state="streamState"
      :can-edit="canEdit"
      @retry="onStreamRetry"
      @chat="chatVisible = true"
      @versions="versionVisible = true"
    />

    <!-- 离线快照条幅（C2.5）：内容来自本地快照时必须明示，编辑入口维持隐藏 -->
    <div v-if="detail && offlineSnapshotAt" class="offline-banner" role="status">
      离线快照 · 保存于 {{ offlineSnapshotAt }} —— 当前为只读视图，联网后自动加载最新内容
    </div>

    <!-- 三栏工作台（v2.6 §19.3；v2.7 §20 R1 视口固定 + 面板独立滚动）：
         左行程 / 中地图 / 右发现；面板宽 340/300 可拖可收（R2，TREK 语义）。
         ≥768 走视口固定布局（.workbench 内铺开），<768 保持移动壳单列分段 -->
    <div
      v-if="detail"
      ref="workbenchEl"
      class="workbench3"
      :style="corridorVars"
    >
      <Segmented
        v-if="!isDesktop"
        v-model="mobilePane"
        class="pane-switch"
        :items="PANE_ITEMS"
        aria-label="工作台视图"
      />

      <!-- 左栏：行程（标题/操作条 + 日目录 + 日卡滚动区 + 预算停靠） -->
      <div v-show="isDesktop || mobilePane === 'trip'" class="panel-slot slot-left">
        <button
          type="button"
          class="panel-ear ear-left"
          :class="{ 'is-collapsed': leftHidden }"
          :aria-label="leftHidden ? '展开行程栏' : '收起行程栏'"
          :title="leftHidden ? '展开行程栏' : '收起行程栏'"
          @click="toggleLeft"
        >
          <PanelLeftOpen v-if="leftHidden" :size="16" />
          <PanelLeftClose v-else :size="16" />
        </button>
        <section class="panel" :style="{ '--lp-panel-w': leftHidden ? '0px' : `${leftWidth}px` }">
          <header class="panel-head">
            <button type="button" class="head-back" aria-label="返回" title="返回" @click="router.back()">
              <ChevronLeft :size="16" />
            </button>
            <div class="head-text" :title="detail.intent || undefined">
              <span class="head-title">{{ detail.title }}</span>
              <span class="head-meta">
                {{ detail.tripTheme || detail.city }} · {{ detail.days }} 天 {{ detail.stayNights }} 晚 ·
                {{ detail.persons }} 人<template v-if="detail.startDate"> · {{ detail.startDate }} ~ {{ detail.endDate }}</template>
              </span>
            </div>
            <AppMenu :items="headMenuItems" trigger-label="行程操作" @select="onHeadMenu" />
          </header>

          <nav class="day-toc" aria-label="每日目录">
            <button
              v-for="d in detail.dayList"
              :key="d.dayId"
              type="button"
              class="toc-pill"
              :style="{ '--chip-color': `var(--lp-day-${((d.dayNo - 1) % 8) + 1})` }"
              :class="{ 'is-active': activeTocDay === d.dayNo }"
              @click="jumpToDay(d.dayNo)"
            >
              D{{ String(d.dayNo).padStart(2, '0') }}
            </button>
          </nav>

          <div class="panel-scroll">
            <div class="day-list">
              <div
                v-for="d in detail.dayList"
                :id="`day-block-${d.dayNo}`"
                :key="d.dayId"
                :ref="(el) => setDayBlockRef(el, d.dayNo)"
                class="day-block"
              >
                <DayListCard
                  :day="d"
                  :collapsed="collapsedDays.includes(d.dayNo)"
                  :highlight-id="highlightId"
                  :stream-state="streamState"
                  :selected-ids="selectedIds"
                  :read-only="!canEdit"
                  @toggle="onDayToggle"
                  @item-drop="onItemDrop"
                  @item-select="onItemSelect"
                  @move-request="onMoveRequest"
                  @edit-request="onEditRequest"
                  @toggle-select="onToggleSelect"
                  @add-request="onAddRequest"
                  @discover-drop="onDiscoverDrop"
                  @item-moved="onCrossDayMove"
                />
              </div>
            </div>
          </div>

          <button v-if="canEdit" type="button" class="expense-entry" @click="expensesVisible = true">实际花费 · 记账</button>
          <!-- 预算条停靠左栏底部（v2.6 §19.3）：docked = 总价一行 + 明细弹层 -->
          <BudgetStrip
            class="budget-dock"
            docked
            :budget-list="detail.budgetList"
            :total-amount="detail.totalAmount"
            :budget-limit="detail.budget"
            :persons="detail.persons"
            :days="detail.dayList.length"
          />

          <div
            v-if="!leftHidden && !narrow"
            class="panel-resize"
            role="presentation"
            aria-hidden="true"
            @mousedown="startResizeLeft"
          ></div>
        </section>
      </div>

      <!-- 地图（工作台铺底，面板浮于其上；窄屏仍是单列里的一段） -->
      <div v-show="isDesktop || mobilePane === 'map'" class="map-stage">
        <TripMapPanel
          :days="detail.dayList"
          :active-item-id="highlightId"
          @select="onSelectFromMap"
          @clear="highlightId = null"
        />
        <!-- 贴底浮层详情卡（v2.6 §19.3）：选中站点/图钉即出；X/Esc/点地图空白关闭 -->
        <PlaceDetailSheet
          v-if="activeItem"
          :item="activeItem"
          @close="highlightId = null"
          @edit="onEditRequest"
          @move="onMoveRequest"
          @delete="onItemDelete"
        />
      </div>

      <!-- 右栏：发现（搜索加点 + 全部/未排/已排 + 分类） -->
      <div v-show="isDesktop || mobilePane === 'discover'" class="panel-slot slot-right">
        <button
          type="button"
          class="panel-ear ear-right"
          :class="{ 'is-collapsed': rightHidden }"
          :aria-label="rightHidden ? '展开发现栏' : '收起发现栏'"
          :title="rightHidden ? '展开发现栏' : '收起发现栏'"
          @click="toggleRight"
        >
          <PanelRightOpen v-if="rightHidden" :size="16" />
          <PanelRightClose v-else :size="16" />
        </button>
        <section class="panel panel-right" :style="{ '--lp-panel-w': rightHidden ? '0px' : `${rightWidth}px` }">
          <div class="panel-fill">
            <DiscoverPanel
              :preset-day-id="presetDiscoverDayId"
              @select="onPanelItemSelect"
              @clear-preset="presetDiscoverDayId = null"
            />
          </div>
          <div
            v-if="!rightHidden && !narrow"
            class="panel-resize is-left"
            role="presentation"
            aria-hidden="true"
            @mousedown="startResizeRight"
          ></div>
        </section>
      </div>
    </div>

    <!-- 跨天移动的目标日选择（S4）：行菜单/键盘路径与拖拽走同一条 API；v2.6 起对话框自研 -->
    <AppDialog
      v-model="moveDialogVisible"
      title="移动到其他天"
      width="min(380px, calc(100vw - 32px))"
    >
      <p v-if="moveTarget" class="move-hint">
        「{{ moveTarget.poiName }}」当前在第 {{ currentDayNo }} 天
      </p>
      <div class="move-day-grid">
        <el-button
          v-for="d in otherDays"
          :key="d.dayId"
          :disabled="moving"
          @click="confirmMove(d.dayId)"
        >
          第 {{ d.dayNo }} 天<template v-if="d.travelDate"> · {{ d.travelDate }}</template>
        </el-button>
      </div>
      <p v-if="moveTarget && !otherDays.length" class="move-hint">没有其他可移动的天</p>
    </AppDialog>

    <!-- S1/S2 弹窗与 A5 抽屉（挂载点收在壳里，逻辑各自内聚） -->
    <CoverDialog
      v-if="detail"
      v-model:visible="coverVisible"
      :itinerary-id="detail.id"
      :default-query="detail.city"
      @updated="onCoverUpdated"
    />
    <!-- 更多字段编辑（v2.6 W2）：对话框收在壳层，行内「编辑」与详情卡「编辑」共用 -->
    <ItemEditDialog v-if="detail" v-model:visible="editVisible" :item="editTarget" />
    <ShareDialog v-if="detail" v-model:visible="shareVisible" :itinerary-id="detail.id" />
    <VersionHistoryDrawer
      v-if="detail"
      v-model:visible="versionVisible"
      :itinerary-id="detail.id"
      @restored="onVersionRestored"
    />

    <!-- 选择态批量条（v2.6 §19.3）：勾选 ≥1 项时底部浮出；viewer 无批量写入口 -->
    <SelectionBar v-if="canEdit" :selected-ids="selectedIds" @clear="selectedIds = []" />

    <AppSheet v-if="detail" v-model="expensesVisible" direction="rtl" size="460px" title="实际花费">
      <ExpensePanel
        v-if="expensesVisible"
        :detail="detail"
        :read-only="!canEdit"
        @select-item="(id) => { highlightId = id; expensesVisible = false }"
      />
    </AppSheet>

    <!-- AI 对话抽屉：ChatEditPanel 自页头卡片收编而来（v2.6 §19.3）；viewer 无写入口 -->
    <AppSheet v-if="detail && canEdit" v-model="chatVisible" direction="rtl" size="460px" title="AI 管家 · 智能修改">
      <ChatEditPanel :itinerary-id="detail.id" @apply-draft="loadDetail" />
    </AppSheet>

    <!-- 协作（C2.3）：成员/邀请管理抽屉 -->
    <AppSheet v-if="detail" v-model="collabVisible" direction="rtl" size="420px" title="协作成员">
      <CollabPanel v-if="collabVisible" :itinerary-id="detail.id" :is-owner="myRole === 'owner'" />
    </AppSheet>

    <!-- 模板（C2.4）：发布前预览脱敏投影，确认发布/下架 -->
    <TemplatePublishDialog
      v-if="detail"
      v-model:visible="templateVisible"
      :itinerary-id="detail.id"
      :published="templatePublished"
      @changed="loadDetail"
    />

    <ExportBar ref="exportBarRef" :stream-connected="streamConnected" :stream-on="stream.on" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ChevronLeft,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
} from 'lucide-vue-next'

import BudgetStrip from '../components/trip/BudgetStrip.vue'
import ExpensePanel from '../components/trip/ExpensePanel.vue'
import CollabPanel from '../components/trip/CollabPanel.vue'
import TemplatePublishDialog from '../components/trip/TemplatePublishDialog.vue'
const expensesVisible = ref(false)
import ButlerStrip from '../components/trip/ButlerStrip.vue'
import DayListCard from '../components/trip/DayListCard.vue'
import ChatEditPanel from '../components/trip/ChatEditPanel.vue'
import DiscoverPanel from '../components/trip/DiscoverPanel.vue'
import ExportBar from '../components/trip/ExportBar.vue'
import CoverDialog from '../components/trip/CoverDialog.vue'
import ItemEditDialog from '../components/trip/ItemEditDialog.vue'
import PlaceDetailSheet from '../components/trip/PlaceDetailSheet.vue'
import SelectionBar from '../components/trip/SelectionBar.vue'
import ShareDialog from '../components/trip/ShareDialog.vue'
import TripMapPanel from '../components/trip/TripMapPanel.vue'
import VersionHistoryDrawer from '../components/trip/VersionHistoryDrawer.vue'
import AppDialog from '../components/ui/AppDialog.vue'
import AppMenu from '../components/ui/AppMenu.vue'
import AppSheet from '../components/ui/AppSheet.vue'
import Segmented from '../components/ui/Segmented.vue'
import { confirmDialog } from '../components/ui/confirm'
import { toast } from '../components/ui/toast'
import { useMediaQuery } from '../composables/useMediaQuery'
import { useDiscoverAdd } from '../composables/useDiscoverAdd'
import { useResizablePanels } from '../composables/useResizablePanels'
import { storeToRefs } from 'pinia'
import { getItineraryDetail } from '../api/itinerary'
import { deleteSnapshot, loadSnapshot, saveDetailSnapshot, snapshotKeyForDetail } from '../utils/offlineSnapshots'
import { useUserStore } from '../store/user'
import { useItineraryStore } from '../store/itinerary'
import { useItineraryActions } from '../composables/useItineraryActions'
import { useItineraryStream, type ItineraryStreamEvent } from '../composables/useItineraryStream'
import type { DayPlan, ItineraryDetail, TripItem } from '../types/itinerary'
import type { Suggestion } from '../types/generated/contracts'
import type { LocalPoi } from '../api/pois'

// 行程详情编排壳（M4-②a §5.4；v2.6 §19.3 三栏重排）：
// 只做组合、路由参数、loadDetail/reconcile/SSE 生命周期；页面区块分别由 components/trip/ 承载。
const route = useRoute()
const router = useRouter()
const store = useItineraryStore()
const actions = useItineraryActions()
const loading = ref(false)
// 详情加载失败态（不存在/无权限/网络异常）：el-empty 错误页替代空白页
const loadError = ref(false)
const loadErrorDescription = ref('行程加载失败')
// detail 为行程全量单一数据源（M4-①）；酒店选择持久化观察收敛在壳内（读写均经 store 单点）
const { detail, streamState, hotelSelections } = storeToRefs(store)
// 天平铺（v2.6 §19.3）：日卡默认全展开，collapsedDays 只记录被单天折叠的 D
const collapsedDays = ref<number[]>([])
const highlightId = ref<number | null>(null)
const coverVisible = ref(false)
const shareVisible = ref(false)
const versionVisible = ref(false)
// 协作（C2.3）/模板（C2.4）：详情 VO 带 myRole；viewer 只读，owner 管协作与发布
const myRole = computed<'owner' | 'editor' | 'viewer'>(() => detail.value?.myRole ?? 'owner')
const canEdit = computed(() => myRole.value !== 'viewer')
const collabVisible = ref(false)
const templateVisible = ref(false)
const templatePublished = computed(() => Boolean(detail.value?.templatePublishedAt))
// 离线快照（C2.5）：非空 = 当前内容来自本地快照（断网回退），条幅明示保存时间
const offlineSnapshotAt = ref<string | null>(null)
const userStore = useUserStore()
const doneDays = computed(
  () => (detail.value?.dayList || []).filter((d) => (d.items || []).length > 0).length,
)

// ---------- 工作台形态（v2.7 §20 R1）：≥768 视口固定三面（面板可拖可收）；<768 移动壳单列分段 ----------
const isDesktop = useMediaQuery('(min-width: 768px)')
const PANE_ITEMS = [
  { value: 'trip', label: '行程' },
  { value: 'map', label: '地图' },
  { value: 'discover', label: '发现' },
]
const mobilePane = ref('trip')
const chatVisible = ref(false)

// 两栏宽度/折叠/拖拽（R2，TREK useResizablePanels 语义）；narrow = 双栏同屏放不下（单栏档）
const workbenchEl = ref<HTMLElement | null>(null)
const {
  leftWidth,
  rightWidth,
  leftHidden,
  rightHidden,
  toggleLeft,
  toggleRight,
  narrow,
  startResizeLeft,
  startResizeRight,
} = useResizablePanels(workbenchEl)

// 走廊在命令行里=地图可见区；地图控件/详情卡/署名都按它定位（面板收起即回 0）
const corridorVars = computed(() => ({
  '--lp-corridor-left': `${leftHidden.value ? 0 : leftWidth.value + 10}px`,
  '--lp-corridor-right': `${rightHidden.value ? 0 : rightWidth.value + 10}px`,
}))

// 行程操作（自封面 Hero 收编，v2.7 §20 R1）：面板头条「⋯」菜单
const headMenuItems = computed(() => {
  // 协作（C2.3）/模板（C2.4）：按角色出菜单——cover/share 是 owner 专属语义，
  // 导出/相似行程对协作成员开放；协作成员与发布入口仅 owner 可见
  const items: { key: string; label: string }[] = []
  if (myRole.value === 'owner') {
    items.push({ key: 'cover', label: '换封面' })
    items.push({ key: 'share', label: '分享' })
    items.push({ key: 'collab', label: '协作成员' })
    items.push({ key: 'template', label: templatePublished.value ? '模板 · 下架' : '发布为模板' })
  }
  items.push({ key: 'pdf', label: '导出 PDF' })
  items.push({ key: 'image', label: '导出图片' })
  items.push({ key: 'similar', label: '新建相似行程' })
  return items
})

function onHeadMenu(key: string): void {
  if (key === 'cover') coverVisible.value = true
  else if (key === 'share') shareVisible.value = true
  else if (key === 'collab') collabVisible.value = true
  else if (key === 'template') templateVisible.value = true
  else if (key === 'pdf') onExportPdf()
  else if (key === 'image') onExportImage()
  else if (key === 'similar') router.push('/generate')
}

async function loadDetail() {
  loading.value = true
  loadError.value = false
  try {
    const res = await getItineraryDetail(route.params.id as string)
    // 行程详情落 store 单一数据源；对话/草稿/酒店选择由 ChatEditPanel 随 itineraryId 自行装载
    store.setDetail(res.data)
    collapsedDays.value = []
    offlineSnapshotAt.value = null
    // 离线快照（C2.5）：成功读取的本人详情按账号落盘（写失败静默，不影响线上）
    const username = userStore.username
    if (username) void saveDetailSnapshot(username, res.data.id, res.data)
  } catch (err) {
    // 离线快照回退（C2.5）：断网时回退到本人最近一次成功读取的快照（只读）
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      const username = userStore.username
      const entry = username ? await loadSnapshot(snapshotKeyForDetail(username, String(route.params.id))) : null
      if (entry) {
        store.setDetail(entry.payload as ItineraryDetail)
        offlineSnapshotAt.value = new Date(entry.savedAt).toLocaleString()
        loading.value = false
        return
      }
    } else {
      // 在线但读取失败：404（行程已删）或 401（鉴权失效）——不回退旧快照，就地删除
      const username = userStore.username
      if (username) void deleteSnapshot(snapshotKeyForDetail(username, String(route.params.id)))
    }
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

// ---------- 日内目录（左栏内粘性 scrollspy）：与日卡滚动联动的方位导航 ----------

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
  // 跳转时顺带展开该天（折叠态单一受控于 collapsedDays）
  collapsedDays.value = collapsedDays.value.filter((n) => n !== dayNo)
  scrollToEl(dayBlockEls.get(dayNo) ?? null)
}

function onDayToggle(dayNo: number) {
  // 天平铺：默认全展开、可单天折叠（与旧手风琴的区别只在默认值与互斥性）
  collapsedDays.value = collapsedDays.value.includes(dayNo)
    ? collapsedDays.value.filter((n) => n !== dayNo)
    : [...collapsedDays.value, dayNo]
}

function onItemSelect(item: TripItem) {
  highlightId.value = item.id ?? null
}

/** 地图 → 列表：高亮并滚动到对应行程行（scrollToEl 内部按 reduce 偏好退化瞬时滚动） */
function onSelectFromMap(item: TripItem) {
  highlightId.value = item.id ?? null
  const el = item.id != null ? document.getElementById(`item-${item.id}`) : null
  scrollToEl(el, 'center')
}

/** 发现面板已排卡 → 左栏：先展开可能被折叠的天，再高亮并滚动到对应行 */
function onPanelItemSelect(item: TripItem) {
  highlightId.value = item.id ?? null
  const day = detail.value?.dayList.find((d) => (d.items || []).some((it) => it.id === item.id))
  if (day) collapsedDays.value = collapsedDays.value.filter((n) => n !== day.dayNo)
  void nextTick(() => {
    const el = item.id != null ? document.getElementById(`item-${item.id}`) : null
    scrollToEl(el, 'center')
  })
}

// ---------- 贴底浮层详情卡（v2.6 W2）：选中项解析 + 操作行接线 ----------

/** 当前高亮项（详情卡的单一数据源；从权威 detail 反查，排序变动也跟随） */
const activeItem = computed<TripItem | null>(() => {
  const id = highlightId.value
  if (id == null) return null
  for (const day of detail.value?.dayList ?? []) {
    const hit = (day.items || []).find((it) => it.id === id)
    if (hit) return hit
  }
  return null
})

// 更多字段编辑（ItemEditDialog 自 DayListCard 收编到壳层）
const editVisible = ref(false)
const editTarget = ref<TripItem | null>(null)

function onEditRequest(item: TripItem) {
  editTarget.value = item
  editVisible.value = true
}

async function onItemDelete(item: TripItem) {
  if (item.id == null) return
  const ok = await confirmDialog(`确认删除「${item.poiName}」？`, { title: '删除确认', confirmText: '删除' })
  if (!ok) return
  await actions.deleteItem(item.id)
  toast.success('已删除')
  if (highlightId.value === item.id) highlightId.value = null
}

// ---------- 选择态批量（W2）：勾选集合（批量条自包含操作与清空） ----------
const selectedIds = ref<number[]>([])

function onToggleSelect(item: TripItem) {
  if (item.id == null) return
  selectedIds.value = selectedIds.value.includes(item.id)
    ? selectedIds.value.filter((id) => id !== item.id)
    : [...selectedIds.value, item.id]
}

// ---------- 右栏「发现」联动（W2）：日尾添加预设目标天 / 卡片拖拽入天 ----------
const presetDiscoverDayId = ref<number | null>(null)
const { addSuggestionToDay, addPoiToDay } = useDiscoverAdd()

/** 日尾「添加地点」：打开/唤出发现面板并预设本天（窄屏切段、桌面展开右栏——收起时自动唤出） */
function onAddRequest(dayId: number) {
  presetDiscoverDayId.value = dayId
  if (!isDesktop.value) mobilePane.value = 'discover'
  else if (rightHidden.value) toggleRight()
}

function dayNoOf(dayId: number): number {
  return detail.value?.dayList.find((d) => d.dayId === dayId)?.dayNo ?? 0
}

/** 拖拽入天落库：计划中 → 移动；备选/近邻 → 排入；搜索结果 → 排入（坐标回填在组合式内） */
async function onDiscoverDrop(payload: { dayId: number; entry: unknown }) {
  const data = payload.entry as {
    kind?: string
    itemId?: number
    name?: string
    suggestion?: Suggestion
    poi?: LocalPoi
  } | null
  if (!data || typeof data !== 'object') return
  try {
    if (data.kind === 'planned' && data.itemId != null) {
      await actions.moveToDay(data.itemId, payload.dayId)
      toast.success(`已移动：${data.name ?? '点位'} → 第 ${dayNoOf(payload.dayId)} 天`)
    } else if (data.kind === 'suggestion' && data.suggestion) {
      await addSuggestionToDay(data.suggestion, payload.dayId)
    } else if (data.kind === 'search' && data.poi) {
      await addPoiToDay(data.poi, payload.dayId)
    }
  } catch {
    /* 拦截器已提示；快照回滚由 actions 完成 */
  }
}

// ---------- 跨天移动（S4）：行菜单/键盘路径 + 拖拽跨天，共用 actions.moveToDay ----------

const moveTarget = ref<TripItem | null>(null)
const moveDialogVisible = ref(false)
const moving = ref(false)

const targetDay = computed(() => {
  const target = moveTarget.value
  if (!target || !detail.value) return null
  return (
    detail.value.dayList.find((d) => (d.items || []).some((item) => item.id === target.id)) ?? null
  )
})
const currentDayNo = computed(() => targetDay.value?.dayNo ?? '?')
const otherDays = computed(
  () => (detail.value?.dayList ?? []).filter((d) => d.dayId !== targetDay.value?.dayId),
)

function onMoveRequest(item: TripItem) {
  moveTarget.value = item
  moveDialogVisible.value = true
}

async function confirmMove(dayId: number) {
  const target = moveTarget.value
  if (target?.id == null || moving.value) return
  moving.value = true
  try {
    await actions.moveToDay(target.id, dayId)
    ElMessage.success('已移动')
    moveDialogVisible.value = false
  } catch {
    /* 拦截器已提示；快照回滚由 actions.run 完成 */
  } finally {
    moving.value = false
  }
}

/** 拖拽跨天：vuedraggable 已就地改了两侧数组，成功以权威详情覆盖、失败快照回滚。 */
function onCrossDayMove(payload: { itemId: number; targetDayId: number }) {
  void actions.moveToDay(payload.itemId, payload.targetDayId).catch(() => undefined)
}

/** 封面更新（S1）：接口返回权威详情，直接覆盖 store（列表页会自行重新拉取）。 */
function onCoverUpdated(next: ItineraryDetail) {
  store.setDetail(next)
}

/** 版本恢复（A5）：restore 返回最新详情；提示已在抽屉内给出。 */
function onVersionRestored(next: ItineraryDetail) {
  store.setDetail(next)
}

function onItemDrop(day: DayPlan) {
  const itemIds = day.items.map((it) => it.id).filter((id): id is number => id != null)
  // 拖拽/键盘排序为乐观本地变更（DayListCard 直接改 store 内 items）：
  // actions 快照兜底，失败自动回滚顺序
  void actions.reorderItems(detail.value!.id, day.dayId, itemIds)
}

// ---------- 导出（逻辑在 ExportBar，入口在左栏头条操作菜单） ----------

function onExportPdf() {
  void exportBarRef.value?.exportPdf()
}

function onExportImage() {
  void exportBarRef.value?.exportImage()
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
.trip-detail {
  margin: 0 auto;
}

/* ---------- 离线快照条幅（C2.5）：内容来自本地时必须明示 ---------- */
.offline-banner {
  position: sticky;
  top: 0;
  z-index: var(--lp-z-panel);
  padding: 8px 16px;
  text-align: center;
  font-size: 12px;
  color: var(--lp-text-muted);
  background: var(--lp-accent-soft);
  border-bottom: 1px solid var(--lp-border);
}

/* ---------- 阅读进度条（el-main 命名滚动时间轴驱动） ---------- */
.reading-progress { position: fixed; top: 0; left: 0; width: 100%; height: 3px; z-index: var(--lp-z-panel); pointer-events: none; }

@supports (animation-timeline: scroll()) {
  .reading-progress {
    background: var(--lp-theme-accent);
    transform-origin: 0 50%;
    transform: scaleX(0);
    animation: lp-reading-grow linear both;
    animation-timeline: --lp-page-scroll;
  }
}

@keyframes lp-reading-grow { to { transform: scaleX(1); } }

/* ---------- 加载失败错误态 ---------- */
.load-error { margin-bottom: 16px; }
.load-error-actions { display: flex; justify-content: center; gap: 4px; flex-wrap: wrap; }

/* ---------- 工作台（v2.7 §20 R1）：<768 移动壳单列；≥768 视口固定，面板浮层 ---------- */
.workbench3 {
  display: block;
}

.map-stage {
  position: relative;
}

.panel-slot {
  position: relative;
}

.panel {
  min-width: 0;
}

.panel-right {
  display: flex;
  flex-direction: column;
}

/* 发现面板自带内边距与滚动：面板只负责给一块确定的画布 */
.panel-fill {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* 面板头条：返回 + 标题/元信息 + 操作菜单（封面 Hero 退役后的收编位，v2.7 §20 R1）——
   桌面浮层面板与移动壳卡片共用同一条头部 */
.panel-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
  padding: var(--lp-space-2) var(--lp-space-3);
  border-bottom: 1px solid var(--lp-edge-faint);
}

.head-back {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--lp-radius-xs);
  background: transparent;
  color: var(--lp-text-muted);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.head-back:hover {
  background: var(--lp-surface-hover);
  color: var(--lp-text-1);
}

.head-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}

.head-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--lp-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.head-meta {
  font-size: 10.5px;
  color: var(--lp-text-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---------- 桌面（≥768）视口固定布局：整页不滚，两栏各自滚（TREK 语义） ---------- */
@media (min-width: 768px) {
  /* 管家条细条：全宽顶栏（h64）之下、工作台之上（v2.8 trek 顶栏形态后不再有左导航偏移） */
  .butler-slot {
    position: fixed;
    top: 64px;
    left: 0;
    right: 0;
    z-index: var(--lp-z-bar);
  }

  .workbench3 {
    position: fixed;
    top: 108px;
    left: 0;
    right: 0;
    bottom: 0;
    overflow: hidden;
    overscroll-behavior: contain;
  }

  /* 地图铺底：面板浮在它上面，走廊（corridor）由壳变量给出 */
  .map-stage {
    position: absolute;
    inset: 0;
  }

  .panel-slot {
    position: absolute;
    top: 10px;
    bottom: 10px;
    z-index: var(--lp-z-sticky);
  }

  .slot-left {
    left: 10px;
  }

  .slot-right {
    right: 10px;
  }

  /* 面板本体（TREK 实测材质）：玻璃底 + blur(24) saturate(180) + r16 + 专用影；
     width 过渡即折叠动画（内容 overflow:hidden 不回流） */
  .panel {
    width: var(--lp-panel-w, 340px);
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: var(--lp-panel-bg);
    backdrop-filter: var(--lp-panel-blur);
    -webkit-backdrop-filter: var(--lp-panel-blur);
    border-radius: var(--lp-radius-md);
    box-shadow: var(--lp-panel-shadow);
    transition: width 0.25s ease;
  }

  /* 日目录：面板子头（不吸顶——滚动区在它下面，自己不动）。
     选择器带 .panel 前缀：压过移动壳基类的负外边距（同特异性时后写的基类会赢） */
  .panel .day-toc {
    position: static;
    margin: 0;
    padding: var(--lp-space-2) var(--lp-space-3);
    border-bottom: 1px solid var(--lp-edge-faint);
    background: transparent;
    box-shadow: none;
    backdrop-filter: none;
  }

  /* 面板滚动区：整页不滚，滚的是这里 */
  .panel-scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: var(--lp-space-2) var(--lp-space-3) var(--lp-space-3);
  }

  .panel .budget-dock {
    flex: none;
    margin: 0;
    border-radius: 0;
    border-left: none;
    border-right: none;
    border-bottom: none;
  }
}

.pane-switch {
  justify-self: center;
  margin-bottom: var(--lp-space-2);
}

/* ---------- 日内目录：D01-D0N 药丸（移动壳里在流内，桌面在面板子头） ---------- */
.day-toc {
  z-index: var(--lp-z-sticky);
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 -16px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--lp-edge-faint);
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
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-pill);
  background: var(--lp-surface-card);
  font-family: var(--lp-font-data);
  font-size: 12px;
  font-weight: 600;
  color: var(--lp-muted);
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
}

.toc-pill:hover {
  color: color-mix(in oklch, var(--chip-color) 72%, var(--lp-text-1));
  border-color: color-mix(in oklch, var(--chip-color) 55%, transparent);
}

/* 选中态走 day-tint（v2.6 §19.4 全消费点）：与日头徽/编号徽/地图钉同源 */
.toc-pill.is-active {
  background: color-mix(in oklch, var(--chip-color) var(--lp-day-tint-badge), transparent);
  border-color: color-mix(in oklch, var(--chip-color) 55%, transparent);
  color: color-mix(in oklch, var(--chip-color) 72%, var(--lp-text-1));
}

.day-list {
  min-width: 0;
}

.day-block {
  scroll-margin-top: 84px;
}

.budget-dock {
  margin-top: var(--lp-space-4);
}

/* ---------- 挂耳折叠按钮（v2.7 §20 R2，照抄 TREK TripPlannerPage 实测值） ----------
   展开态 = 36×36 挂在面板内缘外 28px、压在面板玻璃之下（z-index:-1 只露贴边一角）；
   收起态 = 面板宽 0 时变身黑色小方块（TREK 原文 #000 + 白图标） */
.panel-ear {
  position: absolute;
  top: 14px;
  z-index: var(--lp-z-ear-under);
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: var(--lp-panel-bg);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  color: var(--lp-text-faint);
  cursor: pointer;
  transition: color 0.15s ease;
}

.panel-ear:hover {
  color: var(--lp-text-1);
}

.ear-left {
  right: -28px;
  border-radius: 0 10px 10px 0;
}

.ear-right {
  left: -28px;
  border-radius: 10px 0 0 10px;
}

.panel-ear.is-collapsed {
  top: 14px;
  z-index: var(--lp-z-ear-over);
  border-radius: 10px;
  background: var(--lp-panel-ear-bg);
  color: var(--lp-panel-ear-ink);
  box-shadow: var(--lp-shadow-md);
}

.ear-left.is-collapsed {
  right: auto;
  left: 0;
}

.ear-right.is-collapsed {
  left: auto;
  right: 0;
}

.panel-ear.is-collapsed:hover {
  color: var(--lp-panel-ear-ink);
}

/* 拖拽调宽热区：面板内缘 4px（TREK 原文），hover 给一层淡影 */
.panel-resize {
  position: absolute;
  top: 0;
  bottom: 0;
  right: 0;
  width: 4px;
  cursor: col-resize;
  background: transparent;
}

.panel-resize.is-left {
  right: auto;
  left: 0;
}

.panel-resize:hover {
  background: color-mix(in srgb, var(--lp-text-1) 8%, transparent);
}

/* ---------- 跨天移动对话框（S4） ---------- */
.move-hint {
  margin: 0 0 var(--lp-space-3);
  font-size: 13px;
  color: var(--lp-text-muted);
}

.move-day-grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lp-space-2);
}

/* ---------- <768 移动壳（本轮不重构成 TREK 底栏体系）：单列分段 + 流式滚动 ---------- */
@media (max-width: 767px) {
  .pane-switch {
    display: flex;
    justify-content: center;
    margin: 0 0 var(--lp-space-3);
  }

  /* 挂耳/拖拽热区只在桌面浮层面板里有意义 */
  .panel-ear,
  .panel-resize {
    display: none;
  }

  .panel:not(.panel-right) {
    padding: 4px 16px 12px;
    background: var(--lp-surface-card);
    border: 1px solid var(--lp-edge-1);
    border-radius: var(--lp-radius-card);
  }

  .day-toc {
    position: static;
  }

  .map-stage {
    border-radius: var(--lp-radius-card);
    overflow: hidden;
  }
}
</style>

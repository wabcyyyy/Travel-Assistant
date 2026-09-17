<template>
  <div class="dashboard">
    <p class="dash-date">{{ todayLabel }} · 今天从这里开始</p>

    <div v-if="loading" class="dash-skeleton">
      <SkeletonCard height="460px" />
      <div class="stats-grid">
        <SkeletonCard v-for="n in 4" :key="n" height="150px" />
      </div>
    </div>

    <AppPanel v-else-if="loadError">
      <EmptyState description="行程列表加载失败，请确认服务已启动后重试">
        <el-button type="primary" @click="load">重试</el-button>
      </EmptyState>
    </AppPanel>

    <div v-else-if="summaries.length" class="dash-grid">
      <!-- 主列：海报式登机牌 → 统计行 → 即将出发 -->
      <div class="dash-main">
        <article
          class="hero"
          role="button"
          tabindex="0"
          :aria-label="`翻开行程：${heroTrip.title}`"
          @click="openTrip(heroTrip.id)"
          @keydown.enter.prevent="openTrip(heroTrip.id)"
        >
          <img class="hero-img" :src="coverOf(heroTrip)" alt="" />
          <div class="hero-veil" aria-hidden="true"></div>

          <div class="hero-top">
            <span class="hero-badge">{{ heroBadge }}</span>
            <div class="hero-tools">
              <button type="button" class="tool-btn" aria-label="换封面" @click.stop="openCover(heroTrip)">
                <el-icon><Picture /></el-icon>
              </button>
              <button type="button" class="tool-btn" aria-label="分享" @click.stop="openShare(heroTrip)">
                <el-icon><Share /></el-icon>
              </button>
              <button type="button" class="tool-btn" aria-label="归档" @click.stop="archiveHero">
                <el-icon><Box /></el-icon>
              </button>
            </div>
          </div>

          <div class="hero-main">
            <h2 class="hero-title">{{ heroTrip.title }}</h2>

            <!-- 票根带：横向一条，两侧半圆缺口 + 各格虚线分隔（对齐 TREK 的登机牌） -->
            <div class="hero-ticket">
              <div class="ticket-cell">
                <p class="ticket-k"><span class="lp-micro k-en">BUDDIES</span><span class="k-cn">伙伴们</span></p>
                <p class="ticket-v">{{ heroTrip.persons }}<span class="ticket-unit">位</span></p>
              </div>
              <div class="ticket-cell">
                <p class="ticket-k"><span class="lp-micro k-en">TRIP DATES</span><span class="k-cn">旅行日期</span></p>
                <p class="ticket-v">{{ heroDates }}</p>
              </div>
              <div class="ticket-cell">
                <p class="ticket-k"><span class="lp-micro k-en">TRIP STARTS IN</span><span class="k-cn">倒计时</span></p>
                <p class="ticket-v">
                  {{ heroCountdown.value }}<span v-if="heroCountdown.unit" class="ticket-unit">{{ heroCountdown.unit }}</span>
                </p>
              </div>
              <div class="ticket-cell">
                <p class="ticket-k"><span class="lp-micro k-en">DESTINATION</span><span class="k-cn">目的地</span></p>
                <p class="ticket-v">{{ heroTrip.city || '未设置城市' }}</p>
              </div>
            </div>
          </div>
        </article>

        <!-- 统计行：1 张深色「护照卡」 + 3 张白卡 -->
        <div class="stats-grid">
          <StatTile
            tone="ink"
            en="ATLAS"
            label="图鉴 · 到访国家"
            :value="atlas?.stats.countryCount ?? '暂无'"
            unit="国"
            :sub="atlas ? `共 195 国 · ${atlas.stats.cityCount} 城已点亮` : '统计不可用'"
          />
          <StatTile
            en="TRIPS TOTAL"
            label="行程段数"
            :value="summaries.length"
            unit="段"
            :sub="`已去过 ${atlas?.stats.visitedTripCount ?? '暂无'} · 计划中 ${atlas?.stats.plannedTripCount ?? '暂无'}`"
          />
          <StatTile
            en="DAYS TRAVELED"
            label="旅行天数"
            :value="totalDays"
            unit="天"
            :sub="`覆盖 ${summaries.length} 段旅程`"
          />
          <StatTile
            en="COORD COVERAGE"
            label="点位坐标覆盖"
            :value="atlas ? atlas.coverage.itemsWithoutCoord : '暂无'"
            unit="项"
            :sub="atlas ? `缺坐标 · ${atlas.coverage.dictMiss} 城未归国` : '统计不可用'"
          />
        </div>

        <AppPanel title="即将出发">
          <ul v-if="upcoming.length" class="trip-list">
            <li v-for="trip in upcoming" :key="trip.id">
              <button type="button" class="trip-row" @click="openTrip(trip.id)">
                <span class="trip-title">{{ trip.title }}</span>
                <span class="trip-meta">{{ trip.startDate }} → {{ trip.endDate }}</span>
              </button>
            </li>
          </ul>
          <EmptyState v-else description="没有即将出发的行程" />
        </AppPanel>
      </div>

      <!-- 右栏：白卡 + 发丝边（与 TREK dashboard 一致：玻璃留给有内容流过的层） -->
      <aside class="dash-rail" aria-label="快捷面板">
        <div class="rail-card">
          <p class="rail-caption">上一趟 · 质量口径</p>
          <div class="rail-head">
            <Chip :tone="qualityTone">{{ qualityLabel }}</Chip>
            <span class="rail-title">{{ latestDetail?.title ?? '暂无详情' }}</span>
          </div>
          <p class="rail-sub">{{ pendingText }}</p>
          <el-button v-if="latestDetail" class="rail-action" @click="openTrip(latestDetail.id)">
            去处理
          </el-button>
        </div>

        <div class="rail-card">
          <p class="rail-caption">旅程图鉴</p>
          <p class="rail-value">
            {{ atlas ? `${atlas.stats.cityCount} 城 · ${atlas.stats.countryCount} 国` : '统计不可用' }}
          </p>
          <p class="rail-sub">一行程 = 一城的聚合图鉴，坐标覆盖如实呈现</p>
          <el-button class="rail-action" @click="$router.push('/atlas')">打开图鉴</el-button>
        </div>

        <div class="rail-card">
          <p class="rail-caption">最近编辑</p>
          <ul class="recent-list">
            <li v-for="trip in recent" :key="trip.id">
              <button type="button" class="recent-row" @click="openTrip(trip.id)">
                <img class="recent-thumb" :src="coverOf(trip)" alt="" loading="lazy" />
                <span class="recent-meta">
                  <span class="recent-title">{{ trip.title }}</span>
                  <span class="recent-sub">{{ trip.city || '未设置城市' }} · {{ trip.days }} 天</span>
                </span>
              </button>
            </li>
          </ul>
        </div>
      </aside>
    </div>

    <AppPanel v-else>
      <EmptyState description="还没有行程，从一个目的地开始">
        <el-button type="primary" @click="$router.push('/generate')">生成第一份行程</el-button>
      </EmptyState>
    </AppPanel>

    <!-- 浮动新建（≥768px；窄屏由底部导航的「生成」承担） -->
    <button type="button" class="fab-new" @click="$router.push('/generate')">
      <el-icon><Plus /></el-icon>
      <span>新建行程</span>
    </button>

    <!-- 登机牌上的工具位复用行程卡同一对弹窗 -->
    <CoverDialog
      v-if="coverTarget"
      v-model:visible="coverVisible"
      :itinerary-id="coverTarget.id"
      :default-query="coverTarget.city"
      @updated="onCoverUpdated"
    />
    <ShareDialog v-if="shareTarget" v-model:visible="shareVisible" :itinerary-id="shareTarget.id" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Box, Picture, Plus, Share } from '@element-plus/icons-vue'

import { getItineraryDetail, getItineraryList, setArchived } from '../api'
import { useAtlasStore } from '../store/atlas'
import CoverDialog from '../components/trip/CoverDialog.vue'
import ShareDialog from '../components/trip/ShareDialog.vue'
import AppPanel from '../components/ui/AppPanel.vue'
import Chip from '../components/ui/Chip.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import SkeletonCard from '../components/ui/SkeletonCard.vue'
import StatTile from '../components/ui/StatTile.vue'
import { coverForCity } from '../constants/covers'
import type { AtlasResponse } from '../types/atlas'
import type { ItineraryDetail, ItinerarySummary } from '../types/itinerary'
import { daysUntil, tripStatusLabel } from '../utils/tripStatus'

// dashboard（SPEC §7.2 + 设计对齐 TREK §18）：主列（海报式登机牌 / 统计行 / 即将出发）
// + 400px 粘性右栏。页头只留一行日期：dashboard 的主角是登机牌本身，
// 不做「页面标题 + 主按钮」那块通用头部（新建入口交给右下 FAB / 底部导航的「生成」）。
const router = useRouter()
const atlasStore = useAtlasStore()

const loading = ref(true)
const loadError = ref(false)
const summaries = ref<ItinerarySummary[]>([])
const atlas = ref<AtlasResponse | null>(null)
const latestDetail = ref<ItineraryDetail | null>(null)

const coverVisible = ref(false)
const coverTarget = ref<ItinerarySummary | null>(null)
const shareVisible = ref(false)
const shareTarget = ref<ItinerarySummary | null>(null)

const todayLabel = computed(() =>
  new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }),
)
const today = new Date().toISOString().slice(0, 10)

/** 即将出发：endDate >= today 的前 3 趟，按出发日升序 */
const upcoming = computed(() =>
  summaries.value
    .filter((trip) => trip.endDate && trip.endDate >= today)
    .sort((a, b) => (a.startDate ?? '').localeCompare(b.startDate ?? ''))
    .slice(0, 3),
)
/** 登机牌主角：优先「即将出发」的第一趟，否则最近一段 */
const heroTrip = computed<ItinerarySummary>(() => upcoming.value[0] ?? summaries.value[0])
const heroIsUpcoming = computed(() => upcoming.value.length > 0)
/** 徽章：临出发时用「接下来」，否则回落到生成状态（英文微标签只在有对应语义时出现） */
const heroBadge = computed(() =>
  heroIsUpcoming.value ? 'UP NEXT 接下来' : tripStatusLabel(heroTrip.value),
)
/** 最近编辑：列表本身按 id 倒序（= 最近创建/编辑在前） */
const recent = computed(() => summaries.value.slice(0, 4))
const totalDays = computed(() => summaries.value.reduce((sum, trip) => sum + (trip.days || 0), 0))

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

/** 票根日期：25 SEP 这样的短格式（与中文并存时保持紧凑） */
function ticketDate(iso?: string | null): string {
  if (!iso) return ''
  const [, month, day] = iso.split('-')
  const index = Number(month) - 1
  if (!day || Number.isNaN(index) || !MONTHS[index]) return iso
  return `${Number(day)} ${MONTHS[index]}`
}

const heroDates = computed(() => {
  const { startDate, endDate } = heroTrip.value
  const start = ticketDate(startDate)
  const end = ticketDate(endDate)
  if (start && end) return `${start} → ${end}`
  return start || end || '未设置'
})

const heroCountdown = computed(() => {
  const days = daysUntil(heroTrip.value?.startDate)
  if (days == null) return { value: '未设置', unit: '' }
  if (days === 0) return { value: '今天出发', unit: '' }
  return { value: `${days}`, unit: '天' }
})

const QUALITY_LABEL: Record<string, string> = {
  READY: '已就绪',
  READY_WITH_WARNINGS: '有提示',
  STALE: '需复核',
  DRAFT: '草稿',
  BLOCKED: '受阻',
}
const QUALITY_TONE: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = {
  READY: 'success',
  READY_WITH_WARNINGS: 'warning',
  STALE: 'warning',
  DRAFT: 'neutral',
  BLOCKED: 'danger',
}

const qualityLabel = computed(() => {
  const status = latestDetail.value?.qualityStatus
  return status ? (QUALITY_LABEL[status] ?? status) : '暂无'
})
const qualityTone = computed(() => {
  const status = latestDetail.value?.qualityStatus
  return status ? (QUALITY_TONE[status] ?? 'neutral') : 'neutral'
})
const pendingText = computed(() => {
  const count = latestDetail.value?.pendingFactCount ?? 0
  return count > 0 ? `出发前需复核 ${count} 项事实（未背书项已降级标注）` : '无需出发前复核'
})

function coverOf(row: ItinerarySummary): string {
  return row.coverUrl || coverForCity(row.city)
}

function openTrip(id: number): void {
  router.push({ name: 'trip-detail', params: { id } })
}

function openCover(row: ItinerarySummary): void {
  coverTarget.value = row
  coverVisible.value = true
}

function openShare(row: ItinerarySummary): void {
  shareTarget.value = row
  shareVisible.value = true
}

function onCoverUpdated(): void {
  void load()
}

async function archiveHero(): Promise<void> {
  try {
    await setArchived(heroTrip.value.id, true)
    ElMessage.success('已归档')
    void load()
  } catch {
    /* 拦截器已提示 */
  }
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = false
  try {
    const list = await getItineraryList()
    summaries.value = list.data ?? []
  } catch {
    // 失败与「没有行程」必须区分：后者是真实空态，前者要能重试
    loadError.value = true
    loading.value = false
    return
  }
  loading.value = false

  const latest = summaries.value[0]
  if (latest) {
    try {
      const detail = await getItineraryDetail(latest.id)
      latestDetail.value = detail.data
    } catch {
      /* 质量口径拿不到不阻塞仪表盘 */
    }
  }
  // 统计走共享缓存（列表页复用同一份；失败返回 null → tile 显示占位）
  atlas.value = await atlasStore.ensureLoaded()
}

onMounted(load)
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--lp-space-4);
}

/* 页头只剩一行日期：首屏主角是下面的登机牌 */
.dash-date {
  margin: 0;
  font-size: 13px;
  color: var(--lp-text-muted);
}

/* ---------- 工作台栅格：主列 + 400px 粘性右栏（1280 以下折成单列） ---------- */
.dash-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 400px;
  gap: var(--lp-space-5);
  align-items: start;
}

.dash-main {
  display: flex;
  flex-direction: column;
  gap: var(--lp-space-5);
  min-width: 0;
}

.dash-rail {
  position: sticky;
  top: 80px;
  display: flex;
  flex-direction: column;
  gap: var(--lp-space-3);
}

.dash-skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--lp-space-3);
}

/* ---------- 海报式登机牌：整张卡就是首屏主角（高度按视口给；trek .hero-trip：
   r32 + 微近影/大氛围影） ---------- */
.hero {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: var(--lp-space-6);
  min-height: clamp(520px, 68vh, 760px);
  padding: var(--lp-space-5);
  border-radius: var(--lp-radius-hero);
  box-shadow: var(--lp-shadow-hero);
  overflow: hidden;
  background: var(--lp-cover-gradient);
  cursor: pointer;
}

.hero:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: 3px;
}

.hero-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.6s ease;
}

.hero:hover .hero-img {
  transform: scale(1.04);
}

.hero-veil {
  position: absolute;
  inset: 0;
  background: var(--lp-cover-scrim);
}

.hero-top {
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--lp-space-3);
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  padding: 6px 14px;
  border: 1px solid color-mix(in srgb, var(--lp-text-inverse) 22%, transparent);
  border-radius: var(--lp-radius-pill);
  background: color-mix(in srgb, var(--lp-bg-inverse) 58%, transparent);
  backdrop-filter: blur(14px);
  color: var(--lp-text-inverse);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.12em;
}

.hero-tools {
  display: flex;
  gap: 8px;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border: 1px solid color-mix(in srgb, var(--lp-text-inverse) 22%, transparent);
  border-radius: 50%;
  background: color-mix(in srgb, var(--lp-bg-inverse) 58%, transparent);
  backdrop-filter: blur(14px);
  color: var(--lp-text-inverse);
  font-size: 19px;
  cursor: pointer;
  transition: background 0.15s ease, transform 0.15s ease;
}

.tool-btn:hover {
  background: color-mix(in srgb, var(--lp-bg-inverse) 78%, transparent);
  transform: scale(1.06);
}

.hero-main {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--lp-space-5);
}

.hero-title {
  margin: 0;
  /* trek .hero-title 实测 104px/600/lh0.9/ls-0.045em；中文标题按 CJK 字形把行距与
     字距放宽两档（0.98/-0.03em），拉丁文仍落在 Poppins 原版节奏上 */
  font-size: clamp(42px, 7.2vw, 104px);
  font-weight: 600;
  line-height: 0.98;
  letter-spacing: -0.03em;
  text-wrap: balance;
  color: var(--lp-text-inverse);
  text-shadow: 0 4px 32px var(--lp-overlay);
}

/* ---------- 票根带：横向一条（值大标签小，不抢标题） ---------- */
.hero-ticket {
  --notch: 14px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  padding: var(--lp-space-3) 0;
  border-radius: var(--lp-radius-card);
  background: var(--lp-ticket-bg);
  color: var(--lp-ticket-ink);
  /* 掩膜的实心色只要求「不透明」，用 currentColor 避免裸色值
     （票根 ink 令牌是纯色，改令牌不会影响掩膜语义） */
  -webkit-mask:
    radial-gradient(circle var(--notch) at 0 50%, transparent 98%, currentColor 100%),
    radial-gradient(circle var(--notch) at 100% 50%, transparent 98%, currentColor 100%);
  -webkit-mask-composite: source-in;
  mask:
    radial-gradient(circle var(--notch) at 0 50%, transparent 98%, currentColor 100%),
    radial-gradient(circle var(--notch) at 100% 50%, transparent 98%, currentColor 100%);
  mask-composite: intersect;
}

.ticket-cell {
  display: flex;
  flex-direction: column;
  gap: var(--lp-space-1);
  min-width: 0;
  padding: 0 var(--lp-space-4);
}

.ticket-cell + .ticket-cell {
  border-left: 1px dashed var(--lp-ticket-line);
}

.ticket-k {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
}

.k-en {
  /* 规格来自全局 .lp-micro（大写英文微标签唯一来源），这里只覆盖票根内的颜色 */
  color: var(--lp-ticket-ink-soft);
}

.k-cn {
  font-size: 11px;
  color: var(--lp-ticket-ink-soft);
}

.ticket-v {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.01em;
  font-variant-numeric: tabular-nums;
  color: var(--lp-ticket-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ticket-unit {
  margin-left: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--lp-ticket-ink-soft);
}

/* ---------- 统计行 ---------- */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--lp-space-3);
}

/* ---------- 右栏卡（v2.8 对表 trek .tool 实测）：暖玻璃渐变 + 28px 圆角 + 内高光 ---------- */
.rail-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--lp-space-2);
  padding: var(--lp-space-5) var(--lp-space-5) var(--lp-space-4);
  border: 1px solid var(--lp-glass-border);
  border-radius: var(--lp-radius-xl);
  background: var(--lp-glass-bg);
  backdrop-filter: var(--lp-glass-blur);
  -webkit-backdrop-filter: var(--lp-glass-blur);
  box-shadow: var(--lp-glass-shadow), var(--lp-glass-highlight);
}

.rail-caption {
  margin: 0;
  font-size: var(--lp-text-caption);
  letter-spacing: 0.08em;
  color: var(--lp-text-muted);
}

.rail-head {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
  min-width: 0;
}

.rail-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--lp-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rail-value {
  margin: 0;
  font-family: var(--lp-font-mono);
  font-size: 18px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--lp-text-1);
}

.rail-sub {
  margin: 0;
  font-size: var(--lp-text-caption);
  line-height: 1.7;
  color: var(--lp-text-muted);
}

.rail-action {
  margin-top: var(--lp-space-1);
}

/* ---------- 最近编辑：缩略图行 ---------- */
.recent-list {
  display: flex;
  flex-direction: column;
  gap: var(--lp-space-2);
  width: 100%;
  margin: 0;
  padding: 0;
  list-style: none;
}

.recent-row {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
  width: 100%;
  padding: 4px;
  border: none;
  border-radius: var(--lp-radius-xs);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}

.recent-row:hover {
  background: var(--lp-surface-hover);
}

.recent-thumb {
  flex: none;
  width: 42px;
  height: 42px;
  border-radius: var(--lp-radius-xs);
  object-fit: cover;
  background: var(--lp-surface-2);
}

.recent-meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.recent-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--lp-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-sub {
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
}

/* ---------- 行程行（即将出发） ---------- */
.trip-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
}

.trip-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--lp-space-3);
  width: 100%;
  padding: var(--lp-space-2) 4px;
  border: none;
  border-bottom: 1px solid var(--lp-edge-faint);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.trip-list li:last-child .trip-row {
  border-bottom: none;
}

.trip-row:hover {
  background: var(--lp-surface-2);
}

.trip-title {
  font-weight: 600;
  color: var(--lp-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trip-meta {
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
  white-space: nowrap;
}

/* ---------- 浮动新建（桌面；窄屏走底部导航的「生成」） ---------- */
.fab-new {
  position: fixed;
  right: var(--lp-space-5);
  bottom: var(--lp-space-5);
  z-index: var(--lp-z-sticky);
  display: inline-flex;
  align-items: center;
  gap: var(--lp-space-2);
  height: 52px;
  padding: 0 var(--lp-space-5);
  border: none;
  border-radius: var(--lp-radius-pill);
  background: var(--lp-ink-card-bg);
  color: var(--lp-ink-card-ink);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: var(--lp-shadow-lg);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.fab-new:hover {
  transform: translateY(-2px);
}

.fab-new:active {
  transform: translateY(0) scale(0.98);
}

@media (max-width: 1279px) {
  .dash-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .dash-rail {
    position: static;
  }
}

@media (max-width: 1000px) {
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  /* 票根折成 2×2：虚线只在「格与格」之间（避免外沿出现孤立虚线） */
  .hero-ticket {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--lp-space-3) 0;
  }

  .ticket-cell:nth-child(odd) {
    padding-left: var(--lp-space-4);
    border-left: none;
  }

  .ticket-cell:nth-child(n + 3) {
    border-top: 1px dashed var(--lp-ticket-line);
    padding-top: var(--lp-space-3);
  }
}

@media (max-width: 767px) {
  .fab-new {
    display: none;
  }

  .hero {
    min-height: clamp(460px, 76vh, 620px);
    padding: var(--lp-space-4);
  }

  .hero-title {
    font-size: clamp(42px, 12.5vw, 72px);
  }

  /* 窄屏票根再收一档：条要薄，画面留给照片与标题 */
  .hero-ticket {
    padding: var(--lp-space-2) 0;
  }

  .ticket-v {
    font-size: 18px;
  }
}
</style>

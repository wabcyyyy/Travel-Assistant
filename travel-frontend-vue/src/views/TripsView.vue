<template>
  <div class="trips">
    <SectionHead title="我的行程" :sub="bandSub">
      <template #actions>
        <el-button type="primary" @click="$router.push('/generate')">新建行程</el-button>
      </template>
    </SectionHead>

    <Toolbar class="filters">
      <button
        v-for="tab in TABS"
        :key="tab.value"
        type="button"
        class="view-pill"
        :class="{ active: view === tab.value }"
        :aria-pressed="view === tab.value"
        @click="setView(tab.value)"
      >
        {{ tab.label }}
      </button>
      <div class="search-box">
        <el-input
          v-model="keyword"
          placeholder="搜索标题或城市…"
          clearable
          :prefix-icon="Search"
          aria-label="搜索行程"
          @keyup.enter="applySearch"
          @clear="applySearch"
        />
      </div>
    </Toolbar>

    <div v-if="loading" class="trip-grid">
      <SkeletonCard v-for="i in 6" :key="i" height="260px" />
    </div>

    <div v-else-if="list.length" class="trip-grid">
      <article v-for="row in list" :key="row.id" class="trip-card">
        <div
          class="trip-cover"
          role="button"
          tabindex="0"
          :aria-label="`翻开行程：${row.title}`"
          @click="goDetail(row)"
          @keydown.enter.prevent="goDetail(row)"
        >
          <!-- 封面优先级：coverUrl（服务端 snapshot）→ 城市兜底图 → 通用兜底 -->
          <img :src="coverOf(row)" alt="" loading="lazy" />
          <div class="lp-cover-fade" aria-hidden="true"></div>
          <Chip class="cover-tag" :tone="statusTone(row)">{{ statusLabel(row) }}</Chip>
          <!-- 操作区常驻（TREK 借鉴：深色 scrim 保证白图标压得住亮封面） -->
          <div class="trip-actions">
            <button
              type="button"
              class="act-btn fav-btn"
              :class="{ active: row.favorite }"
              :aria-pressed="!!row.favorite"
              :aria-label="row.favorite ? '取消收藏' : '收藏'"
              @click.stop="toggleFavorite(row)"
            >
              <el-icon><component :is="row.favorite ? StarFilled : Star" /></el-icon>
            </button>
            <div class="menu-holder" @click.stop>
              <AppMenu :items="menuFor(row)" trigger-label="更多操作" @select="onRowMenu($event, row)" />
            </div>
          </div>
        </div>
        <div class="trip-body">
          <button type="button" class="trip-title" @click="goDetail(row)">{{ row.title }}</button>
          <p class="trip-theme">{{ row.tripTheme || '未命名主题' }}</p>
          <div class="trip-meta">
            <span>{{ row.city || '未设置城市' }}</span>
            <span>{{ row.startDate || '未设置日期' }}</span>
          </div>
          <!-- 三列计数（设计对齐 TREK）：mono 数字 + 大写小标签 -->
          <div class="trip-counts">
            <div class="count-cell">
              <span class="count-n">{{ row.days }}</span>
              <span class="lp-micro count-k">天数</span>
            </div>
            <div class="count-cell">
              <span class="count-n">{{ row.persons }}</span>
              <span class="lp-micro count-k">同行</span>
            </div>
            <div class="count-cell">
              <span class="count-n">￥{{ row.totalAmount }}</span>
              <span class="lp-micro count-k">预算</span>
            </div>
          </div>
        </div>
      </article>

      <!-- 虚线「新建行程」卡（TREK 借鉴）：空位即入口 -->
      <button type="button" class="new-trip-card" @click="$router.push('/generate')">
        <el-icon class="new-plus"><Plus /></el-icon>
        <span class="new-label">新建行程</span>
        <span class="new-sub">选目的地与偏好，Agent 整段生成</span>
      </button>
    </div>

    <AppPanel v-else>
      <EmptyState :description="emptyDescription">
        <el-button v-if="loadError" @click="load">重新加载</el-button>
        <el-button v-else type="primary" @click="$router.push('/generate')">去生成行程</el-button>
      </EmptyState>
    </AppPanel>

    <!-- 悬停动作里的「换封面 / 分享」复用详情页同一对弹窗 -->
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
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Search, Star, StarFilled } from '@element-plus/icons-vue'

import { deleteItinerary, listItineraries, setArchived, setFavorite } from '../api'
import CoverDialog from '../components/trip/CoverDialog.vue'
import ShareDialog from '../components/trip/ShareDialog.vue'
import AppMenu from '../components/ui/AppMenu.vue'
import AppPanel from '../components/ui/AppPanel.vue'
import Chip from '../components/ui/Chip.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import SectionHead from '../components/ui/SectionHead.vue'
import SkeletonCard from '../components/ui/SkeletonCard.vue'
import Toolbar from '../components/ui/Toolbar.vue'
import { coverForCity } from '../constants/covers'
import { useAtlasStore } from '../store/atlas'
import type { ItinerarySummary } from '../types/itinerary'
import { tripStatusLabel, tripStatusTone } from '../utils/tripStatus'

// 封面墙（SPEC §7.3）：view 五档 = 「写完了没 / 收不收藏」（生成状态轴），
// 与 Atlas 的 scope（去过/计划，日期启发式）是两套过滤轴，文案不混用。
const route = useRoute()
const router = useRouter()
const atlasStore = useAtlasStore()

const TABS = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '计划中' },
  { value: 'done', label: '已完成' },
  { value: 'favorite', label: '收藏' },
  { value: 'archived', label: '已归档' },
] as const
type ViewValue = (typeof TABS)[number]['value']

const list = ref<ItinerarySummary[]>([])
const loading = ref(true)
const loadError = ref(false)
const keyword = ref(typeof route.query.q === 'string' ? route.query.q : '')
const coverTarget = ref<ItinerarySummary | null>(null)
const coverVisible = ref(false)
const shareTarget = ref<ItinerarySummary | null>(null)
const shareVisible = ref(false)

function openCover(row: ItinerarySummary) {
  coverTarget.value = row
  coverVisible.value = true
}

function openShare(row: ItinerarySummary) {
  shareTarget.value = row
  shareVisible.value = true
}

/** 封面更新后列表卡片要跟着变（封面图在列表上） */
function onCoverUpdated() {
  void load()
}

const view = computed<string>(() => {
  const value = route.query.view
  return typeof value === 'string' && TABS.some((tab) => tab.value === value) ? value : 'all'
})

const bandSub = computed(() => {
  const atlas = atlasStore.data
  const coverage = atlas ? ` · 覆盖 ${atlas.stats.cityCount} 城 ${atlas.stats.countryCount} 国` : ''
  return `共 ${list.value.length} 本${coverage}`
})

const EMPTY_TEXT: Record<string, string> = {
  all: '还没有行程，从一个目的地开始',
  active: '没有计划中的行程',
  done: '还没有已完成的行程',
  favorite: '还没有收藏的行程',
  archived: '没有已归档的行程',
}
const emptyDescription = computed(() =>
  loadError.value ? '行程加载失败，请确认服务已启动后重试' : (EMPTY_TEXT[view.value] ?? EMPTY_TEXT.all),
)

function coverOf(row: ItinerarySummary): string {
  return row.coverUrl || coverForCity(row.city)
}

function statusLabel(row: ItinerarySummary): string {
  return tripStatusLabel(row)
}

function statusTone(row: ItinerarySummary): 'success' | 'warning' | 'danger' | 'neutral' {
  return tripStatusTone(row)
}

function goDetail(row: ItinerarySummary) {
  void router.push(`/trips/${row.id}`)
}

function setView(value: ViewValue) {
  void router.replace({ query: { ...route.query, view: value === 'all' ? undefined : value } })
}

function applySearch() {
  void router.replace({ query: { ...route.query, q: keyword.value.trim() || undefined } })
}

async function load() {
  loading.value = true
  loadError.value = false
  try {
    const res = await listItineraries(view.value, keyword.value.trim())
    list.value = res.data
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
  void atlasStore.ensureLoaded()
}

// 路由 query 是唯一筛选源（顶栏全局搜索也带 q 落到这里）：变化即重新拉取
watch(
  () => [route.query.view, route.query.q].join('|'),
  () => {
    keyword.value = typeof route.query.q === 'string' ? route.query.q : ''
    void load()
  },
  { immediate: true },
)

async function toggleFavorite(row: ItinerarySummary) {
  try {
    await setFavorite(row.id, !row.favorite)
    if (view.value === 'favorite') {
      void load() // 收藏视图里取消收藏 → 该行应离开本视图
    } else {
      row.favorite = !row.favorite
    }
  } catch {
    /* 拦截器已提示 */
  }
}

async function onArchive(row: ItinerarySummary, archived: boolean) {
  try {
    await setArchived(row.id, archived)
    ElMessage.success(archived ? '已归档' : '已取消归档')
    void load()
  } catch {
    /* 拦截器已提示 */
  }
}

/** 行操作菜单项（v2.6 §19.2：AppMenu 数据驱动，动态文案与 divided 由这里表达） */
function menuFor(row: ItinerarySummary) {
  return [
    { key: 'open', label: '翻开行程' },
    { key: 'cover', label: '换封面' },
    { key: 'share', label: '分享' },
    { key: 'favorite', label: row.favorite ? '取消收藏' : '收藏' },
    row.archived
      ? { key: 'unarchive', label: '取消归档' }
      : { key: 'archive', label: '归档' },
    { key: 'delete', label: '删除行程', danger: true, divided: true },
  ]
}

function onRowMenu(key: string, row: ItinerarySummary) {
  if (key === 'open') goDetail(row)
  else if (key === 'cover') openCover(row)
  else if (key === 'share') openShare(row)
  else if (key === 'favorite') void toggleFavorite(row)
  else if (key === 'archive') void onArchive(row, true)
  else if (key === 'unarchive') void onArchive(row, false)
  else if (key === 'delete') void onDelete(row)
}

async function onDelete(row: ItinerarySummary) {
  try {
    await ElMessageBox.confirm(`确认删除「${row.title}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  await deleteItinerary(row.id)
  ElMessage.success('已删除')
  void load()
}
</script>

<style scoped>
.trips {
  display: flex;
  flex-direction: column;
  gap: var(--lp-space-4);
}

.filters {
  align-items: center;
}

.view-pill {
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

.view-pill:hover {
  border-color: var(--lp-accent);
  color: var(--lp-accent);
}

.view-pill.active {
  background: var(--lp-accent);
  border-color: var(--lp-accent);
  color: var(--lp-accent-on-fill);
}

.search-box {
  margin-left: auto;
  width: min(280px, 100%);
}

.trip-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--lp-space-4);
}

.trip-card {
  display: flex;
  flex-direction: column;
  background: var(--lp-surface-card);
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-card);
  overflow: hidden;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.trip-card:hover {
  border-color: var(--lp-accent);
  box-shadow: var(--lp-shadow-md);
  transform: translateY(-4px);
}

.trip-cover {
  position: relative;
  height: 170px;
  background: var(--lp-surface-2);
  overflow: hidden;
  cursor: pointer;
}

.trip-cover:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: -2px;
}

.trip-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.4s ease;
}

.trip-card:hover .trip-cover img {
  transform: scale(1.04);
}

.cover-tag {
  position: absolute;
  top: 10px;
  left: 10px;
}

/* 盖在图上的一律深色 scrim + 反色字（与登机牌徽章/工具钮同一条规则）：
   浅底状态章压在照片上会「发虚」，也是 TREK 在封面上的做法 */
.trip-cover :deep(.cover-tag) {
  border: 1px solid color-mix(in srgb, var(--lp-text-inverse) 22%, transparent);
  background: color-mix(in srgb, var(--lp-bg-inverse) 58%, transparent);
  backdrop-filter: blur(14px);
  color: var(--lp-text-inverse);
}

/* 操作区：常驻右上（设计对齐 TREK：深色 58% scrim + 白图标，亮封面也压得住） */
.trip-actions {
  position: absolute;
  top: 10px;
  right: 10px;
  display: flex;
  gap: 6px;
  opacity: 0.92;
}

.trip-card:hover .trip-actions,
.trip-actions:focus-within {
  opacity: 1;
}

.act-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid color-mix(in srgb, var(--lp-text-inverse) 22%, transparent);
  border-radius: 50%;
  background: color-mix(in srgb, var(--lp-bg-inverse) 58%, transparent);
  backdrop-filter: blur(14px);
  color: var(--lp-text-inverse);
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, transform 0.15s ease;
}

.act-btn:hover {
  background: color-mix(in srgb, var(--lp-bg-inverse) 78%, transparent);
  transform: scale(1.06);
}

.act-btn.active {
  color: var(--lp-danger);
}

/* AppMenu 触发器在照片上的同款观感（自研菜单替换 el-dropdown，v2.6 §19.2）：
   白图标 + 深色 scrim，与 .act-btn 同规格 */
.menu-holder {
  display: inline-flex;
}

.trip-actions :deep(.menu-trigger) {
  width: 34px;
  height: 34px;
  border: 1px solid color-mix(in srgb, var(--lp-text-inverse) 22%, transparent);
  border-radius: 50%;
  background: color-mix(in srgb, var(--lp-bg-inverse) 58%, transparent);
  backdrop-filter: blur(14px);
  color: var(--lp-text-inverse);
}

.trip-actions :deep(.menu-trigger:hover),
.trip-actions :deep(.menu-trigger[aria-expanded='true']) {
  background: color-mix(in srgb, var(--lp-bg-inverse) 78%, transparent);
  color: var(--lp-text-inverse);
}

/* ---------- 三列计数（TREK 借鉴：mono 数字 + 大写小标签） ---------- */
.trip-counts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--lp-space-2);
  margin-top: var(--lp-space-2);
  padding-top: var(--lp-space-2);
  border-top: 1px solid var(--lp-edge-faint);
}

.count-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.count-n {
  font-family: var(--lp-font-mono);
  font-size: 17px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--lp-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.count-k {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.12em;
  color: var(--lp-text-muted);
}

/* ---------- 虚线「新建行程」卡：空位即入口 ---------- */
.new-trip-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--lp-space-1);
  min-height: 260px;
  padding: var(--lp-space-4);
  border: 1px dashed var(--lp-edge-2);
  border-radius: var(--lp-radius-card);
  background: transparent;
  color: var(--lp-text-muted);
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease, background 0.2s ease;
}

.new-trip-card:hover {
  border-color: var(--lp-accent);
  color: var(--lp-accent);
  background: var(--lp-surface-2);
}

.new-plus {
  font-size: 28px;
  line-height: 1;
}

.new-label {
  font-size: 15px;
  font-weight: 600;
  color: var(--lp-text-1);
}

.new-sub {
  font-size: var(--lp-text-caption);
}

.trip-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px 14px;
}

.trip-title {
  padding: 0;
  border: none;
  background: none;
  text-align: left;
  font-size: 16px;
  font-weight: 700;
  color: var(--lp-text-1);
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trip-title:hover {
  color: var(--lp-accent);
}

.trip-theme {
  margin: 0;
  font-size: 12.5px;
  color: var(--lp-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trip-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lp-space-2);
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
}

@media (max-width: 640px) {
  .trip-grid {
    grid-template-columns: 1fr;
  }

  .search-box {
    margin-left: 0;
    width: 100%;
  }
}
</style>

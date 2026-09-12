<template>
  <div class="trips">
    <!-- 手册扉页页头 -->
    <div class="page-band">
      <div class="band-copy">
        <p class="band-eyebrow">TRAVEL HANDBOOK</p>
        <h2>我的行程</h2>
        <p class="band-sub">共 {{ list.length }} 个行程 · 点击卡片查看详情</p>
      </div>
      <div class="actions">
        <el-button round type="primary" @click="$router.push('/generate')">+ 新建行程</el-button>
      </div>
    </div>

    <!-- 骨架屏：与卡片同构 -->
    <div v-if="loading" class="trip-grid">
      <el-skeleton v-for="i in 4" :key="i" animated class="trip-skeleton">
        <template #template>
          <el-skeleton-item variant="image" style="height: 150px; width: 100%" />
          <div style="padding: 16px">
            <el-skeleton-item variant="text" style="width: 60%" />
            <el-skeleton-item variant="text" style="width: 40%; margin-top: 10px" />
          </div>
        </template>
      </el-skeleton>
    </div>

    <div v-else-if="list.length" class="trip-grid">
      <div
        v-for="row in list"
        :key="row.id"
        class="trip-card"
        role="link"
        tabindex="0"
        :aria-label="`查看行程：${row.title}`"
        @click="goDetail(row)"
        @keyup.enter.prevent="goDetail(row)"
        @keyup.space.prevent="goDetail(row)"
      >
        <div class="trip-cover">
          <img :src="coverForCity(row.city || row.title || '')" alt="旅行封面" loading="lazy" />
          <div class="lp-cover-fade" aria-hidden="true"></div>
          <el-tag
            class="cover-tag"
            :type="row.status === 2 ? 'success' : row.status === 1 ? 'warning' : 'danger'"
            size="small"
          >
            {{ row.status === 2 ? '已生成' : row.status === 1 ? '生成中' : '生成失败' }}
          </el-tag>
        </div>
        <div class="trip-body">
          <div class="trip-title">{{ row.title }}</div>
          <div class="trip-dest">
            <span class="dest-city">{{ row.city || '—' }}</span>
            <span class="dest-meta">{{ row.days }} 天 / {{ row.persons }} 人</span>
          </div>
          <div class="trip-dates">{{ row.startDate || '—' }} ~ {{ row.endDate || '—' }}</div>
          <!-- 主题摘要行（§5.5）：trip_theme 衬线小字；字段不存在时回退 muted 文案而非空槽 -->
          <div class="trip-theme">
            <span v-if="row.tripTheme" class="theme-text">{{ row.tripTheme }}</span>
            <span v-else class="theme-empty">未命名行程</span>
          </div>
          <div class="trip-foot">
            <span class="trip-price">￥{{ row.totalAmount }}</span>
            <span class="trip-actions" @click.stop>
              <el-button link type="primary" @click="goDetail(row)">查看</el-button>
              <el-button link type="danger" @click="onDelete(row)">删除</el-button>
            </span>
          </div>
        </div>
      </div>
    </div>

    <el-card v-else shadow="never">
      <el-empty :description="loadError ? '行程加载失败，请刷新重试' : '暂无行程，先去生成一个吧'">
        <el-button v-if="loadError" @click="load">重新加载</el-button>
        <el-button v-else type="primary" @click="$router.push('/generate')">去生成行程</el-button>
      </el-empty>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { deleteItinerary, getItineraryList } from '../api'
import type { ItinerarySummary } from '../types/itinerary'

import { coverForCity } from '../constants/covers'

const $router = useRouter()
const list = ref<ItinerarySummary[]>([])
const loading = ref(true)
const loadError = ref(false)

function goDetail(row: ItinerarySummary) {
  void $router.push(`/trips/${row.id}`)
}

async function load() {
  loading.value = true
  loadError.value = false
  try {
    const res = await getItineraryList()
    list.value = res.data
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
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

onMounted(load)
</script>

<style scoped>
.trips {
  max-width: var(--lp-content, 1120px);
  margin: 0 auto;
}

/* ---------- 手册扉页页头：深绿底 + 陶土圆盘 ---------- */
.page-band {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
  padding: 28px 32px;
  border-radius: 16px;
  overflow: hidden;
  background: var(--lp-cover-gradient);
  color: #fffdf8;
  box-shadow: var(--lp-shadow-accent);
}

.page-band::after {
  content: '';
  position: absolute;
  right: -60px;
  bottom: -90px;
  width: 220px;
  height: 220px;
  border-radius: 50%;
  background: var(--lp-accent-warm);
  opacity: 0.85;
  pointer-events: none;
}

.page-band .band-copy {
  position: relative;
  z-index: 1;
}

.page-band .band-eyebrow {
  margin: 0 0 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgb(255 253 248 / 70%);
}

.page-band .actions {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  flex: none;
}

.page-band h2 {
  margin: 0 0 2px;
  font-family: var(--lp-font-display);
  font-size: 26px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: #fffdf8;
}

.page-band .band-sub {
  margin: 0;
  font-size: 13px;
  color: rgb(255 253 248 / 78%);
}

.page-band :deep(.el-button--primary) {
  background: rgb(255 255 255 / 16%);
  border-color: rgb(255 255 255 / 40%);
  color: #fff;
}

.page-band :deep(.el-button--primary:hover) {
  background: rgb(255 255 255 / 28%);
  border-color: rgb(255 255 255 / 60%);
  color: #fff;
}

.trip-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 18px;
}

.trip-skeleton {
  border: 1px solid var(--lp-border);
  border-radius: 16px;
  overflow: hidden;
  background: var(--lp-surface);
}

/* ---------- 卡片：封面图 + 内容 ---------- */
.trip-card {
  display: flex;
  flex-direction: column;
  background: var(--lp-surface);
  border: 1px solid var(--lp-border);
  border-radius: 16px;
  overflow: hidden;
  cursor: pointer;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;
}

.trip-card:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: 2px;
}

.trip-card:hover {
  border-color: var(--lp-accent);
  box-shadow: var(--lp-shadow-md);
  transform: translateY(-2px);
}

.trip-card:hover .trip-cover img {
  transform: scale(1.05);
}

.trip-cover {
  position: relative;
  height: 150px;
  background: var(--lp-sand);
  overflow: hidden;
}

.trip-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.4s ease;
}

.cover-tag {
  position: absolute;
  top: 10px;
  right: 10px;
  background: rgb(255 255 255 / 92%);
  backdrop-filter: blur(4px);
}

.trip-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px 16px;
}

.trip-title {
  font-family: var(--lp-font-display);
  font-size: 17px;
  font-weight: 600;
  color: var(--lp-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trip-dest {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.dest-city {
  position: relative;
  padding-left: 14px;
  font-size: 14px;
  font-weight: 700;
  color: var(--lp-ink-soft);
}

.dest-city::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--lp-accent);
}

.dest-meta {
  font-size: 13px;
  color: var(--lp-muted);
}

.trip-dates {
  font-size: 13px;
  color: var(--lp-muted);
  font-variant-numeric: tabular-nums;
}

/* ---------- 主题摘要行（§5.5）：trip_theme 衬线小字，--lp-theme-accent 渐变衬字 ---------- */
.trip-theme {
  display: flex;
  align-items: baseline;
  min-height: 18px;
}

.theme-text {
  font-family: var(--lp-font-display);
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  /* 渐变文字：--lp-theme-accent（青绿→蓝绿）；不支持时回落正文强调色 */
  color: var(--lp-accent-hover);
  background: var(--lp-theme-accent);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

/* 无主题：muted 文案占位（文案而非空槽） */
.theme-empty {
  font-size: 12.5px;
  font-style: italic;
  color: var(--lp-muted);
}

.trip-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  padding-top: 10px;
  border-top: 1px dashed var(--lp-border);
}

.trip-price {
  font-size: 18px;
  font-weight: 800;
  color: var(--lp-accent);
  font-variant-numeric: tabular-nums;
}

.trip-created {
  font-size: 11px;
  color: var(--lp-muted);
}

@media (max-width: 640px) {
  .page-band {
    padding: 20px 18px;
  }

  .page-band::after {
    width: 140px;
    height: 140px;
    right: -40px;
    bottom: -60px;
  }

  .page-band h2 {
    font-size: 22px;
  }

  .trip-grid {
    grid-template-columns: 1fr;
  }
}
</style>

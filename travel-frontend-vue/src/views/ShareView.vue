<template>
  <div class="share-page">
    <!-- 内联轻顶栏：公开页不渲染 AppShell（SPEC §1.3） -->
    <header class="share-top">
      <router-link class="brand" to="/">旅行助手</router-link>
      <router-link class="cta" to="/generate?new=1">我也来做一份</router-link>
    </header>

    <main class="share-main">
      <AppPanel v-if="loading">
        <p class="state-text">加载中…</p>
      </AppPanel>

      <AppPanel v-else-if="error">
        <EmptyState description="链接无效或已失效">
          <router-link class="link-btn" to="/">回首页</router-link>
          <router-link class="link-btn primary" to="/generate?new=1">生成我的行程</router-link>
        </EmptyState>
      </AppPanel>

      <template v-else-if="data">
        <section class="hero" :class="{ 'has-cover': !!data.coverUrl }">
          <div
            v-if="data.coverUrl"
            class="hero-img"
            :style="{ backgroundImage: `url(${data.coverUrl})` }"
            aria-hidden="true"
          ></div>
          <div class="hero-body">
            <p class="hero-eyebrow">{{ data.city }}</p>
            <h1 class="hero-title lp-display">{{ data.title }}</h1>
            <p class="hero-sub">
              {{ data.days }} 天 · {{ data.persons }} 人
              <template v-if="data.startDate"> · {{ data.startDate }} ~ {{ data.endDate }}</template>
              <template v-if="data.budget != null"> · 预算 ￥{{ data.budget }}</template>
            </p>
          </div>
        </section>

        <p v-if="data.tripTheme" class="theme-line">{{ data.tripTheme }}</p>

        <AppPanel v-for="day in data.dayList" :key="day.dayNo">
          <header class="day-head">
            <span class="day-no">D{{ String(day.dayNo).padStart(2, '0') }}</span>
            <span v-if="day.travelDate" class="day-date">{{ day.travelDate }}</span>
            <span v-if="day.theme" class="day-theme">{{ day.theme }}</span>
            <span class="day-total">￥{{ day.dayTotalAmount }}</span>
          </header>
          <p v-if="day.note" class="day-note">{{ day.note }}</p>
          <ul class="item-list">
            <li v-for="(item, index) in day.items" :key="`${day.dayNo}-${index}`" class="item-row">
              <img
                v-if="proxyImage(item.image)"
                class="item-img"
                :src="proxyImage(item.image) || ''"
                :alt="item.poiName"
                loading="lazy"
              />
              <div class="item-main">
                <span class="item-name">{{ item.poiName }}</span>
                <span class="item-meta">
                  <template v-if="item.startTime">{{ item.startTime }}<template v-if="item.endTime"> - {{ item.endTime }}</template> · </template>
                  {{ item.address || '暂无地址' }}
                </span>
              </div>
              <span v-if="item.cost != null" class="item-cost">￥{{ item.cost }}</span>
            </li>
          </ul>
        </AppPanel>

        <AppPanel v-if="data.budgetList.length">
          <header class="day-head">
            <span class="day-no">预算</span>
            <span class="day-total">合计 ￥{{ data.totalAmount }}</span>
          </header>
          <ul class="item-list">
            <li v-for="row in data.budgetList" :key="row.category" class="item-row">
              <div class="item-main"><span class="item-name">{{ row.category }}</span></div>
              <span class="item-cost">￥{{ row.amount ?? 0 }}</span>
            </li>
          </ul>
        </AppPanel>

        <p v-if="data.planNote" class="plan-note">{{ data.planNote }}</p>

        <p v-if="data.coverCredit?.author" class="credit">
          Photo · {{ data.coverCredit.author }}<template v-if="data.coverCredit.license">（{{ data.coverCredit.license }}）</template>
        </p>
      </template>
    </main>

    <footer class="share-footer">
      <router-link class="cta big" to="/generate?new=1">生成我的行程</router-link>
      <p class="foot-note">本地演示项目 · {{ DATA_PROVENANCE }}，仅供学习展示 · {{ DATA_PROVENANCE_DISCLAIMER }}</p>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { getSharedItinerary } from '../api/share'
import AppPanel from '../components/ui/AppPanel.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import { DATA_PROVENANCE, DATA_PROVENANCE_DISCLAIMER } from '../constants/data-provenance'
import type { SharedItinerary } from '../types/share'

// 公开只读分享页（SPEC §7.6）：匿名可开、无写接口；锚点 D{n}-{index}；
// 脱敏 VO 由服务端白名单保证（页面只渲染白名单字段）。
const route = useRoute()
const loading = ref(true)
const error = ref(false)
const data = ref<SharedItinerary | null>(null)

function proxyImage(url: string | null | undefined): string | null {
  if (!url) return null
  if (url.startsWith('/')) return url
  // 外链点位图走同源白名单代理（匿名可读），避免热链与混合内容
  return `/api/image-proxy?url=${encodeURIComponent(url)}`
}

async function load(): Promise<void> {
  const token = String(route.params.token ?? '')
  loading.value = true
  error.value = false
  data.value = null
  try {
    const res = await getSharedItinerary(token)
    data.value = res.data
    document.title = `${res.data.title} · 旅行助手`
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => route.params.token, load)
</script>

<style scoped>
.share-page {
  min-height: 100vh;
  background: var(--lp-surface-1);
}

.share-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--lp-space-3) var(--lp-space-5);
  border-bottom: 1px solid var(--lp-glass-border);
  background: var(--lp-glass-bg);
  backdrop-filter: var(--lp-glass-blur);
  box-shadow: var(--lp-glass-shadow), var(--lp-glass-highlight);
}

.brand {
  font-family: var(--lp-font-display);
  font-weight: 600;
  letter-spacing: -0.02em;
  letter-spacing: 0.04em;
  color: var(--lp-text-1);
  text-decoration: none;
}

.cta {
  color: var(--lp-accent-hover);
  font-weight: 600;
  text-decoration: none;
}

.cta.big {
  display: inline-block;
  padding: 10px 22px;
  border-radius: var(--lp-radius-pill);
  background: var(--lp-accent);
  color: var(--lp-accent-on-fill);
}

.share-main {
  max-width: 860px;
  margin: 0 auto;
  padding: var(--lp-space-5);
  display: flex;
  flex-direction: column;
  gap: var(--lp-space-3);
}

.state-text {
  margin: 0;
  color: var(--lp-text-muted);
}

.link-btn {
  display: inline-block;
  padding: 8px 18px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-pill);
  color: var(--lp-text-2);
  text-decoration: none;
}

.link-btn.primary {
  border-color: var(--lp-accent);
  background: var(--lp-accent);
  color: var(--lp-accent-on-fill);
}

.hero {
  position: relative;
  overflow: hidden;
  border-radius: var(--lp-radius-card);
  padding: 52px 36px 40px;
  background: var(--lp-cover-gradient);
  color: var(--lp-text-inverse);
}

.hero-img {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: center;
  opacity: 0.45;
}

.hero-body {
  position: relative;
  /* 图上压字：用遮罩色做投影，保住白字对比（纯令牌，无裸色值） */
  text-shadow: 0 1px 10px var(--lp-overlay);
}

.hero-eyebrow {
  margin: 0 0 10px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  opacity: 0.75;
}

.hero-title {
  margin: 0 0 8px;
  font-family: var(--lp-font-display);
  font-size: clamp(26px, 4vw, 40px);
  font-weight: 600;
  letter-spacing: -0.03em;
  line-height: 1.02;
  color: var(--lp-text-1);
}

.hero-sub {
  margin: 0;
  font-size: 14px;
  opacity: 0.85;
}

.theme-line {
  margin: 0;
  padding: 0 4px;
  font-size: 15px;
  color: var(--lp-accent-hover);
  font-weight: 600;
}

.day-head {
  display: flex;
  align-items: baseline;
  gap: var(--lp-space-3);
  margin-bottom: var(--lp-space-2);
}

.day-no {
  font-family: var(--lp-font-display);
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--lp-accent);
}

.day-date,
.day-theme {
  font-size: 12.5px;
  color: var(--lp-text-muted);
}

.day-total {
  margin-left: auto;
  font-family: var(--lp-font-display);
  font-weight: 600;
  color: var(--lp-text-1);
  font-variant-numeric: tabular-nums;
}

.day-note {
  margin: 0 0 var(--lp-space-2);
  font-size: 13px;
  color: var(--lp-text-2);
}

.item-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
}

.item-row {
  display: flex;
  align-items: center;
  gap: var(--lp-space-3);
  padding: var(--lp-space-2) 0;
  border-bottom: 1px solid var(--lp-edge-faint);
}

.item-list li:last-child {
  border-bottom: none;
}

.item-img {
  width: 56px;
  height: 56px;
  object-fit: cover;
  border-radius: var(--lp-radius-input);
  flex: none;
}

.item-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.item-name {
  font-weight: 600;
  color: var(--lp-text-1);
}

.item-meta {
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-cost {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  color: var(--lp-text-2);
}

.plan-note {
  margin: 0;
  padding: 0 4px;
  font-size: 13px;
  color: var(--lp-text-muted);
}

.credit {
  margin: 0;
  padding: 0 4px;
  font-size: var(--lp-text-caption);
  color: var(--lp-text-faint);
}

.share-footer {
  padding: var(--lp-space-5) var(--lp-space-3) var(--lp-space-6);
  text-align: center;
}

.foot-note {
  margin: var(--lp-space-3) 0 0;
  font-size: var(--lp-text-caption);
  color: var(--lp-text-faint);
}
</style>

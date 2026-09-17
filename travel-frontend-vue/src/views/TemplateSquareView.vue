<template>
  <div class="template-square" :class="{ wide: true }">
    <header class="square-head">
      <h1>模板广场</h1>
      <p class="hint">把别人的行程骨架拿来改成自己的：使用模板后可继续 AI 改造。</p>
    </header>

    <p v-if="loadError" class="error">{{ loadError }} <button type="button" @click="load">重试</button></p>
    <p v-else-if="loading" class="hint">加载中…</p>
    <EmptyState v-else-if="templates.length === 0" title="还没有公开模板" description="发布一个行程，让更多人看到它" />

    <ul v-else class="card-list">
      <li v-for="card in templates" :key="card.id" class="card">
        <div class="cover" :style="card.coverUrl ? { backgroundImage: `url(${card.coverUrl})` } : undefined">
          <span v-if="!card.coverUrl" class="cover-fallback">{{ card.city }}</span>
        </div>
        <div class="card-body">
          <h3>{{ card.title }}</h3>
          <p class="meta">{{ card.city }} · {{ card.days }} 天</p>
          <ul class="tiers">
            <li v-for="tier in card.costTiers" :key="tier.category">{{ tier.amountRangeText }}</li>
          </ul>
          <div class="card-actions">
            <button type="button" @click="openDetail(card)">查看</button>
            <button type="button" class="primary" :disabled="forkingId === card.id" @click="onFork(card)">
              {{ forkingId === card.id ? '创建中…' : '使用这个模板' }}
            </button>
          </div>
        </div>
      </li>
    </ul>

    <!-- 只读详情投影 -->
    <AppSheet v-if="detailCard" v-model="detailVisible" direction="rtl" size="460px" :title="detailCard.title">
      <div v-if="detailLoading" class="hint pad">加载中…</div>
      <div v-else-if="detail" class="detail pad">
        <p class="hint">{{ detail.summary.intro }}</p>
        <ul class="tiers">
          <li v-for="tier in detail.summary.costTiers" :key="tier.category">{{ tier.amountRangeText }}</li>
        </ul>
        <ol class="days">
          <li v-for="day in detail.summary.dayList" :key="day.dayNo">
            <b>D{{ day.dayNo }} {{ day.theme || '' }}</b>
            <span class="hint">{{ (day.items || []).map((item) => item.poiName).join(' → ') }}</span>
          </li>
        </ol>
        <button type="button" class="primary" :disabled="forkingId === detail.id" @click="onFork(detailCard)">
          {{ forkingId === detail.id ? '创建中…' : '使用这个模板' }}
        </button>
      </div>
    </AppSheet>
  </div>
</template>

<script setup lang="ts">
/** 模板广场（C2.4）：卡片列表 → 只读投影详情 → fork 跳转新行程工作台。 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppSheet from '../components/ui/AppSheet.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import { toast } from '../components/ui/toast'
import { forkTemplate, getTemplate, listTemplates, type TemplateCardVO } from '../api/templates'
import type { TemplateDetailVO } from '../api/templates'

const router = useRouter()
const templates = ref<TemplateCardVO[]>([])
const loading = ref(false)
const loadError = ref('')
const detailVisible = ref(false)
const detail = ref<TemplateDetailVO | null>(null)
const detailLoading = ref(false)
const detailCard = ref<TemplateCardVO | null>(null)
const forkingId = ref<number | null>(null)

onMounted(load)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    templates.value = (await listTemplates()).data
  } catch {
    loadError.value = '模板广场加载失败'
  } finally {
    loading.value = false
  }
}

async function openDetail(card: TemplateCardVO) {
  detailCard.value = card
  detailVisible.value = true
  detailLoading.value = true
  try {
    detail.value = (await getTemplate(card.id)).data
  } catch {
    toast.error('详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

async function onFork(card: TemplateCardVO) {
  forkingId.value = card.id
  try {
    const forked = (await forkTemplate(card.id)).data
    toast.success('模板已复制到你的旅程，可让 AI 按你的偏好重排')
    await router.push(`/trips/${forked.itineraryId}?templateFork=1`)
  } catch {
    toast.error('使用模板失败，请重试')
  } finally {
    forkingId.value = null
  }
}
</script>

<style scoped>
.template-square {
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-width: 1080px;
  margin: 0 auto;
  padding: 24px 16px;
}
.square-head h1 {
  margin: 0 0 4px;
  font-size: 22px;
}
.hint {
  color: var(--lp-text-muted);
  font-size: 13px;
  margin: 0;
}
.error {
  color: var(--lp-danger);
}
.error button {
  border: none;
  background: none;
  color: inherit;
  text-decoration: underline;
  cursor: pointer;
}
.card-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}
.card {
  border: 1px solid var(--lp-border);
  border-radius: var(--lp-radius-card);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.cover {
  height: 132px;
  background-size: cover;
  background-position: center;
  background-color: var(--lp-bg);
  display: flex;
  align-items: center;
  justify-content: center;
}
.cover-fallback {
  font-size: 22px;
  font-weight: 600;
  color: var(--lp-text-muted);
}
.card-body {
  padding: 12px 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
}
.card-body h3 {
  margin: 0;
  font-size: 16px;
}
.meta {
  margin: 0;
  color: var(--lp-text-muted);
  font-size: 13px;
}
.tiers {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.tiers li {
  border: 1px solid var(--lp-border);
  border-radius: var(--lp-radius-pill);
  padding: 2px 10px;
  font-size: 12px;
}
.card-actions {
  margin-top: auto;
  display: flex;
  gap: 8px;
}
.card-actions button,
.pad button.primary {
  border: 1px solid var(--lp-border);
  background: var(--lp-bg);
  color: inherit;
  border-radius: var(--lp-radius-sm);
  padding: 6px 12px;
  cursor: pointer;
  font-size: 13px;
}
button.primary {
  border-color: var(--lp-accent);
  background: var(--lp-accent);
  color: var(--lp-accent-on-fill);
}
button.primary:disabled {
  opacity: 0.6;
  cursor: default;
}
.pad {
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.days {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
</style>

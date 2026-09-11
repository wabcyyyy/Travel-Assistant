<template>
  <section class="cover">
    <div class="cover-disc" aria-hidden="true"></div>
    <div class="cover-eyebrow">{{ detail.city }}</div>
    <h1 class="cover-title">{{ detail.title }}</h1>
    <p class="cover-sub">{{ detail.days }} 天 {{ detail.stayNights }} 晚 · {{ detail.persons }} 人</p>
    <div class="cover-chips">
      <span v-if="detail.startDate" class="cover-chip">{{ detail.startDate }} ~ {{ detail.endDate }}</span>
      <span v-if="detail.budget != null" class="cover-chip">预算 ￥{{ detail.budget }}</span>
      <span v-if="detail.hotelTier" class="cover-chip">住宿 {{ detail.hotelTier }}</span>
    </div>
    <div class="cover-actions">
      <el-button class="cover-btn-primary" :loading="exportingPdf" @click="$emit('export-pdf')">
        导出 PDF
      </el-button>
      <el-button :loading="exportingImg" @click="$emit('export-image')">导出图片</el-button>
      <el-button @click="$emit('similar')">新建相似行程</el-button>
      <el-button text @click="$emit('back')">返回</el-button>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { ItineraryDetail } from '../types/itinerary'

defineProps<{
  detail: ItineraryDetail
  exportingPdf?: boolean
  exportingImg?: boolean
}>()

defineEmits<{
  'export-pdf': []
  'export-image': []
  similar: []
  back: []
}>()
</script>

<style scoped>
.cover {
  position: relative;
  overflow: hidden;
  border-radius: 16px;
  padding: 44px 40px 36px;
  background: var(--lp-cover-gradient);
  color: #fffdf8;
  margin-bottom: 16px;
}

.cover-disc {
  position: absolute;
  right: -70px;
  bottom: -110px;
  width: 330px;
  height: 330px;
  border-radius: 50%;
  background: var(--lp-accent-warm);
  box-shadow: 0 0 100px rgb(226 139 92 / 22%);
  pointer-events: none;
}

.cover-eyebrow {
  margin: 0 0 14px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgb(255 253 248 / 72%);
}

.cover-title {
  margin: 0 0 10px;
  font-family: var(--lp-font-display);
  font-weight: 500;
  font-size: clamp(34px, 5vw, 52px);
  line-height: 1.12;
  letter-spacing: -0.03em;
  color: #fffdf8;
}

.cover-sub {
  margin: 0 0 18px;
  font-size: 14px;
  color: rgb(255 253 248 / 85%);
}

.cover-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.cover-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid rgb(255 255 255 / 28%);
  background: rgb(255 255 255 / 10%);
  font-size: 12.5px;
  font-weight: 600;
  color: #fffdf8;
  font-variant-numeric: tabular-nums;
}

.cover-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 22px;
}

.cover-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.cover-actions :deep(.el-button) {
  background: transparent;
  border: 1px solid rgb(255 255 255 / 35%);
  color: #fffdf8;
}

.cover-actions :deep(.el-button:hover) {
  background: rgb(255 255 255 / 16%);
  border-color: rgb(255 255 255 / 55%);
  color: #fff;
}

.cover-actions :deep(.cover-btn-primary) {
  background: var(--lp-accent);
  border-color: var(--lp-accent);
  color: #fff;
  font-weight: 700;
}

.cover-actions :deep(.cover-btn-primary:hover) {
  background: var(--lp-accent-hover);
  border-color: var(--lp-accent-hover);
  color: #fff;
}

.cover-actions :deep(.is-text) {
  border-color: transparent;
}

@media (max-width: 640px) {
  .cover {
    padding: 28px 20px 24px;
  }

  .cover-title {
    font-size: clamp(26px, 8vw, 34px);
  }

  .cover-disc {
    width: 180px;
    height: 180px;
    right: -40px;
    bottom: -60px;
  }
}
</style>

<template>
  <!-- 内联提示卡（v2.6 §19.3，TREK 式彩色小卡）：就地提示，不铺正文 -->
  <div v-if="hasTips" class="tip-stack">
    <InlineTipCard v-if="practicalNotes.length" kind="info" title="实用提示">
      <ul class="tip-list">
        <li v-for="(n, i) in practicalNotes" :key="i">{{ n }}</li>
      </ul>
    </InlineTipCard>
    <InlineTipCard v-if="photoSpots.length" kind="photo" title="拍照机位">
      <ul class="tip-list">
        <li v-for="(s, i) in photoSpots" :key="i">
          <span class="tip-strong">{{ spotName(s) }}</span>
          <span v-if="s.tip" class="tip-sub">{{ s.tip }}</span>
          <span v-if="s.bestTime" class="tip-time">{{ s.bestTime }}</span>
        </li>
      </ul>
    </InlineTipCard>
    <InlineTipCard v-if="backupRules.length" kind="warn" title="备选方案">
      <ul class="tip-list">
        <li v-for="(r, i) in backupRules" :key="i">
          <template v-if="(r.action || '').trim()">
            <span class="tip-strong">若{{ ruleIf(r) }}</span>
            <span class="tip-sub">{{ r.action }}</span>
          </template>
          <template v-else>{{ r.name || r.title }}</template>
        </li>
      </ul>
    </InlineTipCard>
  </div>
</template>

<script setup lang="ts">
/**
 * 日卡内联提示卡（实用提示 / 拍照机位 / 备选方案）——纯展示子组件。
 *
 * 数据清洗与字段兼容（name/title 历史键）在 day-card/shared.ts（有单测）；
 * 本组件只负责编排三张卡与排版。三块全空时整块不渲染（v-if hasTips）。
 */
import { computed } from 'vue'

import InlineTipCard from '../InlineTipCard.vue'
import {
  cleanBackupRules,
  cleanPhotoSpots,
  cleanPracticalNotes,
  hasAnyTips,
  ruleIf,
  spotName,
} from './shared'
import type { DayPlan } from '../../../types/itinerary'

const props = defineProps<{ day: DayPlan }>()

const practicalNotes = computed(() => cleanPracticalNotes(props.day.practicalNotes))
const photoSpots = computed(() => cleanPhotoSpots(props.day.photoSpots))
const backupRules = computed(() => cleanBackupRules(props.day.backupPlan))
const hasTips = computed(() => hasAnyTips(practicalNotes.value, photoSpots.value, backupRules.value))
</script>

<style scoped>
/* ---------- 内联提示卡（TREK 式彩色小卡）：内容排版由本层组织，基调色在 InlineTipCard ---------- */
.tip-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 0 14px;
}

.tip-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--lp-text-2);
}

.tip-strong {
  margin-right: 6px;
  font-weight: 600;
  color: var(--lp-text-1);
}

.tip-time {
  margin-left: 6px;
  font-family: var(--lp-font-mono);
  font-size: 11px;
  color: var(--lp-text-muted);
}
</style>

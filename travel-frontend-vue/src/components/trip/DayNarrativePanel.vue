<template>
  <div v-if="hasNarrative" class="day-narrative">
    <!-- note：本章导语正文（v2.6 W3：day_options 已迁日头「建议方案」弹层） -->
    <p v-if="day.note" class="narr-note">{{ day.note }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { DayPlan } from '../../types/itinerary'

// 每日叙事区（v2.6 §19.3 拆分后；W3 再迁 day_options）：仅保留 note 导语。
// practical/photo/backup → 日卡内联提示卡；day_options → 日头「建议方案」弹层。
const props = defineProps<{
  day: DayPlan
}>()

const hasNarrative = computed(() => !!(props.day.note || '').trim())
</script>

<style scoped>
.day-narrative {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  margin: 4px 0 16px;
}

.narr-note {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--lp-ink-soft);
}
</style>

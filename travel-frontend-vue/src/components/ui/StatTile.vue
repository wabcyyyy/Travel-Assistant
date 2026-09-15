<template>
  <div class="stat-tile" :class="`tone-${tone}`">
    <p class="tile-label">
      <span v-if="en" class="lp-micro label-en">{{ en }}</span>
      <span class="label-cn">{{ label }}</span>
    </p>
    <p class="tile-value">
      {{ value }}<span v-if="unit" class="tile-unit">{{ unit }}</span>
    </p>
    <p v-if="sub" class="tile-sub">{{ sub }}</p>
  </div>
</template>

<script setup lang="ts">
// 统计格（设计对齐 TREK）：微标签双语（大写英文 + 中文）、大数字带小号单位后缀；
// tone='ink' 是统计行里的深色「护照卡」，用来打破「四张同款卡」的规整感。
withDefaults(
  defineProps<{
    label: string
    /** 大写英文微标签（可选）：只用于统计/票根这类标签层，不铺正文 */
    en?: string
    value: string | number
    /** 值的小号单位后缀（段/天/项…） */
    unit?: string
    sub?: string
    tone?: 'default' | 'ink'
  }>(),
  { en: '', unit: '', sub: '', tone: 'default' },
)
</script>

<style scoped>
.stat-tile {
  padding: var(--lp-space-5);
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-card);
  background: var(--lp-surface-card);
}

.tone-ink {
  border-color: transparent;
  background: var(--lp-ink-card-bg);
  color: var(--lp-ink-card-ink);
}

.tile-label {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--lp-space-2);
  margin: 0;
}

.label-en {
  /* 规格来自全局 .lp-micro（大写英文微标签唯一来源），这里只覆盖卡片内的颜色 */
  color: var(--lp-text-muted);
}

.label-cn {
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
}

.tone-ink .label-en,
.tone-ink .label-cn {
  color: var(--lp-ink-card-muted);
}

.tile-value {
  margin: var(--lp-space-3) 0 0;
  font-size: 44px;
  font-weight: 800;
  line-height: 1.05;
  letter-spacing: -0.02em;
  color: var(--lp-text-1);
  font-variant-numeric: tabular-nums;
}

.tone-ink .tile-value {
  font-size: 52px;
  color: var(--lp-ink-card-ink);
}

.tile-unit {
  margin-left: 4px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0;
  color: var(--lp-text-muted);
}

.tone-ink .tile-unit {
  color: var(--lp-ink-card-muted);
}

.tile-sub {
  margin: var(--lp-space-2) 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--lp-text-muted);
}

.tone-ink .tile-sub {
  color: var(--lp-ink-card-muted);
}
</style>

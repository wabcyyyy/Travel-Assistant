<template>
  <div class="section-head">
    <div class="head-main">
      <h2 class="head-title lp-display">{{ title }}</h2>
      <p v-if="sub" class="head-sub">{{ sub }}</p>
    </div>
    <div v-if="$slots.actions" class="head-actions"><slot name="actions" /></div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ title: string; sub?: string }>()
</script>

<style scoped>
.section-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--lp-space-3);
  flex-wrap: wrap;
}

.head-title {
  margin: 0;
  font-family: var(--lp-font-display);
  font-size: var(--lp-text-display);
  font-weight: 600;
  letter-spacing: -0.035em;
  line-height: 1.02;
  color: var(--lp-text-1);
  font-variant-numeric: tabular-nums;
}

.head-sub {
  margin: 8px 0 0;
  font-size: 14px;
  color: var(--lp-text-muted);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
}
</style>

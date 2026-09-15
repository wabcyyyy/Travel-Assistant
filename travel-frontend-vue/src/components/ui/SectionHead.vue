<template>
  <div class="section-head">
    <div class="head-main">
      <h2 class="head-title">{{ title }}</h2>
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
  font-size: var(--lp-text-title);
  font-weight: 800;
  letter-spacing: -0.01em;
  color: var(--lp-text-1);
}

.head-sub {
  margin: var(--lp-space-1) 0 0;
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
}
</style>

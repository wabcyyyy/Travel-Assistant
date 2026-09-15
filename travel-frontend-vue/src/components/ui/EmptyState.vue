<template>
  <div class="empty-state">
    <p class="empty-desc">{{ description }}</p>
    <div v-if="$slots.default" class="empty-actions"><slot /></div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ description: string }>()
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--lp-space-3);
  padding: var(--lp-space-6) var(--lp-space-4);
  text-align: center;
}

.empty-desc {
  margin: 0;
  font-size: 13px;
  color: var(--lp-text-muted);
}

.empty-actions {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
}
</style>

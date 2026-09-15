<template>
  <span class="chip" :class="`tone-${tone}`"><slot /></span>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{ tone?: 'neutral' | 'accent' | 'success' | 'warning' | 'danger' }>(),
  { tone: 'neutral' },
)
</script>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: var(--lp-radius-pill);
  font-size: var(--lp-text-caption);
  font-weight: 600;
  white-space: nowrap;
}

.tone-neutral {
  background: var(--lp-surface-2);
  color: var(--lp-text-2);
}

.tone-accent {
  background: var(--lp-accent-subtle);
  color: var(--lp-accent-hover);
}

.tone-success {
  background: var(--lp-success-soft);
  color: var(--lp-success);
}

.tone-warning {
  background: var(--lp-warning-soft);
  color: var(--lp-warning);
}

.tone-danger {
  background: var(--lp-danger-soft);
  color: var(--lp-danger);
}
</style>

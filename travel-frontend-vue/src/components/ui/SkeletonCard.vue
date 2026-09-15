<template>
  <div class="skeleton-card" :style="{ minHeight: height }" aria-hidden="true">
    <span class="lp-skel-line line is-40" />
    <span class="lp-skel-line line is-90" />
    <span class="lp-skel-line line is-70" />
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ height?: string }>(), { height: '96px' })
</script>

<style scoped>
.skeleton-card {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--lp-space-2);
  padding: var(--lp-space-4);
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-card);
  background: var(--lp-surface-card);
}

.line {
  height: 12px;
}

.is-40 {
  width: 40%;
}

.is-90 {
  width: 90%;
}

.is-70 {
  width: 70%;
}
</style>

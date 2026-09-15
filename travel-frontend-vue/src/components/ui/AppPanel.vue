<template>
  <section class="app-panel" :class="{ 'is-flat': flat }">
    <header v-if="title || $slots.actions" class="panel-head">
      <h3 v-if="title" class="panel-title">{{ title }}</h3>
      <div v-if="$slots.actions" class="panel-actions"><slot name="actions" /></div>
    </header>
    <slot />
  </section>
</template>

<script setup lang="ts">
defineProps<{
  title?: string
  /** 无边框无底色：用于需要嵌在既有卡片里的场景 */
  flat?: boolean
}>()
</script>

<style scoped>
.app-panel {
  padding: var(--lp-space-4);
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-card);
  background: var(--lp-surface-card);
}

.app-panel.is-flat {
  padding: 0;
  border: none;
  background: transparent;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--lp-space-3);
  margin-bottom: var(--lp-space-3);
}

.panel-title {
  margin: 0;
  font-size: var(--lp-text-subtitle);
  font-weight: 700;
  color: var(--lp-text-1);
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
}
</style>

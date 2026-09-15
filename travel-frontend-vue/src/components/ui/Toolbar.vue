<template>
  <div class="toolbar"><slot /></div>
</template>

<script setup lang="ts">
/** 行内工具条：搜索框 / 筛选 chips / 右侧动作的统一节奏（换行不塌陷）。 */
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
  flex-wrap: wrap;
}
</style>

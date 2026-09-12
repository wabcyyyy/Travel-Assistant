<template>
  <p v-if="text" class="why-line" tabindex="0">
    <span class="why-tag">为何在此</span>
    <span class="why-text">{{ text }}</span>
  </p>
</template>

<script setup lang="ts">
import { computed } from 'vue'

// why_this 次级行（M4-②b §5.3.3）：默认展示、不折叠（与 poi-desc 的 60 字折叠刻意区分：
// why_this 是本趟意图与该点的差异化关系，首屏即时可见）。正文 0.85em + --lp-why-ink 注释感；
// 最多两行截断，hover / focus（键盘可达）展开全文。空值整行静默不渲染。
const props = defineProps<{
  whyThis?: string | null
}>()

const text = computed(() => (props.whyThis || '').trim())
</script>

<style scoped>
.why-line {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 6px 0 0;
  font-size: 0.85em;
  line-height: 1.65;
  color: var(--lp-why-ink);
  cursor: default;
}

.why-tag {
  flex: none;
  font-family: var(--lp-font-data);
  font-size: 11px;
  letter-spacing: 0.08em;
}

.why-text {
  min-width: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}

/* hover / 键盘 focus 展开全文（替代 tooltip，焦点环由全局 :focus-visible 提供） */
.why-line:hover .why-text,
.why-line:focus-visible .why-text {
  display: block;
  -webkit-line-clamp: unset;
  line-clamp: unset;
  overflow: visible;
}
</style>

<template>
  <div class="segmented" role="radiogroup" :aria-label="ariaLabel">
    <button
      v-for="(item, index) in items"
      :key="item.value"
      :ref="(el) => setItemRef(el, index)"
      type="button"
      role="radio"
      class="seg-item"
      :class="{ 'is-active': model === item.value }"
      :aria-checked="model === item.value ? 'true' : 'false'"
      :tabindex="model === item.value ? 0 : -1"
      @click="selectAt(index)"
      @keydown.left.prevent="move(index, -1)"
      @keydown.right.prevent="move(index, 1)"
      @keydown.home.prevent="selectAt(0)"
      @keydown.end.prevent="selectAt(items.length - 1)"
    >
      {{ item.label
      }}<span v-if="item.badge !== undefined && item.badge !== ''" class="seg-badge">{{ item.badge }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

// 胶囊分段控件（v2.6 §19.2，替换 el-radio-button/el-radio-group）：view 筛选、分类页签等。
// 语义 = radiogroup/radio；←→ 移动并选中、Home/End 到端点（选中项保持唯一 tab 停靠点）。
const model = defineModel<string>({ required: true })
const props = defineProps<{
  items: { value: string; label: string; badge?: number | string }[]
  ariaLabel?: string
}>()

const buttons = ref<(HTMLButtonElement | null)[]>([])

function setItemRef(el: unknown, index: number): void {
  buttons.value[index] = el instanceof HTMLButtonElement ? el : null
}

function selectAt(index: number): void {
  const item = props.items[index]
  if (!item) return
  model.value = item.value
  buttons.value[index]?.focus()
}

function move(index: number, step: number): void {
  selectAt((index + step + props.items.length) % props.items.length)
}
</script>

<style scoped>
.segmented {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: var(--lp-radius-pill);
  background: var(--lp-surface-2);
}

.seg-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: none;
  border-radius: var(--lp-radius-pill);
  background: transparent;
  color: var(--lp-text-muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
}

.seg-item:hover {
  color: var(--lp-text-1);
}

.seg-item.is-active {
  background: var(--lp-surface-elevated);
  color: var(--lp-text-1);
  box-shadow: var(--lp-shadow-xs);
}

.seg-badge {
  font-family: var(--lp-font-mono);
  font-size: 11px;
  color: var(--lp-text-muted);
}

.seg-item.is-active .seg-badge {
  color: var(--lp-text-2);
}
</style>

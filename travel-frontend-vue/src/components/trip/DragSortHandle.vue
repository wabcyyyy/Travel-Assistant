<template>
  <span class="drag-sort-wrap" @focusout="closeMenuOnBlur">
    <span
      :id="`drag-handle-${item.id}`"
      class="drag-handle"
      role="button"
      tabindex="0"
      aria-label="拖拽排序"
      title="拖拽排序"
      aria-haspopup="menu"
      :aria-expanded="menuFor ? 'true' : 'false'"
      @keydown.enter.prevent="toggleMenu"
      @keydown.space.prevent="toggleMenu"
      @keydown.up.prevent="move(-1)"
      @keydown.down.prevent="move(1)"
      @keydown.esc.prevent="closeMenu"
    ><GripVertical :size="13" :stroke-width="1.8" /></span>
    <span
      v-if="menuFor"
      :id="`drag-menu-${item.id}`"
      class="drag-menu"
      role="menu"
      aria-label="键盘排序"
      @keydown.esc.prevent="closeMenuTo"
    >
      <button type="button" role="menuitem" :disabled="index === 0" @click="move(-1)">
        上移
      </button>
      <button
        type="button"
        role="menuitem"
        :disabled="index === total - 1"
        @click="move(1)"
      >
        下移
      </button>
    </span>
  </span>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { GripVertical } from 'lucide-vue-next'
import type { DayPlan, TripItem } from '../../types/itinerary'

// 拖拽手柄 + 键盘排序替代（§5.5 a11y #1/#2，M4-②b 自 DayListCard 迁出以瘦身）：
// 手柄为独立 role=button；Enter/Space 打开「上移/下移」菜单，方向键直接移动，鼠标拖拽不受影响。
// 移动为乐观本地变更（直接改 day.items），经 moved 事件交父级走 item-drop 统一持久化路径。
const props = defineProps<{
  day: DayPlan
  item: TripItem
  index: number
  total: number
}>()

const emit = defineEmits<{
  moved: [day: DayPlan]
}>()

const menuFor = ref(false)

async function toggleMenu() {
  if (menuFor.value) {
    closeMenu()
    return
  }
  menuFor.value = true
  await nextTick()
  document
    .getElementById(`drag-menu-${props.item.id}`)
    ?.querySelector<HTMLButtonElement>('button:not(:disabled)')
    ?.focus()
}

function closeMenu() {
  menuFor.value = false
}

async function closeMenuTo() {
  closeMenu()
  await nextTick()
  document.getElementById(`drag-handle-${props.item.id}`)?.focus()
}

function closeMenuOnBlur(event: FocusEvent) {
  if (!(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node)) closeMenu()
}

/** 键盘上移/下移：焦点跟随到新位置的手柄，支持连续键盘排序 */
async function move(offset: -1 | 1) {
  const items = props.day.items
  const target = props.index + offset
  if (target < 0 || target >= items.length) return
  items.splice(props.index, 1)
  items.splice(target, 0, props.item)
  closeMenu()
  emit('moved', props.day)
  await nextTick()
  document.getElementById(`drag-handle-${props.item.id}`)?.focus()
}
</script>

<style scoped>
.drag-sort-wrap {
  position: relative;
  display: inline-flex;
}

/* TREK 行解剖（v2.7 §20 R3）：抓手 13px、常态 opacity .3，行 hover 时亮起（见 DayListCard） */
.drag-handle {
  display: inline-flex;
  align-items: center;
  cursor: grab;
  color: var(--lp-text-faint);
  padding: 4px;
  border-radius: var(--lp-radius-xs);
}

.drag-handle:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: 1px;
  color: var(--lp-accent);
}

/* 键盘排序菜单：仅在键盘激活手柄后出现，鼠标拖拽交互不受影响 */
.drag-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 50%;
  transform: translateX(-50%);
  z-index: 20;
  display: flex;
  flex-direction: column;
  min-width: 76px;
  padding: 4px;
  background: #fff;
  border: 1px solid var(--lp-border);
  border-radius: 8px;
  box-shadow: var(--lp-shadow-sm);
}

.drag-menu button {
  border: none;
  background: transparent;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--lp-ink);
  text-align: left;
  cursor: pointer;
}

.drag-menu button:hover:not(:disabled) {
  background: var(--lp-accent-soft);
  color: var(--lp-accent);
}

.drag-menu button:disabled {
  color: var(--lp-muted);
  opacity: 0.6;
  cursor: not-allowed;
}
</style>

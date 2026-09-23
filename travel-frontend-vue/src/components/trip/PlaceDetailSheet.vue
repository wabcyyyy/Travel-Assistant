<template>
  <section v-if="item" class="place-sheet" role="dialog" aria-label="点位详情">
    <button type="button" class="sheet-close" aria-label="关闭" @click="emit('close')">
      <X :size="16" />
    </button>
    <div class="sheet-head">
      <div class="sheet-img">
        <img v-if="photoSrc" :src="photoSrc" :alt="item.poiName" @error="onImgError(item)" />
        <span v-else class="img-fallback">{{ typeLabel }}</span>
      </div>
      <div class="sheet-title">
        <p class="name-row">
          <span class="name">{{ item.poiName }}</span>
          <span class="type-chip">{{ typeLabel }}</span>
          <EvidenceBadge :item="item" />
        </p>
        <p class="addr">{{ item.address || '暂无地址' }}</p>
        <p v-if="hasCoord" class="coords">{{ coordText }}</p>
      </div>
    </div>

    <div class="sheet-meta">
      <span v-if="item.startTime" class="meta-item">
        时间 {{ formatTime(item.startTime) }}<template v-if="item.endTime"> - {{ formatTime(item.endTime) }}</template>
      </span>
      <span v-if="item.durationMin" class="meta-item">约 {{ item.durationMin }} 分钟</span>
      <span class="meta-item">参考费用 {{ costText }}</span>
      <span v-if="item.tag" class="meta-item">{{ item.tag }}</span>
    </div>

    <p v-if="item.intro || item.description || item.whyThis" class="sheet-desc">
      <template v-if="item.intro || item.description">{{ item.intro || item.description }}</template><span v-if="item.whyThis" class="why">{{ item.whyThis }}</span>
    </p>
    <p v-if="item.remark" class="sheet-remark">备注：{{ item.remark }}</p>

    <ItemFeedbackPanel :item="item" />

    <div class="sheet-actions">
      <button type="button" class="act" @click="emit('edit', item)">编辑</button>
      <button type="button" class="act" @click="emit('move', item)">加入其他天</button>
      <button type="button" class="act is-danger" @click="emit('delete', item)">删除</button>
      <a class="act is-link" :href="link" target="_blank" rel="noopener">
        打开链接<ExternalLink :size="13" />
      </a>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { ExternalLink, X } from 'lucide-vue-next'

import { useItineraryStore } from '../../store/itinerary'
import { useItemPhoto } from '../../composables/useItemPhoto'
import { externalMapLink, hasValidCoordinates } from '../../utils/geo'
import { typeLabel as typeLabelOf } from './day-card/shared'
import EvidenceBadge from './EvidenceBadge.vue'
import ItemFeedbackPanel from './ItemFeedbackPanel.vue'
import type { TripItem } from '../../types/itinerary'

// 贴底浮层详情卡（v2.6 §19.3，TREK 式）：选中站点/图钉 → 悬浮于中栏地图上。
// 非模态：不锁滚动、不圈焦点；X / Esc / 点地图空白（壳监听 TripMapPanel 的 clear）关闭。
// 操作行：编辑（更多字段对话框）/ 加入其他天（跨天移动）/ 删除 / 打开链接（统一口径 geo.externalMapLink）。
// 「移出当天」无「退回未排池」后端能力，本轮不做（不造 UI）。
const props = defineProps<{ item: TripItem | null }>()
const emit = defineEmits<{
  close: []
  edit: [item: TripItem]
  move: [item: TripItem]
  delete: [item: TripItem]
}>()

const store = useItineraryStore()
const { detail } = storeToRefs(store)
const { imgSrc, onImgError } = useItemPhoto()

// 类型标签走全站唯一口径（R5-3）；无点位时回落「点位」占位
const typeLabel = computed(() => {
  const type = props.item?.itemType
  return type ? typeLabelOf(type) : '点位'
})

const hasCoord = computed(() => !!props.item && hasValidCoordinates(props.item))

const coordText = computed(() => {
  const it = props.item
  return it ? `${Number(it.latitude).toFixed(4)}, ${Number(it.longitude).toFixed(4)}` : ''
})

const photoSrc = computed(() => (props.item ? imgSrc(props.item) : ''))

const link = computed(() =>
  props.item
    ? externalMapLink(
        { name: props.item.poiName, latitude: props.item.latitude, longitude: props.item.longitude },
        detail.value?.city,
      )
    : '#',
)

const costText = computed(() => {
  const it = props.item
  if (!it || it.cost == null) return '未填'
  return `￥${it.cost}${it.itemType === 'hotel' ? '/晚/间' : '/人'}`
})

function formatTime(value?: string | null): string {
  return typeof value === 'string' ? value.slice(0, 5) : ''
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') emit('close')
}

watch(
  () => props.item,
  (item) => {
    document.removeEventListener('keydown', onKeydown)
    if (item) document.addEventListener('keydown', onKeydown)
  },
  { immediate: true },
)

onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
/* 详情卡：居中于地图可见走廊（v2.7 §20 R3，TREK DayDetailPanel 的定位语义），
   面板收起/拖宽时跟随移动——走廊变量由详情壳写在祖先上，移动壳里默认为 0。 */
.place-sheet {
  position: absolute;
  left: calc(
    var(--lp-corridor-left, 0px) +
      (100% - var(--lp-corridor-left, 0px) - var(--lp-corridor-right, 0px)) / 2
  );
  transform: translateX(-50%);
  width: min(800px, calc(100% - var(--lp-corridor-left, 0px) - var(--lp-corridor-right, 0px) - 32px));
  bottom: 20px;
  z-index: var(--lp-z-sticky);
  padding: 14px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-card);
  background: var(--lp-surface-elevated);
  box-shadow: var(--lp-shadow-lg);
  transition: left 0.25s ease, width 0.25s ease;
}

.sheet-close {
  position: absolute;
  top: 10px;
  right: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: var(--lp-radius-xs);
  background: transparent;
  color: var(--lp-text-muted);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.sheet-close:hover {
  background: var(--lp-surface-hover);
  color: var(--lp-text-1);
}

.sheet-head {
  display: flex;
  gap: 12px;
}

.sheet-img {
  flex: none;
  width: 72px;
  height: 72px;
  border-radius: var(--lp-radius-sm);
  overflow: hidden;
  background: var(--lp-surface-2);
}

.sheet-img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.img-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--lp-accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.sheet-title {
  flex: 1;
  min-width: 0;
  padding-right: 24px;
}

.name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
}

.name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--lp-font-display);
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--lp-text-1);
}

.type-chip {
  flex: none;
  padding: 1px 8px;
  border-radius: var(--lp-radius-pill);
  background: var(--lp-accent-subtle);
  color: var(--lp-accent-hover);
  font-size: 11px;
  font-weight: 600;
}

.addr {
  margin: 4px 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--lp-text-muted);
}

.coords {
  margin: 3px 0 0;
  font-family: var(--lp-font-mono);
  font-size: 11px;
  color: var(--lp-text-faint);
}

.sheet-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  margin-top: 10px;
}

.meta-item {
  padding: 2px 8px;
  border-radius: var(--lp-radius-pill);
  background: var(--lp-surface-2);
  font-size: 11.5px;
  color: var(--lp-text-2);
  font-variant-numeric: tabular-nums;
}

.sheet-desc {
  margin: 10px 0 0;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--lp-text-2);
}

.why {
  margin-left: 0.35em;
  color: var(--lp-text-muted);
}

.sheet-remark {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--lp-text-muted);
}

.sheet-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--lp-edge-faint);
}

.act {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-xs);
  background: var(--lp-surface-card);
  color: var(--lp-text-2);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.act:hover {
  color: var(--lp-accent);
  border-color: var(--lp-accent);
}

.act.is-danger:hover {
  color: var(--lp-danger);
  border-color: var(--lp-danger);
}

.act.is-link {
  margin-left: auto;
}
</style>

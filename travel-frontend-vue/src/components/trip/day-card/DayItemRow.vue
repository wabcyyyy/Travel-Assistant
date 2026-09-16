<template>
          <div :id="`item-${item.id}`" :data-item-id="item.id" class="row-wrap">
            <!-- 站间分隔条（v2.7 §20 R3，TREK 的「6h5min · 27.5km」等价物）：
                 本地直线估算 + 明确标注，缺坐标不画 -->
            <div v-if="leg" class="leg-row" :title="LEG_HINT">
              <span class="leg-line" aria-hidden="true"></span>
              <component
                :is="leg?.mode === 'walk' ? Footprints : Car"
                :size="10"
                :stroke-width="2"
                aria-hidden="true"
              />
              <span class="leg-text">{{ legText(leg) }}</span>
              <span class="leg-line" aria-hidden="true"></span>
            </div>
            <div
              class="route-row"
              :class="{ highlighted }"
              role="button"
              tabindex="0"
              :aria-label="`行程点位：${item.poiName}`"
              @click="emit('item-select', item)"
              @keydown.enter.prevent="emit('item-select', item)"
            >
              <input
                type="checkbox"
                class="row-check"
                :checked="selected"
                :aria-label="`选择「${item.poiName}」`"
                @click.stop
                @change="emit('toggle-select', item)"
              />
              <DragSortHandle
                class="row-grip"
                :day="day"
                :item="item"
                :index="index"
                :total="(day.items || []).length"
                @moved="emit('item-drop', $event)"
              />
              <!-- 28px 圆头像（TREK 行解剖）：缩略图失败落分类字块；左上角压天内序号 -->
              <span class="row-avatar">
                <img
                  v-if="imgLevel(item) < 2 && imgSrc(item)"
                  :src="imgSrc(item)"
                  :alt="item.poiName"
                  loading="lazy"
                  @error="onImgError(item)"
                />
                <span v-else class="row-avatar-fallback" aria-hidden="true">
                  {{ typeLabel(item.itemType).slice(0, 1) }}
                </span>
                <i class="stop-badge" aria-hidden="true">{{ index + 1 }}</i>
              </span>
              <div class="row-main">
                <div class="row-top">
                  <!-- 分类小图标 10px + 名称 12.5px/500 + 时间 10px 文本（点开即改，不再常显 chip） -->
                  <component
                    :is="typeIcon(item.itemType)"
                    class="row-type-icon"
                    :size="10"
                    :stroke-width="2"
                    aria-hidden="true"
                  />
                  <span class="row-name">{{ item.poiName }}</span>
                  <span class="qe-wrap" @click.stop>
                    <AppPopover
                      :open="quickEdit?.id === item.id && quickEdit?.field === 'time'"
                      :label="`编辑「${item.poiName}」的时间`"
                      align="start"
                      @update:open="(open) => syncQuick(item, 'time', open)"
                    >
                      <template #trigger>
                        <button v-if="item.startTime" type="button" class="row-time" title="编辑时间">
                          <Clock :size="9" :stroke-width="2" />
                          {{ formatTime(item.startTime) }}<template v-if="item.endTime"> – {{ formatTime(item.endTime) }}</template>
                        </button>
                        <button v-else type="button" class="row-time is-empty" title="添加时间">加时间</button>
                      </template>
                      <div class="qe-body">
                        <label class="qe-label">
                          开始时间
                          <AppInput v-model="timeDraft" type="time" aria-label="开始时间" />
                        </label>
                        <label class="qe-label">
                          时长（分钟）
                          <AppNumberInput v-model="durDraft" :min="0" aria-label="时长" />
                        </label>
                        <button type="button" class="qe-save" @click="saveTime(item)">保存</button>
                      </div>
                    </AppPopover>
                  </span>
                </div>
                <!-- 描述行：10px 单行省略（全文见贴底详情卡）；无描述落地址 -->
                <p v-if="item.intro || item.description || item.address" class="row-desc">
                  {{ item.intro || item.description || item.address }}
                </p>
                <!-- 备注行：10px + StickyNote 9px 单行 -->
                <p v-if="item.remark" class="row-remark">
                  <StickyNote :size="9" :stroke-width="2" aria-hidden="true" />
                  <span>{{ item.remark }}</span>
                </p>
              </div>
              <span class="qe-wrap row-cost-wrap" @click.stop>
                <AppPopover
                  :open="quickEdit?.id === item.id && quickEdit?.field === 'cost'"
                  :label="`编辑「${item.poiName}」的费用`"
                  align="end"
                  @update:open="(open) => syncQuick(item, 'cost', open)"
                >
                  <template #trigger>
                    <button v-if="item.cost != null" type="button" class="row-cost" title="编辑费用">
                      ￥{{ item.cost }}
                    </button>
                    <button v-else type="button" class="row-cost is-empty" title="添加费用">￥—</button>
                  </template>
                  <div class="qe-body">
                    <label class="qe-label">
                      费用（￥{{ item.itemType === 'hotel' ? '每晚每间' : '每人' }}）
                      <AppNumberInput v-model="costDraft" :min="0" :precision="2" aria-label="费用" />
                    </label>
                    <button type="button" class="qe-save" @click="saveCost(item)">保存</button>
                  </div>
                </AppPopover>
              </span>
              <!-- 行操作：hover/聚焦才现身（TREK 的「悬停出操作」语义），图标 16px -->
              <div class="row-actions">
                <a
                  class="row-icon"
                  :href="mapLinkOf(item)"
                  target="_blank"
                  rel="noopener"
                  :title="mapLinkLabel"
                  :aria-label="mapLinkLabel"
                  @click.stop
                >
                  <ExternalLink :size="16" />
                </a>
                <button
                  type="button"
                  class="row-icon"
                  title="移至其他天"
                  aria-label="移至其他天"
                  @click.stop="emit('move-request', item)"
                >
                  <ArrowRightLeft :size="16" />
                </button>
                <button
                  type="button"
                  class="row-icon"
                  title="编辑详情"
                  aria-label="编辑详情"
                  @click.stop="emit('edit-request', item)"
                >
                  <Pencil :size="16" />
                </button>
                <button
                  type="button"
                  class="row-icon is-danger"
                  title="删除"
                  aria-label="删除"
                  @click.stop="onDeleteItem(item)"
                >
                  <Trash2 :size="16" />
                </button>
              </div>
            </div>
          </div>
</template>

<script setup lang="ts">
// 行程条目行（DayListCard 拆分④）：头像 / 名称 / 时间与费用的行内快捷编辑 /
// hover 操作簇 / 站间交通分隔条。
//
// 交互语义：
// - toggle-select / item-select / move-request / edit-request / item-drop
//   全部上抛，由日卡壳（DayListCard）统一落库——本组件不直接改行程数据，删除
//   除外（deleteItem 带 confirmDialog，行为与迁移前一致）；
// - 快捷编辑（useQuickEdit）：同时只开一个编辑器，保存走全量 PUT 载荷；
// - leg 由父级按上一条目估算（本条目为当天首条时为 null，不渲染分隔条）。
import { ArrowRightLeft, Car, Clock, ExternalLink, Footprints, Pencil, StickyNote, Trash2 } from 'lucide-vue-next'
import { computed } from 'vue'
import { storeToRefs } from 'pinia'

import AppInput from '../../ui/AppInput.vue'
import AppNumberInput from '../../ui/AppNumberInput.vue'
import AppPopover from '../../ui/AppPopover.vue'
import { confirmDialog } from '../../ui/confirm'
import { toast } from '../../ui/toast'
import DragSortHandle from '../DragSortHandle.vue'
import { formatTime, typeIcon, typeLabel } from './shared'
import { useQuickEdit } from './useQuickEdit'
import { useItineraryActions } from '../../../composables/useItineraryActions'
import { useItemPhoto } from '../../../composables/useItemPhoto'
import { useItineraryStore } from '../../../store/itinerary'
import { externalMapLink, isForeignCity } from '../../../utils/geo'
import { legText, type TravelLeg } from '../../../utils/travelEstimate'
import type { DayPlan, TripItem } from '../../../types/itinerary'

defineProps<{
  item: TripItem
  index: number
  day: DayPlan
  leg: TravelLeg | null
  selected: boolean
  highlighted: boolean
}>()

const emit = defineEmits<{
  'toggle-select': [item: TripItem]
  'item-drop': [day: DayPlan]
  'item-select': [item: TripItem]
  'move-request': [item: TripItem]
  'edit-request': [item: TripItem]
}>()

const { detail } = storeToRefs(useItineraryStore())
const actions = useItineraryActions()
const { imgLevel, imgSrc, onImgError } = useItemPhoto()
const { quickEdit, timeDraft, durDraft, costDraft, syncQuick, saveTime, saveCost } = useQuickEdit(actions)

const LEG_HINT = '本地直线估算（含路网折算，非实时路况）'

const detailForeign = computed(() => isForeignCity(detail.value?.city ?? ''))
const mapLinkLabel = computed(() => (detailForeign.value ? '谷歌地图' : '高德地图'))

/** 地图外链：统一口径在 utils/geo（国内高德搜索 / 海外 Google Maps，有坐标优先） */
function mapLinkOf(item: TripItem) {
  return externalMapLink(
    { name: item.poiName, latitude: item.latitude, longitude: item.longitude },
    detail.value?.city,
  )
}

async function onDeleteItem(item: TripItem) {
  const ok = await confirmDialog(`确认删除「${item.poiName}」？`, { title: '删除确认', confirmText: '删除' })
  if (!ok) return
  await actions.deleteItem(item.id!)
  toast.success('已删除')
}
</script>

<style scoped>
.row-wrap {
  border-radius: var(--lp-radius-xs);
}

.leg-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 12px;
  color: var(--lp-text-faint);
  font-size: 9.5px;
  font-variant-numeric: tabular-nums;
  pointer-events: none;
}

.leg-line {
  flex: 1;
  border-top: 1px dashed var(--lp-edge-2);
}

.leg-text {
  flex: none;
  white-space: nowrap;
}

/* ---------- 站点行（v2.7 §20 R3 照抄 TREK DayPlanSidebar 行解剖） ----------
   一条横长条：勾选 + 抓手 + 28px 圆头像 + 名称/时间/描述/备注三行文本 + 费用；
   hover 出 16px 图标操作列（地图外链 / 移至 / 编辑 / 删除） */
.route-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  scroll-margin-top: 84px;
  padding: 7px 8px 7px 10px;
  border-left: 3px solid transparent;
  border-radius: var(--lp-radius-xs);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.route-row:hover {
  background: var(--lp-surface-hover);
}

.route-row:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: -2px;
}

.route-row.highlighted {
  background: var(--lp-surface-selected);
  border-left-color: var(--lp-accent);
}

/* 拖拽入天落点提示：整卡虚线描边（dragover 期间） */
.day-panel.is-drop-over > summary {
  outline: 2px dashed var(--lp-accent);
  outline-offset: -2px;
}

.row-check {
  flex: none;
  width: 14px;
  height: 14px;
  margin: 0;
  accent-color: var(--lp-accent);
  cursor: pointer;
  opacity: 0.5;
  transition: opacity 0.15s;
}

.route-row:hover .row-check,
.row-check:checked {
  opacity: 1;
}

/* 抓手：常态 0.3 亮度，行 hover/聚焦才亮起（TREK 同款） */
.row-grip {
  flex: none;
  opacity: 0.3;
  transition: opacity 0.15s;
}

.route-row:hover .row-grip,
.route-row:focus-within .row-grip {
  opacity: 1;
}

/* 28px 圆头像；缩略图失败落分类字块；左上角压天内序号（与地图图钉同号） */
.row-avatar {
  position: relative;
  flex: none;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  overflow: visible;
  background: var(--lp-surface-2);
}

.row-avatar img {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  display: block;
}

.row-avatar-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: color-mix(in oklch, var(--day-color) var(--lp-day-tint-badge), transparent);
  color: color-mix(in oklch, var(--day-color) 75%, var(--lp-text-1));
  font-size: 11px;
  font-weight: 700;
}

/* 编号徽（day-tint badge 档，与日头徽/地图图钉同源） */
.stop-badge {
  position: absolute;
  top: -4px;
  left: -4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 15px;
  height: 15px;
  padding: 0 3px;
  border-radius: var(--lp-radius-pill);
  background: var(--lp-surface-card);
  color: color-mix(in oklch, var(--day-color) 75%, var(--lp-text-1));
  box-shadow: 0 0 0 1.5px color-mix(in oklch, var(--day-color) var(--lp-day-tint-badge), transparent);
  font-family: var(--lp-font-mono);
  font-size: 9px;
  font-style: normal;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.row-main {
  flex: 1;
  min-width: 0;
}

.row-top {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.row-type-icon {
  flex: none;
  color: var(--lp-text-muted);
}

.row-name {
  font-family: var(--lp-font-body);
  font-weight: 500;
  font-size: 12.5px;
  line-height: 1.2;
  color: var(--lp-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 时间 10px 纯文本（v2.7 §20 R3：不再常显 chip），点开即改 */
.row-time {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: 6px;
  padding: 0;
  border: none;
  background: none;
  color: var(--lp-text-faint);
  font-family: inherit;
  font-size: 10px;
  font-weight: 400;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}

.row-time:hover {
  color: var(--lp-text-1);
}

.row-time.is-empty {
  color: var(--lp-text-faint);
  opacity: 0.75;
}

/* 描述行：10px 单行省略（全文在贴底详情卡） */
.row-desc {
  margin: 2px 0 0;
  max-height: 1.2em;
  font-size: 10px;
  line-height: 1.2;
  color: var(--lp-text-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 备注行：10px + StickyNote 9px（TREK 同款单行） */
.row-remark {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 2px 0 0;
  font-size: 10px;
  line-height: 1.2;
  color: var(--lp-text-faint);
  overflow: hidden;
}

.row-remark span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-cost-wrap {
  flex: none;
  margin-left: auto;
}

.row-cost {
  padding: 0;
  border: none;
  background: none;
  color: var(--lp-text-muted);
  font-family: var(--lp-font-mono);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}

.row-cost:hover {
  color: var(--lp-text-1);
}

.row-cost.is-empty {
  opacity: 0.6;
}

/* 行操作：默认隐去，hover/聚焦浮出行尾；底衬淡出避免压字 */
.row-actions {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 0 8px 0 18px;
  border-radius: 0 var(--lp-radius-xs) var(--lp-radius-xs) 0;
  background: linear-gradient(
    to right,
    transparent,
    var(--lp-surface-hover) 24%,
    var(--lp-surface-hover)
  );
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
}

.route-row:hover .row-actions,
.route-row:focus-within .row-actions {
  opacity: 1;
  pointer-events: auto;
}

.route-row.highlighted:hover .row-actions {
  background: linear-gradient(
    to right,
    transparent,
    var(--lp-surface-selected) 24%,
    var(--lp-surface-selected)
  );
}

.row-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--lp-radius-xs);
  background: transparent;
  color: var(--lp-text-muted);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.row-icon:hover {
  background: var(--lp-surface-card);
  color: var(--lp-text-1);
}

.row-icon.is-danger:hover {
  color: var(--lp-danger);
}

/* ---------- 日尾添加地点（整行虚线钮；打开右栏「发现」并预设目标天） ---------- */

.qe-wrap {
  display: inline-flex;
}

.qe-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.qe-label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
  color: var(--lp-text-muted);
}

.qe-save {
  align-self: flex-end;
  padding: 4px 14px;
  border: none;
  border-radius: var(--lp-radius-xs);
  background: var(--lp-accent);
  color: var(--lp-accent-on-fill);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.qe-save:hover {
  background: var(--lp-accent-hover);
}
</style>
